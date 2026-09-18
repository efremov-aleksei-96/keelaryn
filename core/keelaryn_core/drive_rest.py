from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from hashlib import sha256
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .drive_backend import (
    BLOB_MIME,
    FOLDER_MIME,
    DriveAlreadyExists,
    DriveBackend,
    DriveItem,
    DriveNotFound,
    DriveTransportError,
    DriveUncertainMutation,
)
from .protocol import ProtocolError, strict_json_bytes


API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
FILE_FIELDS = "id,name,mimeType,parents,version,trashed,size,sha256Checksum,headRevisionId"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> HttpResponse: ...


class UrllibHttpClient:
    """Small no-retry HTTP client.

    Retry policy intentionally lives above this layer. Retrying a Drive mutation
    inside the HTTP client could duplicate or reorder state changes after an
    uncertain network outcome.
    """

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> HttpResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return HttpResponse(
                    status=int(response.status),
                    headers={key: value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except HTTPError as exc:
            return HttpResponse(
                status=int(exc.code),
                headers={key: value for key, value in exc.headers.items()} if exc.headers else {},
                body=exc.read(),
            )
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise ConnectionError(str(exc)) from exc


class GoogleDriveBackend:
    """Google Drive API v3 implementation of :class:`DriveBackend`.

    This adapter performs one HTTP attempt per method call. Core-created objects
    must use pre-generated IDs so a lost create/copy response can be resolved by
    exact ``files.get(fileId)`` after restart. Canonical content is never updated
    in place; ``update_content`` is deliberately disabled.
    """

    def __init__(
        self,
        access_token: str | Callable[[], str],
        *,
        http: HttpClient | None = None,
    ) -> None:
        self._token_source = access_token
        self.http = http or UrllibHttpClient()

    def _token(self) -> str:
        try:
            token = self._token_source() if callable(self._token_source) else self._token_source
        except Exception as exc:
            raise DriveTransportError("Drive access token provider failed") from exc
        if not isinstance(token, str) or not token or any(ch.isspace() for ch in token):
            raise DriveTransportError("Drive access token is empty or malformed")
        return token

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        return headers

    @staticmethod
    def _url(base: str, path: str, params: list[tuple[str, str]] | None = None) -> str:
        url = f"{base}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode(params)
        return url

    @staticmethod
    def _json_body(value: object) -> bytes:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        mutation: bool = False,
        conflict_means_exists: bool = False,
    ) -> HttpResponse:
        headers = self._headers(content_type=content_type)
        try:
            response = self.http.request(method, url, headers=headers, body=body)
        except Exception as exc:
            if mutation:
                raise DriveUncertainMutation(f"Drive mutation outcome is uncertain: {method} {url}") from exc
            raise DriveTransportError(f"Drive request failed before an authoritative response: {method} {url}") from exc

        if 200 <= response.status < 300:
            return response
        if response.status == 404:
            raise DriveNotFound(f"Drive object not found: {method} {url}")
        if response.status == 409 and conflict_means_exists:
            raise DriveAlreadyExists(f"Drive reserved file ID already exists: {method} {url}")
        if mutation and (response.status in {408, 429} or 500 <= response.status <= 599):
            raise DriveUncertainMutation(
                f"Drive mutation returned non-authoritative HTTP {response.status}: {method} {url}"
            )
        raise DriveTransportError(f"Drive API HTTP {response.status}: {method} {url}")

    @staticmethod
    def _parse_json(response: HttpResponse, *, label: str) -> object:
        return strict_json_bytes(response.body, label=label)

    @staticmethod
    def _parse_int(value: object, *, label: str) -> int:
        if isinstance(value, bool):
            raise DriveTransportError(f"{label}: boolean is not an integer")
        if isinstance(value, int):
            result = value
        elif isinstance(value, str) and value.isdigit():
            result = int(value)
        else:
            raise DriveTransportError(f"{label}: invalid integer")
        if result < 0:
            raise DriveTransportError(f"{label}: negative integer")
        return result

    @classmethod
    def _item(cls, value: object, *, label: str) -> DriveItem:
        if not isinstance(value, dict):
            raise DriveTransportError(f"{label}: expected object")
        try:
            file_id = value["id"]
            name = value["name"]
            mime_type = value["mimeType"]
            version_raw = value["version"]
            trashed = value["trashed"]
        except KeyError as exc:
            raise DriveTransportError(f"{label}: required Drive metadata missing: {exc.args[0]}") from exc
        if not all(isinstance(field, str) and field for field in (file_id, name, mime_type)):
            raise DriveTransportError(f"{label}: invalid id/name/mimeType")
        if not isinstance(trashed, bool):
            raise DriveTransportError(f"{label}.trashed: invalid boolean")

        parents_raw = value.get("parents", [])
        if not isinstance(parents_raw, list) or any(not isinstance(parent, str) or not parent for parent in parents_raw):
            raise DriveTransportError(f"{label}.parents: invalid array")
        if len(parents_raw) > 1:
            raise DriveTransportError(f"{label}.parents: multiple parents are unsupported")
        parent_id = parents_raw[0] if parents_raw else None

        size_raw = value.get("size")
        size = None if size_raw is None else cls._parse_int(size_raw, label=f"{label}.size")
        checksum = value.get("sha256Checksum")
        if checksum is not None:
            if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdefABCDEF" for c in checksum):
                raise DriveTransportError(f"{label}.sha256Checksum: invalid SHA-256")
            checksum = checksum.lower()
        revision = value.get("headRevisionId")
        if revision is not None and (not isinstance(revision, str) or not revision):
            raise DriveTransportError(f"{label}.headRevisionId: invalid revision")

        return DriveItem(
            file_id=file_id,
            parent_id=parent_id,
            name=name,
            mime_type=mime_type,
            version=cls._parse_int(version_raw, label=f"{label}.version"),
            trashed=trashed,
            size=size,
            sha256_checksum=checksum,
            head_revision_id=revision,
        )

    @staticmethod
    def _require_reserved_id(file_id: str | None) -> str:
        if not isinstance(file_id, str) or not file_id:
            raise ProtocolError("Google Drive creation requires a pre-generated file ID")
        return file_id

    @staticmethod
    def _q_literal(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def generate_ids(self, count: int) -> list[str]:
        if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > 1000:
            raise ProtocolError("Drive ID reservation count must be 1..1000")
        url = self._url(
            API_BASE,
            "files/generateIds",
            [("count", str(count)), ("space", "drive"), ("type", "files")],
        )
        response = self._request("GET", url)
        value = self._parse_json(response, label="DRIVE_GENERATE_IDS")
        if not isinstance(value, dict) or not isinstance(value.get("ids"), list):
            raise DriveTransportError("DRIVE_GENERATE_IDS: ids array missing")
        ids = value["ids"]
        if len(ids) != count or any(not isinstance(file_id, str) or not file_id for file_id in ids):
            raise DriveTransportError("DRIVE_GENERATE_IDS: invalid ID count or value")
        if len(set(ids)) != len(ids):
            raise DriveTransportError("DRIVE_GENERATE_IDS: duplicate IDs returned")
        return list(ids)

    def get(self, file_id: str, *, include_trashed: bool = True) -> DriveItem:
        url = self._url(
            API_BASE,
            f"files/{quote(file_id, safe='')}",
            [("supportsAllDrives", "true"), ("fields", FILE_FIELDS)],
        )
        response = self._request("GET", url)
        item = self._item(self._parse_json(response, label="DRIVE_GET"), label="DRIVE_GET")
        if item.file_id != file_id:
            raise DriveTransportError("DRIVE_GET: response ID does not match request")
        if item.trashed and not include_trashed:
            raise DriveNotFound(f"Drive object is not live: {file_id}")
        return item

    def list_children(
        self,
        parent_id: str,
        *,
        name: str | None = None,
        include_trashed: bool = False,
    ) -> list[DriveItem]:
        clauses = [f"{self._q_literal(parent_id)} in parents"]
        if name is not None:
            clauses.append(f"name = {self._q_literal(name)}")
        if not include_trashed:
            clauses.append("trashed = false")
        query = " and ".join(clauses)

        result: list[DriveItem] = []
        page_token: str | None = None
        while True:
            params = [
                ("q", query),
                ("spaces", "drive"),
                ("pageSize", "1000"),
                ("supportsAllDrives", "true"),
                ("includeItemsFromAllDrives", "true"),
                ("fields", f"nextPageToken,files({FILE_FIELDS})"),
            ]
            if page_token is not None:
                params.append(("pageToken", page_token))
            response = self._request("GET", self._url(API_BASE, "files", params))
            value = self._parse_json(response, label="DRIVE_LIST")
            if not isinstance(value, dict) or not isinstance(value.get("files"), list):
                raise DriveTransportError("DRIVE_LIST: files array missing")
            result.extend(self._item(item, label="DRIVE_LIST.files[]") for item in value["files"])
            next_token = value.get("nextPageToken")
            if next_token is None:
                break
            if not isinstance(next_token, str) or not next_token:
                raise DriveTransportError("DRIVE_LIST.nextPageToken: invalid token")
            page_token = next_token

        result.sort(key=lambda item: item.file_id)
        return result

    def exact_name(self, parent_id: str, name: str) -> DriveItem | None:
        matches = self.list_children(parent_id, name=name)
        if not matches:
            return None
        if len(matches) != 1:
            raise ProtocolError(f"ambiguous Drive path segment: {name!r} under {parent_id}")
        return matches[0]

    def download(self, file_id: str) -> bytes:
        url = self._url(
            API_BASE,
            f"files/{quote(file_id, safe='')}",
            [("alt", "media"), ("supportsAllDrives", "true")],
        )
        response = self._request("GET", url)
        return bytes(response.body)

    def create_folder(
        self,
        parent_id: str,
        name: str,
        *,
        file_id: str | None = None,
        label: str = "drive.create_folder",
    ) -> DriveItem:
        del label
        object_id = self._require_reserved_id(file_id)
        body = self._json_body(
            {"id": object_id, "name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        )
        url = self._url(
            API_BASE,
            "files",
            [("supportsAllDrives", "true"), ("fields", FILE_FIELDS)],
        )
        response = self._request(
            "POST",
            url,
            body=body,
            content_type="application/json; charset=UTF-8",
            mutation=True,
            conflict_means_exists=True,
        )
        item = self._item(self._parse_json(response, label="DRIVE_CREATE_FOLDER"), label="DRIVE_CREATE_FOLDER")
        if item.file_id != object_id:
            raise DriveTransportError("DRIVE_CREATE_FOLDER: response ID mismatch")
        return item

    @staticmethod
    def _multipart(metadata: bytes, content: bytes, mime_type: str, seed: str) -> tuple[str, bytes]:
        counter = 0
        while True:
            digest = sha256(seed.encode("utf-8") + counter.to_bytes(4, "big") + content).hexdigest()[:40]
            boundary = f"keelaryn_{digest}"
            marker = boundary.encode("ascii")
            if marker not in metadata and marker not in content:
                break
            counter += 1
            if counter > 100:
                raise ProtocolError("unable to construct collision-free multipart boundary")
        body = (
            b"--" + marker + b"\r\n"
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            + metadata
            + b"\r\n--"
            + marker
            + b"\r\nContent-Type: "
            + mime_type.encode("ascii")
            + b"\r\n\r\n"
            + content
            + b"\r\n--"
            + marker
            + b"--\r\n"
        )
        return boundary, body

    def create_blob(
        self,
        parent_id: str,
        name: str,
        content: bytes,
        *,
        mime_type: str = BLOB_MIME,
        file_id: str | None = None,
        label: str = "drive.create_blob",
    ) -> DriveItem:
        del label
        if mime_type == FOLDER_MIME or mime_type.startswith("application/vnd.google-apps."):
            raise ProtocolError("Drive backend v1 creates blob files only")
        try:
            mime_type.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ProtocolError("blob MIME type must be ASCII") from exc
        object_id = self._require_reserved_id(file_id)
        raw = bytes(content)
        metadata = self._json_body(
            {"id": object_id, "name": name, "mimeType": mime_type, "parents": [parent_id]}
        )
        boundary, body = self._multipart(metadata, raw, mime_type, object_id)
        url = self._url(
            UPLOAD_BASE,
            "files",
            [("uploadType", "multipart"), ("supportsAllDrives", "true"), ("fields", FILE_FIELDS)],
        )
        response = self._request(
            "POST",
            url,
            body=body,
            content_type=f"multipart/related; boundary={boundary}",
            mutation=True,
            conflict_means_exists=True,
        )
        item = self._item(self._parse_json(response, label="DRIVE_CREATE_BLOB"), label="DRIVE_CREATE_BLOB")
        if item.file_id != object_id:
            raise DriveTransportError("DRIVE_CREATE_BLOB: response ID mismatch")
        return item

    def copy_blob(
        self,
        source_id: str,
        parent_id: str,
        name: str,
        *,
        file_id: str | None = None,
        label: str = "drive.copy_blob",
    ) -> DriveItem:
        del label
        source = self.get(source_id, include_trashed=False)
        if source.is_folder or source.size is None or source.sha256_checksum is None:
            raise ProtocolError("Drive backend v1 copies blob files only")
        object_id = self._require_reserved_id(file_id)
        url = self._url(
            API_BASE,
            f"files/{quote(source_id, safe='')}/copy",
            [("supportsAllDrives", "true"), ("fields", FILE_FIELDS)],
        )
        body = self._json_body({"id": object_id, "name": name, "parents": [parent_id]})
        response = self._request(
            "POST",
            url,
            body=body,
            content_type="application/json; charset=UTF-8",
            mutation=True,
            conflict_means_exists=True,
        )
        item = self._item(self._parse_json(response, label="DRIVE_COPY_BLOB"), label="DRIVE_COPY_BLOB")
        if item.file_id != object_id:
            raise DriveTransportError("DRIVE_COPY_BLOB: response ID mismatch")
        return item

    def move_rename(
        self,
        file_id: str,
        parent_id: str,
        name: str,
        *,
        label: str = "drive.move_rename",
    ) -> DriveItem:
        del label
        current = self.get(file_id, include_trashed=False)
        if current.parent_id == parent_id and current.name == name:
            return current
        params: list[tuple[str, str]] = [("supportsAllDrives", "true"), ("fields", FILE_FIELDS)]
        if current.parent_id != parent_id:
            if current.parent_id is None:
                raise ProtocolError(f"cannot move parentless Drive object: {file_id}")
            params.extend([("addParents", parent_id), ("removeParents", current.parent_id)])
        url = self._url(API_BASE, f"files/{quote(file_id, safe='')}", params)
        response = self._request(
            "PATCH",
            url,
            body=self._json_body({"name": name}),
            content_type="application/json; charset=UTF-8",
            mutation=True,
        )
        item = self._item(self._parse_json(response, label="DRIVE_MOVE_RENAME"), label="DRIVE_MOVE_RENAME")
        if item.file_id != file_id:
            raise DriveTransportError("DRIVE_MOVE_RENAME: response ID mismatch")
        return item

    def replace_blob_content(
        self,
        expected: DriveItem,
        content: bytes,
        *,
        label: str = "drive.replace_blob_content",
    ) -> DriveItem:
        del label
        if (
            expected.trashed
            or expected.is_folder
            or expected.parent_id is None
            or expected.size is None
            or expected.sha256_checksum is None
            or expected.mime_type.startswith("application/vnd.google-apps.")
        ):
            raise ProtocolError("exact blob replacement requires one live regular blob observation")

        current = self.get(expected.file_id, include_trashed=False)
        if current != expected:
            raise ProtocolError("exact blob observation changed before replacement")

        raw = bytes(content)
        url = self._url(
            UPLOAD_BASE,
            f"files/{quote(expected.file_id, safe='')}",
            [
                ("uploadType", "media"),
                ("supportsAllDrives", "true"),
                ("fields", FILE_FIELDS),
            ],
        )
        response = self._request(
            "PATCH",
            url,
            body=raw,
            content_type=expected.mime_type,
            mutation=True,
        )
        item = self._item(
            self._parse_json(response, label="DRIVE_REPLACE_BLOB_CONTENT"),
            label="DRIVE_REPLACE_BLOB_CONTENT",
        )
        if (
            item.file_id != expected.file_id
            or item.parent_id != expected.parent_id
            or item.name != expected.name
            or item.mime_type != expected.mime_type
            or item.trashed
            or item.is_folder
            or item.version <= expected.version
            or item.size != len(raw)
            or item.sha256_checksum != sha256(raw).hexdigest()
        ):
            raise DriveTransportError(
                "DRIVE_REPLACE_BLOB_CONTENT: response does not confirm exact replacement"
            )
        return item

    def update_content(
        self,
        file_id: str,
        content: bytes,
        *,
        label: str = "drive.update_content",
    ) -> DriveItem:
        del file_id, content, label
        raise ProtocolError("Drive backend v1 forbids in-place content replacement")

    def trash(self, file_id: str, *, label: str = "drive.trash") -> DriveItem:
        del label
        url = self._url(
            API_BASE,
            f"files/{quote(file_id, safe='')}",
            [("supportsAllDrives", "true"), ("fields", FILE_FIELDS)],
        )
        response = self._request(
            "PATCH",
            url,
            body=self._json_body({"trashed": True}),
            content_type="application/json; charset=UTF-8",
            mutation=True,
        )
        item = self._item(self._parse_json(response, label="DRIVE_TRASH"), label="DRIVE_TRASH")
        if item.file_id != file_id or not item.trashed:
            raise DriveTransportError("DRIVE_TRASH: response does not confirm trashed object")
        return item

    def delete(self, file_id: str, *, label: str = "drive.delete") -> None:
        del label
        url = self._url(
            API_BASE,
            f"files/{quote(file_id, safe='')}",
            [("supportsAllDrives", "true")],
        )
        self._request("DELETE", url, mutation=True)


__all__ = [
    "GoogleDriveBackend",
    "HttpClient",
    "HttpResponse",
    "UrllibHttpClient",
]
