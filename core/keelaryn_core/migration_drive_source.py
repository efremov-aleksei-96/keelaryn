from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any

from .drive_backend import DriveBackend, DriveItem
from .migration_common import (
    MAX_MIGRATION_FILE_BYTES,
    MAX_MIGRATION_TOTAL_BYTES,
    MigrationPack,
    MigrationPackBlocked,
    MigrationSource,
    real_directory,
    relative_path,
    small_file,
)
from .migration_pack import build_migration_pack, verify_migration_pack
from .migration_source import (
    parse_selection,
    parse_source,
    verify_migration_source,
)
from .protocol import ProtocolError, canonical_json_bytes


class DriveMigrationSourceBlocked(MigrationPackBlocked):
    """A live legacy Drive source cannot be observed as one exact read-only set."""


class DriveMigrationSourceReader:
    """Strict read-only reader for a legacy Hub rooted at one exact Drive folder ID."""

    def __init__(self, drive: DriveBackend, source_root_id: str):
        if not isinstance(source_root_id, str) or not source_root_id:
            raise DriveMigrationSourceBlocked("legacy Drive source root ID is invalid")
        self.drive = drive
        self.source_root_id = source_root_id

    def _root(self) -> DriveItem:
        try:
            root = self.drive.get(self.source_root_id, include_trashed=False)
        except ProtocolError as exc:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source root is not readable"
            ) from exc
        if root.trashed or not root.is_folder:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source root is not a live folder"
            )
        return root

    def _resolve(self, source: str) -> DriveItem:
        path = relative_path(source, "legacy Drive migration source")
        segments = path.split("/")
        current = self._root()
        try:
            for index, segment in enumerate(segments):
                children = self.drive.list_children(current.file_id)
                folded = [
                    child
                    for child in children
                    if child.name.casefold() == segment.casefold()
                ]
                if len(folded) != 1 or folded[0].name != segment:
                    raise DriveMigrationSourceBlocked(
                        "legacy Drive source path is missing, duplicated, or case-conflicting"
                    )
                current = folded[0]
                if current.trashed:
                    raise DriveMigrationSourceBlocked(
                        "legacy Drive source path resolves to trashed content"
                    )
                if index < len(segments) - 1:
                    if not current.is_folder:
                        raise DriveMigrationSourceBlocked(
                            "legacy Drive source path traverses a non-folder"
                        )
                elif current.is_folder:
                    raise DriveMigrationSourceBlocked(
                        "legacy Drive migration source resolves to a folder"
                    )
            return current
        except DriveMigrationSourceBlocked:
            raise
        except ProtocolError as exc:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source path resolution failed"
            ) from exc

    @staticmethod
    def _validate_download(item: DriveItem, raw: bytes) -> None:
        if item.size is not None and item.size != len(raw):
            raise DriveMigrationSourceBlocked(
                "legacy Drive source size disagrees with downloaded bytes"
            )
        if (
            item.sha256_checksum is not None
            and item.sha256_checksum != sha256(raw).hexdigest()
        ):
            raise DriveMigrationSourceBlocked(
                "legacy Drive source checksum disagrees with downloaded bytes"
            )

    def read_source(self, source: str) -> bytes:
        """Read one path while proving its object identity did not move or change."""
        resolved = self._resolve(source)
        try:
            before = self.drive.get(resolved.file_id, include_trashed=False)
            if before != resolved:
                raise DriveMigrationSourceBlocked(
                    "legacy Drive source changed between path resolution and read"
                )
            raw = self.drive.download(before.file_id)
            after = self.drive.get(before.file_id, include_trashed=False)
        except DriveMigrationSourceBlocked:
            raise
        except ProtocolError as exc:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source read failed"
            ) from exc

        if before != after:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source changed while bytes were being read"
            )
        self._validate_download(after, raw)
        again = self._resolve(source)
        if again != after:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source path changed after bytes were read"
            )
        return raw


def _read_exact_source_set(
    reader: DriveMigrationSourceReader,
    source: MigrationSource,
) -> dict[str, bytes]:
    first: dict[str, bytes] = {}
    total = 0
    for entry in source.entries:
        raw = reader.read_source(entry.source)
        if len(raw) > MAX_MIGRATION_FILE_BYTES:
            raise DriveMigrationSourceBlocked(
                "legacy Drive migration source exceeds per-file size limit"
            )
        if (sha256(raw).hexdigest(), len(raw)) != (entry.sha256, entry.size):
            raise DriveMigrationSourceBlocked(
                "live legacy Drive source no longer matches frozen source boundary"
            )
        total += len(raw)
        if total > MAX_MIGRATION_TOTAL_BYTES:
            raise DriveMigrationSourceBlocked(
                "legacy Drive migration source exceeds total size limit"
            )
        first[entry.source] = raw

    for entry in source.entries:
        raw = reader.read_source(entry.source)
        if raw != first[entry.source]:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source changed during whole-set verification"
            )
    return first


