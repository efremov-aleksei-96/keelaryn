from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .migration_common import (
    MAX_MIGRATION_FILE_BYTES,
    MigrationPackBlocked,
    digest_hex,
    identifier,
    keys_exact,
    real_directory,
    relative_path,
    small_file,
    source_file,
)
from .pilot_pack import _is_linklike
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


MIGRATION_SOURCE_INVENTORY_SCHEMA = "keelaryn.migration-source-inventory.v1"
MAX_INVENTORY_FILES = 20_000
MAX_INVENTORY_DIRECTORIES = 100_000
MAX_INVENTORY_FILE_SIZE = (1 << 63) - 1


@dataclass(frozen=True)
class MigrationSourceInventoryEntry:
    source: str
    size: int
    sha256: str | None
    selectable: bool


@dataclass(frozen=True)
class MigrationSourceInventory:
    candidate_id: str
    entries: tuple[MigrationSourceInventoryEntry, ...]
    raw: bytes

    @property
    def digest(self) -> str:
        return sha256(self.raw).hexdigest()

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.entries)

    @property
    def selectable_total_bytes(self) -> int:
        return sum(item.size for item in self.entries if item.selectable)

    def public_summary(self) -> dict[str, Any]:
        selectable = sum(1 for item in self.entries if item.selectable)
        return {
            "schema": MIGRATION_SOURCE_INVENTORY_SCHEMA,
            "candidate_id": self.candidate_id,
            "inventory_sha256": self.digest,
            "file_count": len(self.entries),
            "selectable_file_count": selectable,
            "oversized_file_count": len(self.entries) - selectable,
            "total_bytes": self.total_bytes,
            "selectable_total_bytes": self.selectable_total_bytes,
        }


def _inventory_size(value: Any, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > MAX_INVENTORY_FILE_SIZE
    ):
        raise MigrationPackBlocked(f"{label}: invalid file size")
    return value


def parse_migration_source_inventory(raw: bytes) -> MigrationSourceInventory:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_SOURCE_INVENTORY")
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationPackBlocked("MIGRATION_SOURCE_INVENTORY: must be object")
    keys_exact(
        value,
        {"schema", "candidate_id", "entries"},
        "MIGRATION_SOURCE_INVENTORY",
    )
    if value["schema"] != MIGRATION_SOURCE_INVENTORY_SCHEMA:
        raise MigrationPackBlocked("MIGRATION_SOURCE_INVENTORY: unsupported schema")
    candidate = identifier(
        value["candidate_id"], "MIGRATION_SOURCE_INVENTORY.candidate_id"
    )
    raw_entries = value["entries"]
    if (
        not isinstance(raw_entries, list)
        or not 1 <= len(raw_entries) <= MAX_INVENTORY_FILES
    ):
        raise MigrationPackBlocked(
            "MIGRATION_SOURCE_INVENTORY.entries: invalid count"
        )

    entries: list[MigrationSourceInventoryEntry] = []
    seen: set[str] = set()
    seen_casefold: set[str] = set()
    for index, item in enumerate(raw_entries):
        label = f"MIGRATION_SOURCE_INVENTORY.entries[{index}]"
        if not isinstance(item, dict):
            raise MigrationPackBlocked(f"{label}: must be object")
        keys_exact(item, {"source", "size", "sha256", "selectable"}, label)
        source = relative_path(item["source"], f"{label}.source")
        size = _inventory_size(item["size"], f"{label}.size")
        selectable = item["selectable"]
        if not isinstance(selectable, bool):
            raise MigrationPackBlocked(f"{label}.selectable: must be boolean")

        folded = source.casefold()
        if source in seen or folded in seen_casefold:
            raise MigrationPackBlocked(
                "MIGRATION_SOURCE_INVENTORY: duplicate/case-conflicting source"
            )
        seen.add(source)
        seen_casefold.add(folded)

        expected_selectable = size <= MAX_MIGRATION_FILE_BYTES
        if selectable != expected_selectable:
            raise MigrationPackBlocked(
                f"{label}.selectable: disagrees with migration file-size limit"
            )
        if selectable:
            digest = digest_hex(item["sha256"], f"{label}.sha256")
        else:
            if item["sha256"] is not None:
                raise MigrationPackBlocked(
                    f"{label}.sha256: oversized inventory entry must use null"
                )
            digest = None
        entries.append(
            MigrationSourceInventoryEntry(source, size, digest, selectable)
        )

    if [item.source for item in entries] != sorted(item.source for item in entries):
        raise MigrationPackBlocked(
            "MIGRATION_SOURCE_INVENTORY: entries must be sorted"
        )
    if raw != canonical_json_bytes(value):
        raise MigrationPackBlocked(
            "MIGRATION_SOURCE_INVENTORY: manifest is not canonical JSON bytes"
        )
    return MigrationSourceInventory(candidate, tuple(entries), raw)


