from __future__ import annotations

import hashlib
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_backend import (
    BLOB_MIME,
    DriveAlreadyExists,
    DriveBackend,
    DriveNotFound,
    DriveTransportError,
    DriveUncertainMutation,
)
from keelaryn_core.drive_rest import GoogleDriveBackend, HttpResponse
from keelaryn_core.protocol import ProtocolError


@dataclass
class _Action:
    response: HttpResponse | None = None
    error: Exception | None = None


class _ScriptedHttp:
    def __init__(self, *actions: _Action):
        self.actions = list(actions)
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, *, headers, body=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        if not self.actions:
            raise AssertionError("unexpected HTTP request")
        action = self.actions.pop(0)
        if action.error is not None:
            raise action.error
        assert action.response is not None
        return action.response


def _json_response(value: object, status: int = 200) -> _Action:
    return _Action(HttpResponse(status=status, headers={"Content-Type": "application/json"}, body=json.dumps(value).encode()))


def _empty_response(status: int) -> _Action:
    return _Action(HttpResponse(status=status, headers={}, body=b""))


def _blob_metadata(
    file_id: str,
    parent_id: str,
    name: str,
    content: bytes,
    *,
    version: int = 1,
    trashed: bool = False,
) -> dict[str, object]:
    return {
        "id": file_id,
        "name": name,
        "mimeType": BLOB_MIME,
        "parents": [parent_id],
        "version": str(version),
        "trashed": trashed,
        "size": str(len(content)),
        "sha256Checksum": hashlib.sha256(content).hexdigest(),
        "headRevisionId": f"r{version}",
    }


def _folder_metadata(file_id: str, parent_id: str | None, name: str, *, version: int = 1) -> dict[str, object]:
    value: dict[str, object] = {
        "id": file_id,
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "version": str(version),
        "trashed": False,
    }
    if parent_id is not None:
        value["parents"] = [parent_id]
    return value


