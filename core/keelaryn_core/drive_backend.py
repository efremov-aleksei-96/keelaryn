from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


FOLDER_MIME = "application/vnd.google-apps.folder"
BLOB_MIME = "application/octet-stream"


@dataclass(frozen=True)
class DriveItem:
    """Backend-neutral metadata for one Drive object.

    Blob bytes are intentionally not stored here. A real Drive transport obtains
    content through ``download`` while metadata comes from ``get``/``list``.
    Keeping those channels separate prevents the simulator from accidentally
    depending on behavior that the REST API does not provide.
    """

    file_id: str
    parent_id: str | None
    name: str
    mime_type: str
    version: int
    trashed: bool
    size: int | None
    sha256_checksum: str | None
    head_revision_id: str | None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME


@runtime_checkable
class DriveBackend(Protocol):
    """Minimal object-store contract required by the zero-based Drive layers.

    Implementations may be an in-memory safety model or a real Drive API
    transport. Callers must not assume atomicity across methods, unique names, or
    fresh listing results beyond what the implementation explicitly guarantees.
    """

    def create_folder(
        self,
        parent_id: str,
        name: str,
        *,
        label: str = "drive.create_folder",
    ) -> DriveItem: ...

    def create_blob(
        self,
        parent_id: str,
        name: str,
        content: bytes,
        *,
        mime_type: str = BLOB_MIME,
        label: str = "drive.create_blob",
    ) -> DriveItem: ...

    def copy_blob(
        self,
        source_id: str,
        parent_id: str,
        name: str,
        *,
        label: str = "drive.copy_blob",
    ) -> DriveItem: ...

    def get(self, file_id: str, *, include_trashed: bool = True) -> DriveItem: ...

    def list_children(
        self,
        parent_id: str,
        *,
        name: str | None = None,
        include_trashed: bool = False,
    ) -> list[DriveItem]: ...

    def download(self, file_id: str) -> bytes: ...

    def move_rename(
        self,
        file_id: str,
        parent_id: str,
        name: str,
        *,
        label: str = "drive.move_rename",
    ) -> DriveItem: ...

    def update_content(
        self,
        file_id: str,
        content: bytes,
        *,
        label: str = "drive.update_content",
    ) -> DriveItem: ...

    def trash(self, file_id: str, *, label: str = "drive.trash") -> DriveItem: ...

    def delete(self, file_id: str, *, label: str = "drive.delete") -> None: ...

    def exact_name(self, parent_id: str, name: str) -> DriveItem | None: ...