def _enumerate_source(root: Path) -> tuple[tuple[str, int], ...]:
    pending = [root]
    directory_count = 0
    files: list[tuple[str, int]] = []
    seen_casefold: set[str] = set()

    while pending:
        directory = pending.pop()
        directory_count += 1
        if directory_count > MAX_INVENTORY_DIRECTORIES:
            raise MigrationPackBlocked(
                "migration source inventory exceeds directory-count limit"
            )
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise MigrationPackBlocked(
                f"migration source inventory cannot enumerate directory: {exc}"
            ) from exc

        child_directories: list[Path] = []
        for path in children:
            try:
                observed = path.lstat()
            except OSError as exc:
                raise MigrationPackBlocked(
                    f"migration source inventory cannot stat entry: {exc}"
                ) from exc
            if stat.S_ISLNK(observed.st_mode) or _is_linklike(path):
                raise MigrationPackBlocked(
                    "migration source inventory traverses a symlink/reparse object"
                )
            if stat.S_ISDIR(observed.st_mode):
                child_directories.append(path)
                continue
            if not stat.S_ISREG(observed.st_mode):
                raise MigrationPackBlocked(
                    "migration source inventory contains a non-regular object"
                )

            try:
                relative = path.relative_to(root).as_posix()
            except ValueError as exc:
                raise MigrationPackBlocked(
                    "migration source inventory entry escapes source root"
                ) from exc
            relative = relative_path(
                relative, "MIGRATION_SOURCE_INVENTORY.observed_source"
            )
            folded = relative.casefold()
            if folded in seen_casefold:
                raise MigrationPackBlocked(
                    "migration source inventory contains case-conflicting paths"
                )
            seen_casefold.add(folded)
            if observed.st_size < 0 or observed.st_size > MAX_INVENTORY_FILE_SIZE:
                raise MigrationPackBlocked(
                    "migration source inventory contains an invalid file size"
                )
            files.append((relative, observed.st_size))
            if len(files) > MAX_INVENTORY_FILES:
                raise MigrationPackBlocked(
                    "migration source inventory exceeds file-count limit"
                )

        # LIFO stack with reverse insertion preserves deterministic traversal,
        # while the returned inventory is sorted again by relative path.
        pending.extend(reversed(child_directories))

    if not files:
        raise MigrationPackBlocked("migration source inventory is empty")
    return tuple(sorted(files))


def _write_private_atomic_new(path: Path, raw: bytes) -> None:
    parent = real_directory(path.parent, "migration source inventory output parent")
    output = parent / path.name
    if output.exists() or output.is_symlink():
        raise MigrationPackBlocked("migration source inventory output already exists")

    staging = parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = None
    try:
        fd = os.open(staging, flags, 0o600)
        try:
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                try:
                    fchmod(fd, 0o600)
                except OSError:
                    if os.name != "nt":
                        raise
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
            fd = None

        try:
            os.link(staging, output)
        except FileExistsError as exc:
            raise MigrationPackBlocked(
                "migration source inventory output raced with an existing file"
            ) from exc
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except OSError as exc:
        raise MigrationPackBlocked(
            f"cannot publish migration source inventory safely: {exc}"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


def inventory_migration_source(
    source_root: str | Path,
    candidate_id: str,
    output_manifest: str | Path,
) -> MigrationSourceInventory:
    root = real_directory(Path(source_root), "migration source inventory root")
    candidate = identifier(candidate_id, "MIGRATION_SOURCE_INVENTORY.candidate_id")

    output = Path(output_manifest)
    output_parent = real_directory(
        output.parent, "migration source inventory output parent"
    )
    try:
        output_parent.relative_to(root)
    except ValueError:
        pass
    else:
        raise MigrationPackBlocked(
            "migration source inventory output must be outside source root"
        )

    first_structure = _enumerate_source(root)
    first_fingerprints: dict[str, tuple[str, int] | None] = {}
    for source, observed_size in first_structure:
        if observed_size > MAX_MIGRATION_FILE_BYTES:
            first_fingerprints[source] = None
            continue
        raw = source_file(root, source, f"migration inventory source {source}")
        fingerprint = (sha256(raw).hexdigest(), len(raw))
        if fingerprint[1] != observed_size:
            raise MigrationPackBlocked(
                f"migration source inventory size changed during observation: {source}"
            )
        first_fingerprints[source] = fingerprint

    second_structure = _enumerate_source(root)
    if second_structure != first_structure:
        raise MigrationPackBlocked(
            "migration source structure changed during inventory"
        )

    for source, observed_size in second_structure:
        first = first_fingerprints[source]
        if first is None:
            # Oversized files can never enter a migration selection. Their exact
            # path and stable size are retained for review, but their bytes are
            # deliberately not loaded into memory merely to build the inventory.
            continue
        raw = source_file(root, source, f"migration inventory source recheck {source}")
        observed = (sha256(raw).hexdigest(), len(raw))
        if observed != first or observed[1] != observed_size:
            raise MigrationPackBlocked(
                f"migration source changed during inventory: {source}"
            )

    entries = []
    for source, size in first_structure:
        fingerprint = first_fingerprints[source]
        entries.append(
            {
                "source": source,
                "size": size,
                "sha256": None if fingerprint is None else fingerprint[0],
                "selectable": fingerprint is not None,
            }
        )
    manifest_raw = canonical_json_bytes(
        {
            "schema": MIGRATION_SOURCE_INVENTORY_SCHEMA,
            "candidate_id": candidate,
            "entries": entries,
        }
    )
    _write_private_atomic_new(output, manifest_raw)
    return parse_migration_source_inventory(manifest_raw)


def verify_migration_source_inventory(
    inventory_manifest: str | Path,
) -> MigrationSourceInventory:
    raw = small_file(Path(inventory_manifest), "migration source inventory")
    return parse_migration_source_inventory(raw)


__all__ = [
    "MIGRATION_SOURCE_INVENTORY_SCHEMA",
    "MigrationSourceInventory",
    "MigrationSourceInventoryEntry",
    "inventory_migration_source",
    "parse_migration_source_inventory",
    "verify_migration_source_inventory",
]