class GoogleDriveRestTests(unittest.TestCase):
    def test_structurally_implements_backend_contract(self) -> None:
        self.assertIsInstance(GoogleDriveBackend("token", http=_ScriptedHttp()), DriveBackend)

    def test_generate_ids_uses_drive_generate_ids_once(self) -> None:
        http = _ScriptedHttp(_json_response({"ids": ["id-a", "id-b"], "space": "drive"}))
        drive = GoogleDriveBackend("token", http=http)

        self.assertEqual(drive.generate_ids(2), ["id-a", "id-b"])
        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "GET")
        split = urlsplit(str(call["url"]))
        self.assertEqual(split.path, "/drive/v3/files/generateIds")
        self.assertEqual(parse_qs(split.query)["count"], ["2"])
        self.assertEqual(parse_qs(split.query)["space"], ["drive"])
        self.assertEqual(parse_qs(split.query)["type"], ["files"])

    def test_create_blob_requires_pre_generated_id_before_http(self) -> None:
        http = _ScriptedHttp()
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(ProtocolError):
            drive.create_blob("parent", "a.bin", b"abc")
        self.assertEqual(http.calls, [])

    def test_create_blob_uses_reserved_id_and_multipart_payload(self) -> None:
        content = b"abc\x00payload"
        http = _ScriptedHttp(_json_response(_blob_metadata("reserved", "parent", "a.bin", content)))
        drive = GoogleDriveBackend("token", http=http)

        item = drive.create_blob("parent", "a.bin", content, file_id="reserved")
        self.assertEqual(item.file_id, "reserved")
        self.assertEqual(item.sha256_checksum, hashlib.sha256(content).hexdigest())
        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        split = urlsplit(str(call["url"]))
        self.assertEqual(split.path, "/upload/drive/v3/files")
        self.assertEqual(parse_qs(split.query)["uploadType"], ["multipart"])
        body = call["body"]
        self.assertIsInstance(body, bytes)
        assert isinstance(body, bytes)
        self.assertIn(b'"id":"reserved"', body)
        self.assertIn(b'"parents":["parent"]', body)
        self.assertIn(content, body)
        headers = call["headers"]
        assert isinstance(headers, dict)
        self.assertTrue(str(headers["Content-Type"]).startswith("multipart/related; boundary=keelaryn_"))
        self.assertEqual(headers["Authorization"], "Bearer token")

    def test_reserved_id_conflict_is_explicit_not_retried(self) -> None:
        http = _ScriptedHttp(_empty_response(409))
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(DriveAlreadyExists):
            drive.create_blob("parent", "a.bin", b"abc", file_id="reserved")
        self.assertEqual(len(http.calls), 1)

    def test_network_failure_on_mutation_is_uncertain_and_not_retried(self) -> None:
        http = _ScriptedHttp(_Action(error=ConnectionError("lost response")))
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(DriveUncertainMutation):
            drive.create_blob("parent", "a.bin", b"abc", file_id="reserved")
        self.assertEqual(len(http.calls), 1)

    def test_server_5xx_on_mutation_is_uncertain(self) -> None:
        http = _ScriptedHttp(_empty_response(503))
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(DriveUncertainMutation):
            drive.create_folder("parent", "folder", file_id="reserved")
        self.assertEqual(len(http.calls), 1)

    def test_network_failure_on_read_is_transport_error_not_not_found(self) -> None:
        http = _ScriptedHttp(_Action(error=ConnectionError("offline")))
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(DriveTransportError):
            drive.get("file")
        self.assertEqual(len(http.calls), 1)

    def test_get_404_is_typed_not_found(self) -> None:
        http = _ScriptedHttp(_empty_response(404))
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(DriveNotFound):
            drive.get("missing")

    def test_list_children_paginates_and_escapes_drive_query_literals(self) -> None:
        first = _blob_metadata("f1", "par'ent", "a'b", b"one")
        second = _blob_metadata("f2", "par'ent", "a'b", b"two")
        http = _ScriptedHttp(
            _json_response({"files": [first], "nextPageToken": "next"}),
            _json_response({"files": [second]}),
        )
        drive = GoogleDriveBackend("token", http=http)

        items = drive.list_children("par'ent", name="a'b")
        self.assertEqual([item.file_id for item in items], ["f1", "f2"])
        self.assertEqual(len(http.calls), 2)
        first_query = parse_qs(urlsplit(str(http.calls[0]["url"])).query)
        self.assertEqual(
            first_query["q"],
            ["'par\\'ent' in parents and name = 'a\\'b' and trashed = false"],
        )
        second_query = parse_qs(urlsplit(str(http.calls[1]["url"])).query)
        self.assertEqual(second_query["pageToken"], ["next"])

    def test_move_rename_reads_current_parent_then_patches_exact_object(self) -> None:
        old = _blob_metadata("file", "old-parent", "old.bin", b"abc", version=2)
        new = _blob_metadata("file", "new-parent", "new.bin", b"abc", version=3)
        http = _ScriptedHttp(_json_response(old), _json_response(new))
        drive = GoogleDriveBackend("token", http=http)

        result = drive.move_rename("file", "new-parent", "new.bin")
        self.assertEqual(result.parent_id, "new-parent")
        self.assertEqual(result.name, "new.bin")
        self.assertEqual(len(http.calls), 2)
        patch = http.calls[1]
        self.assertEqual(patch["method"], "PATCH")
        query = parse_qs(urlsplit(str(patch["url"])).query)
        self.assertEqual(query["addParents"], ["new-parent"])
        self.assertEqual(query["removeParents"], ["old-parent"])
        self.assertEqual(json.loads(bytes(patch["body"]).decode()), {"name": "new.bin"})

    def test_copy_blob_uses_reserved_destination_id(self) -> None:
        source = _blob_metadata("source", "src-parent", "source.bin", b"abc")
        copied = _blob_metadata("copy-id", "dest-parent", "copy.bin", b"abc")
        http = _ScriptedHttp(_json_response(source), _json_response(copied))
        drive = GoogleDriveBackend("token", http=http)

        result = drive.copy_blob("source", "dest-parent", "copy.bin", file_id="copy-id")
        self.assertEqual(result.file_id, "copy-id")
        self.assertEqual(len(http.calls), 2)
        copy_call = http.calls[1]
        self.assertEqual(copy_call["method"], "POST")
        self.assertEqual(urlsplit(str(copy_call["url"])).path, "/drive/v3/files/source/copy")
        self.assertEqual(
            json.loads(bytes(copy_call["body"]).decode()),
            {"id": "copy-id", "name": "copy.bin", "parents": ["dest-parent"]},
        )

    def test_exact_blob_replacement_rechecks_identity_then_uses_media_patch(self) -> None:
        old = b"bootstrap index"
        replacement = b"migrated index"
        old_metadata = _blob_metadata(
            "index-id",
            "hub-root",
            "INDEX.md",
            old,
            version=7,
        )
        old_metadata["mimeType"] = "text/markdown"
        new_metadata = _blob_metadata(
            "index-id",
            "hub-root",
            "INDEX.md",
            replacement,
            version=8,
        )
        new_metadata["mimeType"] = "text/markdown"
        expected = GoogleDriveBackend._item(old_metadata, label="TEST_INDEX")

        http = _ScriptedHttp(
            _json_response(old_metadata),
            _json_response(new_metadata),
        )
        drive = GoogleDriveBackend("token", http=http)

        result = drive.replace_blob_content(
            expected,
            replacement,
            label="drive.migration.router.candidate.index.replace",
        )

        self.assertEqual(result.file_id, expected.file_id)
        self.assertEqual(result.parent_id, expected.parent_id)
        self.assertEqual(result.name, expected.name)
        self.assertEqual(result.mime_type, expected.mime_type)
        self.assertEqual(result.sha256_checksum, hashlib.sha256(replacement).hexdigest())
        self.assertEqual(result.size, len(replacement))
        self.assertGreater(result.version, expected.version)
        self.assertEqual(len(http.calls), 2)

        preflight = http.calls[0]
        self.assertEqual(preflight["method"], "GET")
        self.assertEqual(urlsplit(str(preflight["url"])).path, "/drive/v3/files/index-id")

        update = http.calls[1]
        self.assertEqual(update["method"], "PATCH")
        split = urlsplit(str(update["url"]))
        self.assertEqual(split.path, "/upload/drive/v3/files/index-id")
        query = parse_qs(split.query)
        self.assertEqual(query["uploadType"], ["media"])
        self.assertEqual(query["supportsAllDrives"], ["true"])
        self.assertEqual(update["body"], replacement)
        headers = update["headers"]
        assert isinstance(headers, dict)
        self.assertEqual(headers["Content-Type"], "text/markdown")

    def test_exact_blob_replacement_rejects_stale_observation_before_mutation(self) -> None:
        expected_metadata = _blob_metadata(
            "index-id",
            "hub-root",
            "INDEX.md",
            b"old",
            version=7,
        )
        expected_metadata["mimeType"] = "text/markdown"
        changed_metadata = _blob_metadata(
            "index-id",
            "hub-root",
            "INDEX.md",
            b"externally changed",
            version=8,
        )
        changed_metadata["mimeType"] = "text/markdown"
        expected = GoogleDriveBackend._item(expected_metadata, label="TEST_INDEX")

        http = _ScriptedHttp(_json_response(changed_metadata))
        drive = GoogleDriveBackend("token", http=http)

        with self.assertRaises(ProtocolError):
            drive.replace_blob_content(
                expected,
                b"migrated index",
                label="drive.migration.router.candidate.index.replace",
            )

        self.assertEqual(len(http.calls), 1)
        self.assertEqual(http.calls[0]["method"], "GET")

    def test_in_place_content_update_is_forbidden_without_http(self) -> None:
        http = _ScriptedHttp()
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(ProtocolError):
            drive.update_content("file", b"replacement")
        self.assertEqual(http.calls, [])

    def test_metadata_with_multiple_parents_fails_closed(self) -> None:
        metadata = _folder_metadata("folder", None, "bad")
        metadata["parents"] = ["one", "two"]
        http = _ScriptedHttp(_json_response(metadata))
        drive = GoogleDriveBackend("token", http=http)
        with self.assertRaises(DriveTransportError):
            drive.get("folder")


if __name__ == "__main__":
    unittest.main(verbosity=2)
