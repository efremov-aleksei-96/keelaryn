from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

from keelaryn_core.drive_backend import DriveAlreadyExists, DriveItem, DriveNotFound
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_rest import HttpResponse
from keelaryn_core.protocol import ProtocolError


_LIST_QUERY_RE = re.compile(
    r"^'((?:\\.|[^'])*)' in parents(?: and name = '((?:\\.|[^'])*)')?(?: and trashed = false)?$"
)


def _unescape_query_literal(value: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\":
            index += 1
            if index >= len(value):
                raise AssertionError("dangling Drive query escape")
        out.append(value[index])
        index += 1
    return "".join(out)


def _metadata(item: DriveItem) -> dict[str, object]:
    value: dict[str, object] = {
        "id": item.file_id,
        "name": item.name,
        "mimeType": item.mime_type,
        "version": str(item.version),
        "trashed": item.trashed,
    }
    if item.parent_id is not None:
        value["parents"] = [item.parent_id]
    if item.size is not None:
        value["size"] = str(item.size)
    if item.sha256_checksum is not None:
        value["sha256Checksum"] = item.sha256_checksum
    if item.head_revision_id is not None:
        value["headRevisionId"] = item.head_revision_id
    return value


def _json_response(value: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status=status, headers={"Content-Type": "application/json"}, body=json.dumps(value).encode())


class ModelDriveHttp:
    """Stateful in-process Drive API subset backed by DriveModel.

    ``fail_after_mutation`` simulates the hardest network boundary: Drive has
    already committed mutation N, but the client loses the response. The model
    remains changed and the HTTP call raises ConnectionError.
    """

    def __init__(self, drive: DriveModel, *, fail_after_mutation: int | None = None) -> None:
        self.drive = drive
        self.fail_after_mutation = fail_after_mutation
        self.mutation_count = 0
        self.calls: list[tuple[str, str]] = []

    def _after_mutation(self) -> None:
        self.mutation_count += 1
        if self.fail_after_mutation == self.mutation_count:
            self.fail_after_mutation = None
            raise ConnectionError(f"simulated lost response after mutation {self.mutation_count}")

    @staticmethod
    def _body_json(body: bytes | None) -> dict[str, object]:
        if body is None:
            raise AssertionError("JSON request body missing")
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise AssertionError("JSON request root must be object")
        return value

    @staticmethod
    def _multipart(headers, body: bytes | None) -> tuple[dict[str, object], bytes, str]:
        if body is None:
            raise AssertionError("multipart body missing")
        content_type = str(headers.get("Content-Type", ""))
        match = re.fullmatch(r"multipart/related; boundary=([A-Za-z0-9_-]+)", content_type)
        if not match:
            raise AssertionError(f"invalid multipart content type: {content_type}")
        marker = ("--" + match.group(1)).encode("ascii")
        pieces = body.split(marker)
        if len(pieces) != 4 or pieces[0] != b"" or pieces[3] != b"--\r\n":
            raise AssertionError("unexpected multipart framing")

        def payload(piece: bytes) -> tuple[bytes, bytes]:
            if not piece.startswith(b"\r\n") or not piece.endswith(b"\r\n"):
                raise AssertionError("unexpected multipart part framing")
            header_bytes, data = piece[2:].split(b"\r\n\r\n", 1)
            return header_bytes, data[:-2]

        meta_headers, meta_payload = payload(pieces[1])
        media_headers, media_payload = payload(pieces[2])
        if b"Content-Type: application/json" not in meta_headers:
            raise AssertionError("multipart metadata content type missing")
        media_match = re.search(rb"Content-Type: ([^\r\n]+)", media_headers)
        if not media_match:
            raise AssertionError("multipart media content type missing")
        metadata = json.loads(meta_payload.decode("utf-8"))
        if not isinstance(metadata, dict):
            raise AssertionError("multipart metadata must be object")
        return metadata, media_payload, media_match.group(1).decode("ascii")

    def request(self, method: str, url: str, *, headers, body=None) -> HttpResponse:
        self.calls.append((method, url))
        split = urlsplit(url)
        query = parse_qs(split.query)
        path = split.path

        try:
            if method == "GET" and path == "/drive/v3/files/generateIds":
                count = int(query.get("count", ["1"])[0])
                return _json_response({"ids": self.drive.generate_ids(count), "space": "drive"})

            if method == "GET" and path == "/drive/v3/files":
                q = query.get("q", [None])[0]
                if q is None:
                    raise AssertionError("files.list query missing")
                match = _LIST_QUERY_RE.fullmatch(q)
                if not match:
                    raise AssertionError(f"unsupported files.list query: {q}")
                parent_id = _unescape_query_literal(match.group(1))
                name = _unescape_query_literal(match.group(2)) if match.group(2) is not None else None
                include_trashed = "trashed = false" not in q
                items = self.drive.list_children(parent_id, name=name, include_trashed=include_trashed)
                return _json_response({"files": [_metadata(item) for item in items]})

            if method == "GET" and path.startswith("/drive/v3/files/"):
                file_id = unquote(path.removeprefix("/drive/v3/files/"))
                if query.get("alt") == ["media"]:
                    return HttpResponse(status=200, headers={"Content-Type": "application/octet-stream"}, body=self.drive.download(file_id))
                return _json_response(_metadata(self.drive.get(file_id)))

            if method == "POST" and path == "/drive/v3/files":
                value = self._body_json(body)
                item = self.drive.create_folder(
                    str(value["parents"][0]),
                    str(value["name"]),
                    file_id=str(value["id"]),
                    label="http.create_folder",
                )
                self._after_mutation()
                return _json_response(_metadata(item))

            if method == "POST" and path == "/upload/drive/v3/files":
                metadata, content, mime_type = self._multipart(headers, body)
                item = self.drive.create_blob(
                    str(metadata["parents"][0]),
                    str(metadata["name"]),
                    content,
                    mime_type=mime_type,
                    file_id=str(metadata["id"]),
                    label="http.create_blob",
                )
                self._after_mutation()
                return _json_response(_metadata(item))

            copy_match = re.fullmatch(r"/drive/v3/files/([^/]+)/copy", path)
            if method == "POST" and copy_match:
                source_id = unquote(copy_match.group(1))
                value = self._body_json(body)
                item = self.drive.copy_blob(
                    source_id,
                    str(value["parents"][0]),
                    str(value["name"]),
                    file_id=str(value["id"]),
                    label="http.copy_blob",
                )
                self._after_mutation()
                return _json_response(_metadata(item))

            file_match = re.fullmatch(r"/drive/v3/files/([^/]+)", path)
            if method == "PATCH" and file_match:
                file_id = unquote(file_match.group(1))
                value = self._body_json(body)
                if value.get("trashed") is True:
                    item = self.drive.trash(file_id, label="http.trash")
                else:
                    current = self.drive.get(file_id, include_trashed=False)
                    add_parent = query.get("addParents", [None])[0]
                    remove_parent = query.get("removeParents", [None])[0]
                    if add_parent is not None:
                        if remove_parent != current.parent_id:
                            raise AssertionError("removeParents does not match model parent")
                        parent_id = add_parent
                    else:
                        parent_id = current.parent_id
                    if parent_id is None:
                        raise AssertionError("cannot move to parentless location")
                    item = self.drive.move_rename(
                        file_id,
                        parent_id,
                        str(value.get("name", current.name)),
                        label="http.move_rename",
                    )
                self._after_mutation()
                return _json_response(_metadata(item))

            if method == "DELETE" and file_match:
                file_id = unquote(file_match.group(1))
                self.drive.delete(file_id, label="http.delete")
                self._after_mutation()
                return HttpResponse(status=204, headers={}, body=b"")

            raise AssertionError(f"unsupported Drive HTTP request: {method} {url}")

        except DriveNotFound:
            return HttpResponse(status=404, headers={}, body=b"")
        except DriveAlreadyExists:
            return HttpResponse(status=409, headers={}, body=b"")
        except ProtocolError as exc:
            return _json_response({"error": str(exc)}, status=400)