def _coerce_source(value: MigrationSource | bytes | str | Path) -> MigrationSource:
    if isinstance(value, MigrationSource):
        return value
    if isinstance(value, bytes):
        return parse_source(value)
    return verify_migration_source(value)


def capture_migration_source_from_drive(
    drive: DriveBackend,
    source_root_id: str,
    selection_manifest: str | Path,
    output_manifest: str | Path,
) -> MigrationSource:
    selection_raw = small_file(Path(selection_manifest), "migration selection manifest")
    candidate, names = parse_selection(selection_raw)
    reader = DriveMigrationSourceReader(drive, source_root_id)

    first: dict[str, bytes] = {}
    total = 0
    for name in names:
        raw = reader.read_source(name)
        if len(raw) > MAX_MIGRATION_FILE_BYTES:
            raise DriveMigrationSourceBlocked(
                "legacy Drive migration source exceeds per-file size limit"
            )
        total += len(raw)
        if total > MAX_MIGRATION_TOTAL_BYTES:
            raise DriveMigrationSourceBlocked(
                "migration source selection exceeds total size limit"
            )
        first[name] = raw

    for name in names:
        if reader.read_source(name) != first[name]:
            raise DriveMigrationSourceBlocked(
                "legacy Drive source changed after capture"
            )

    raw = canonical_json_bytes(
        {
            "schema": "keelaryn.migration-source.v1",
            "candidate_id": candidate,
            "entries": [
                {
                    "source": name,
                    "sha256": sha256(first[name]).hexdigest(),
                    "size": len(first[name]),
                }
                for name in names
            ],
        }
    )
    from .migration_common import atomic_write_new

    atomic_write_new(Path(output_manifest), raw)
    return parse_source(raw)


def verify_migration_source_against_drive(
    drive: DriveBackend,
    source_root_id: str,
    source_manifest: MigrationSource | bytes | str | Path,
) -> MigrationSource:
    source = _coerce_source(source_manifest)
    _read_exact_source_set(DriveMigrationSourceReader(drive, source_root_id), source)
    return source


def _write_private_materialized(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def build_migration_pack_from_drive(
    drive: DriveBackend,
    source_root_id: str,
    source_manifest: str | Path,
    mapping_manifest: str | Path,
    output_dir: str | Path,
    *,
    prepared_root: str | Path | None = None,
) -> MigrationPack:
    """Build a pack from Drive bytes without making a synced checkout authoritative."""
    source = verify_migration_source(source_manifest)
    payloads = _read_exact_source_set(
        DriveMigrationSourceReader(drive, source_root_id),
        source,
    )

    output = Path(output_dir)
    parent = real_directory(output.parent, "migration Drive pack output parent")
    output = parent / output.name
    if output.exists() or output.is_symlink():
        raise DriveMigrationSourceBlocked("migration pack output already exists")
    transient = parent / f".{output.name}.drive-stage-{uuid.uuid4().hex}"

    try:
        with tempfile.TemporaryDirectory(prefix="keelaryn-migration-drive-source-") as tmp:
            materialized = Path(tmp)
            try:
                materialized.chmod(0o700)
            except OSError:
                pass
            for source_name, raw in payloads.items():
                _write_private_materialized(materialized / source_name, raw)

            build_migration_pack(
                materialized,
                source_manifest,
                mapping_manifest,
                transient,
                prepared_root=prepared_root,
            )

        # Fresh authority validation occurs immediately before the durable pack
        # publication. The transient pack is removed if Drive drift is observed.
        verify_migration_source_against_drive(drive, source_root_id, source)
        verify_migration_pack(transient)
        if output.exists() or output.is_symlink():
            raise DriveMigrationSourceBlocked(
                "migration pack output appeared before publication"
            )
        transient.rename(output)
    except Exception:
        if transient.exists():
            shutil.rmtree(transient, ignore_errors=True)
        raise

    return verify_migration_pack(output)


__all__ = [
    "DriveMigrationSourceBlocked",
    "DriveMigrationSourceReader",
    "capture_migration_source_from_drive",
    "verify_migration_source_against_drive",
    "build_migration_pack_from_drive",
]
