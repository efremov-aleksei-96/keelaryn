from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Iterable

from .drive_backend import BLOB_MIME, FOLDER_MIME, DriveItem
from .protocol import FaultInjector, ProtocolError


class DriveModel:
    """Small deterministic Drive-like object store used only for safety simulation.

    It deliberately allows duplicate names and non-atomic multi-object sequences.
    Every mutation has a fault checkpoint. Observations can be forced stale once to
    make callers prove that discovery data is not treated as commit authority.

    Metadata and blob content are stored separately so this model obeys the same
    boundary as a real Drive backend: ``get``/``list`` return metadata while
    ``download`` returns bytes.
    """

    def __init__(self, *, fault: FaultInjector | None = None) -> None:
        self.fault = fault or FaultInjector()
        self._next_id = 1
        self._next_revision = 1
        self._items: dict[str, DriveItem] = {
            "root": DriveItem(
                file_id="root",
                parent_id=None,
                name="root",
                mime_type=FOLDER_MIME,
                version=1,
                trashed=False,
                size=None,
                sha256_checksum=None,
                head_revision_id=None,
            )
        }
        self._content: dict[str, bytes] = {}
        self._stale_get: dict[str, DriveItem] = {}
        self._stale_list: dict[tuple[str, str | None], list[DriveItem]] = {}

    def _id(self) -> str:
        value = f"f{self._next_id:08d}"
        self._next_id += 1
        return value

    def _revision(self) -> str:
        value = f"r{self._next_revision:08d}"
        self._next_revision += 1
        return value

    def _require_parent(self, parent_id: str) -> DriveItem:
        parent = self._items.get(parent_id)
        if parent is None or parent.trashed or not parent.is_folder:
            raise ProtocolError(f"invalid Drive parent: {parent_id}")
        return parent

    def _require(self, file_id: str) -> DriveItem:
        item = self._items.get(file_id)
        if item is None:
            raise ProtocolError(f"Drive object not found: {file_id}")
        return item

    def create_folder(self, parent_id: str, name: str, *, label: str = "drive.create_folder") -> DriveItem:
        self._require_parent(parent_id)
        item = DriveItem(
            file_id=self._id(),
            parent_id=parent_id,
            name=name,
            mime_type=FOLDER_MIME,
            version=1,
            trashed=False,
            size=None,
            sha256_checksum=None,
            head_revision_id=None,
        )
        self._items[item.file_id] = item
        self.fault.hit(f"{label}.after")
        return replace(item)

    def create_blob(
        self,
        parent_id: str,
        name: str,
        content: bytes,
        *,
        mime_type: str = BLOB_MIME,
        label: str = "drive.create_blob",
    ) -> DriveItem:
        self._require_parent(parent_id)
        if mime_type == FOLDER_MIME:
            raise ProtocolError("blob cannot use folder MIME type")
        raw = bytes(content)
        item = DriveItem(
            file_id=self._id(),
            parent_id=parent_id,
            name=name,
            mime_type=mime_type,
            version=1,
            trashed=False,
            size=len(raw),
            sha256_checksum=sha256(raw).hexdigest(),
            head_revision_id=self._revision(),
        )
        self._items[item.file_id] = item
        self._content[item.file_id] = raw
        self.fault.hit(f"{label}.after")
        return replace(item)

    def copy_blob(
        self,
        source_id: str,
        parent_id: str,
        name: str,
        *,
        label: str = "drive.copy_blob",
    ) -> DriveItem:
        source = self._require(source_id)
        if source.trashed or source.is_folder or source.file_id not in self._content:
            raise ProtocolError(f"source is not a live blob: {source_id}")
        return self.create_blob(
            parent_id,
            name,
            self._content[source.file_id],
            mime_type=source.mime_type,
            label=label,
        )

    def get(self, file_id: str, *, include_trashed: bool = True) -> DriveItem:
        if file_id in self._stale_get:
            item = self._stale_get.pop(file_id)
        else:
            item = self._require(file_id)
        if item.trashed and not include_trashed:
            raise ProtocolError(f"Drive object is trashed: {file_id}")
        return replace(item)

    def list_children(
        self,
        parent_id: str,
        *,
        name: str | None = None,
        include_trashed: bool = False,
    ) -> list[DriveItem]:
        self._require_parent(parent_id)
        key = (parent_id, name)
        if key in self._stale_list:
            values = self._stale_list.pop(key)
            return [replace(item) for item in values]
        values = [
            item
            for item in self._items.values()
            if item.parent_id == parent_id
            and (include_trashed or not item.trashed)
            and (name is None or item.name == name)
        ]
        values.sort(key=lambda item: item.file_id)
        return [replace(item) for item in values]

    def download(self, file_id: str) -> bytes:
        item = self._require(file_id)
        if item.trashed or item.is_folder or file_id not in self._content:
            raise ProtocolError(f"Drive object is not downloadable blob: {file_id}")
        return bytes(self._content[file_id])

    def move_rename(
        self,
        file_id: str,
        parent_id: str,
        name: str,
        *,
        label: str = "drive.move_rename",
    ) -> DriveItem:
        self._require_parent(parent_id)
        current = self._require(file_id)
        if current.trashed:
            raise ProtocolError(f"cannot move trashed object: {file_id}")
        updated = replace(current, parent_id=parent_id, name=name, version=current.version + 1)
        self._items[file_id] = updated
        self.fault.hit(f"{label}.after")
        return replace(updated)

    def update_content(
        self,
        file_id: str,
        content: bytes,
        *,
        label: str = "drive.update_content",
    ) -> DriveItem:
        current = self._require(file_id)
        if current.trashed or current.is_folder:
            raise ProtocolError(f"cannot update non-live blob: {file_id}")
        raw = bytes(content)
        updated = replace(
            current,
            size=len(raw),
            sha256_checksum=sha256(raw).hexdigest(),
            version=current.version + 1,
            head_revision_id=self._revision(),
        )
        self._items[file_id] = updated
        self._content[file_id] = raw
        self.fault.hit(f"{label}.after")
        return replace(updated)

    def trash(self, file_id: str, *, label: str = "drive.trash") -> DriveItem:
        current = self._require(file_id)
        if current.file_id == "root":
            raise ProtocolError("cannot trash root")
        updated = replace(current, trashed=True, version=current.version + 1)
        self._items[file_id] = updated
        self.fault.hit(f"{label}.after")
        return replace(updated)

    def delete(self, file_id: str, *, label: str = "drive.delete") -> None:
        current = self._require(file_id)
        if current.file_id == "root":
            raise ProtocolError("cannot delete root")
        if current.is_folder:
            children = [item for item in self._items.values() if item.parent_id == file_id and not item.trashed]
            if children:
                raise ProtocolError("cannot delete non-empty model folder")
        del self._items[file_id]
        self._content.pop(file_id, None)
        self.fault.hit(f"{label}.after")

    def exact_name(self, parent_id: str, name: str) -> DriveItem | None:
        matches = self.list_children(parent_id, name=name)
        if not matches:
            return None
        if len(matches) != 1:
            raise ProtocolError(f"ambiguous Drive path segment: {name!r} under {parent_id}")
        return matches[0]

    def inject_stale_get(self, file_id: str, observed: DriveItem) -> None:
        self._stale_get[file_id] = replace(observed)

    def inject_stale_list(self, parent_id: str, name: str | None, observed: Iterable[DriveItem]) -> None:
        self._stale_list[(parent_id, name)] = [replace(item) for item in observed]

    def all_items(self) -> list[DriveItem]:
        return [replace(self._items[key]) for key in sorted(self._items)]
