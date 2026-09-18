from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .drive_backend import DriveBackend, DriveItem
from .drive_master import DriveMasterTransition, DriveMasterUnavailable
from .drive_transaction import BlobState
from .protocol import ProtocolError, strict_json_bytes, validate_master, validate_relative_path


class DriveReadBlocked(ProtocolError):
    """Canonical Drive data cannot be proven stable and SAFE for this read."""


@dataclass(frozen=True)
class DriveReadItem:
    path: str
    file_id: str
    sha256: str
    size: int
    content: bytes


@dataclass(frozen=True)
class DriveReadResult:
    canonical_epoch: int
    items: tuple[DriveReadItem, ...]

    def by_path(self) -> dict[str, DriveReadItem]:
        return {item.path: item for item in self.items}


class DriveCanonicalReader:
    """Normal canonical reader implementing the SAFE + epoch pre/post protocol.

    Normal readers never recover MASTER transitions. They require one valid SAFE
    MASTER before the read and again after the read with the same canonical epoch.
    Canonical path mappings are also re-resolved after the read so out-of-band
    Drive edits cannot silently produce a mixed snapshot without an epoch change.
    """

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        if not isinstance(hub_root_id, str) or not hub_root_id:
            raise ValueError("hub_root_id must be non-empty")
        self.hub_root_id = hub_root_id

    def _safe_master_epoch(self) -> int:
        try:
            _, raw = DriveMasterTransition.read_unique_master(self.drive, self.hub_root_id)
        except (DriveMasterUnavailable, ProtocolError) as exc:
            raise DriveReadBlocked(f"cannot resolve one exact MASTER.json: {exc}") from exc
        try:
            value = validate_master(strict_json_bytes(raw, label="MASTER.reader"))
        except ProtocolError as exc:
            raise DriveReadBlocked(f"MASTER.json is invalid: {exc}") from exc
        if value["canonical_read_status"] != "SAFE":
            raise DriveReadBlocked(
                f"canonical reads are not SAFE: state={value['state']} stage={value['current_stage']}"
            )
        return value["canonical_epoch"]

    def _canonical_root(self) -> DriveItem:
        matches = self.drive.list_children(self.hub_root_id, name="canonical")
        if len(matches) != 1:
            raise DriveReadBlocked(f"expected exactly one canonical folder, found {len(matches)}")
        item = matches[0]
        if item.trashed or not item.is_folder:
            raise DriveReadBlocked("canonical root is not a live folder")
        return item

    def _unique_child(
        self,
        parent_id: str,
        name: str,
        *,
        folder: bool,
        cache: dict[str, tuple[DriveItem, ...]] | None = None,
    ) -> DriveItem:
        if cache is None:
            matches = self.drive.list_children(parent_id, name=name)
        else:
            children = cache.get(parent_id)
            if children is None:
                children = tuple(self.drive.list_children(parent_id))
                cache[parent_id] = children
            matches = [item for item in children if item.name == name]
        if len(matches) != 1:
            raise DriveReadBlocked(
                f"canonical path component {parent_id}/{name} is not unique: {len(matches)} matches"
            )
        item = matches[0]
        if item.trashed or item.is_folder != folder:
            expected = "folder" if folder else "blob"
            raise DriveReadBlocked(f"canonical path component {parent_id}/{name} is not a live {expected}")
        return item

    def _resolve_path(
        self,
        canonical_root_id: str,
        path: str,
        *,
        cache: dict[str, tuple[DriveItem, ...]] | None = None,
    ) -> DriveItem:
        try:
            normalized = validate_relative_path(path, "canonical read path")
        except ProtocolError as exc:
            raise DriveReadBlocked(str(exc)) from exc
        parts = normalized.split("/")
        parent = canonical_root_id
        for segment in parts[:-1]:
            parent = self._unique_child(
                parent,
                segment,
                folder=True,
                cache=cache,
            ).file_id
        return self._unique_child(
            parent,
            parts[-1],
            folder=False,
            cache=cache,
        )

    def _read_item(
        self,
        canonical_root_id: str,
        path: str,
        *,
        cache: dict[str, tuple[DriveItem, ...]] | None = None,
    ) -> DriveReadItem:
        item = self._resolve_path(canonical_root_id, path, cache=cache)
        raw = self.drive.download(item.file_id)
        state = BlobState.from_bytes(raw)
        if not state.matches(item):
            raise DriveReadBlocked(f"canonical blob metadata/content mismatch: {path}")
        return DriveReadItem(path, item.file_id, state.sha256, state.size, raw)

    def read_paths(self, paths: Iterable[str]) -> DriveReadResult:
        requested = tuple(paths)
        if not requested:
            raise ValueError("at least one canonical path is required")
        if any(not isinstance(path, str) for path in requested):
            raise ValueError("canonical paths must be strings")
        if len(requested) != len(set(requested)):
            raise ValueError("canonical paths must be unique within one read")

        before_epoch = self._safe_master_epoch()
        before_root = self._canonical_root()
        before_cache: dict[str, tuple[DriveItem, ...]] = {}
        items = tuple(
            self._read_item(
                before_root.file_id,
                path,
                cache=before_cache,
            )
            for path in requested
        )

        # Re-resolve all path mappings after payload reads from a fresh snapshot.
        # Parent listings are reused only within each observation pass; pre/post
        # caches are deliberately separate so out-of-band edits remain visible.
        after_cache: dict[str, tuple[DriveItem, ...]] = {}
        for read in items:
            current = self._resolve_path(
                before_root.file_id,
                read.path,
                cache=after_cache,
            )
            if (
                current.file_id != read.file_id
                or current.sha256_checksum != read.sha256
                or current.size != read.size
            ):
                raise DriveReadBlocked(f"canonical path changed during read: {read.path}")

        after_root = self._canonical_root()
        if after_root.file_id != before_root.file_id:
            raise DriveReadBlocked("canonical root identity changed during read")
        after_epoch = self._safe_master_epoch()
        if after_epoch != before_epoch:
            raise DriveReadBlocked(
                f"canonical epoch changed during read: {before_epoch} -> {after_epoch}"
            )
        return DriveReadResult(before_epoch, items)

    def read_path(self, path: str) -> DriveReadItem:
        return self.read_paths((path,)).items[0]


__all__ = [
    "DriveCanonicalReader",
    "DriveReadBlocked",
    "DriveReadItem",
    "DriveReadResult",
]
