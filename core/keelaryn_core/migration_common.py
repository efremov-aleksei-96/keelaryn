from __future__ import annotations

import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .pilot_pack import (
    PilotPackBlocked as _PilotPackBlocked,
    _read_regular_file,
    _require_real_directory,
    _resolve_source,
    _write_new,
)
from .protocol import ID_RE, ProtocolError, SHA_RE, validate_relative_path


MIGRATION_SELECTION_SCHEMA = "keelaryn.migration-selection.v1"
MIGRATION_SOURCE_SCHEMA = "keelaryn.migration-source.v1"
MIGRATION_MAPPING_SCHEMA = "keelaryn.migration-mapping.v1"
MIGRATION_PACK_SCHEMA = "keelaryn.migration-pack.v1"

MIGRATION_SOURCE_NAME = "MIGRATION_SOURCE.json"
MIGRATION_MAPPING_NAME = "MIGRATION_MAPPING.json"
MIGRATION_PACK_NAME = "MIGRATION_PACK.json"

CLASSIFICATIONS = frozenset(
    {
        "CANONICAL_IMPORT",
        "ROUTER_SOURCE",
        "PROJECT_WORK_IMPORT",
        "ARCHIVE_ONLY",
        "DROP_TECHNICAL",
    }
)
PRESERVATION_CLASSIFICATIONS = frozenset({"PROJECT_WORK_IMPORT", "ARCHIVE_ONLY"})

MAX_MIGRATION_FILES = 10_000
MAX_MIGRATION_FILE_BYTES = 128 * 1024 * 1024
MAX_MIGRATION_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_MIGRATION_MANIFEST_BYTES = 16 * 1024 * 1024


class MigrationPackBlocked(ProtocolError):
    """Migration source/mapping/pack authority cannot be proven safe."""


@dataclass(frozen=True)
class SourceEntry:
    source: str
    sha256: str
    size: int


@dataclass(frozen=True)
class MigrationSource:
    candidate_id: str
    entries: tuple[SourceEntry, ...]
    raw: bytes

    @property
    def digest(self) -> str:
        return sha256(self.raw).hexdigest()

    @property
    def sha256(self) -> str:
        return self.digest

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.entries)

    def public_summary(self) -> dict[str, Any]:
        return {
            "schema": MIGRATION_SOURCE_SCHEMA,
            "candidate_id": self.candidate_id,
            "source_manifest_sha256": self.digest,
            "file_count": len(self.entries),
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True)
class CanonicalOutput:
    target: str
    semantic_sources: tuple[str, ...]
    payload_kind: str
    payload_value: str


@dataclass(frozen=True)
class ProjectStateOutput:
    project_id: str
    prepared_path: str


@dataclass(frozen=True)
class RootIndexOutput:
    semantic_sources: tuple[str, ...]
    prepared_path: str


@dataclass(frozen=True)
class MigrationMapping:
    candidate_id: str
    source_manifest_sha256: str
    actions: tuple[tuple[str, str], ...]
    preservation_destinations: tuple[tuple[str, str], ...]
    project_initial_states: tuple[ProjectStateOutput, ...]
    canonical_outputs: tuple[CanonicalOutput, ...]
    root_index: RootIndexOutput | None
    raw: bytes

    @property
    def digest(self) -> str:
        return sha256(self.raw).hexdigest()

    @property
    def sha256(self) -> str:
        return self.digest

    def public_summary(self) -> dict[str, Any]:
        counts = {name: 0 for name in sorted(CLASSIFICATIONS)}
        for _, classification in self.actions:
            counts[classification] += 1
        return {
            "schema": MIGRATION_MAPPING_SCHEMA,
            "candidate_id": self.candidate_id,
            "source_manifest_sha256": self.source_manifest_sha256,
            "mapping_manifest_sha256": self.digest,
            "source_count": len(self.actions),
            "canonical_output_count": len(self.canonical_outputs),
            "project_state_count": len(self.project_initial_states),
            "has_root_index": self.root_index is not None,
            "classification_counts": counts,
        }


@dataclass(frozen=True)
class PackEntry:
    operation_id: str
    target: str
    semantic_sources: tuple[str, ...]
    payload: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ProjectStateEntry:
    operation_id: str
    project_id: str
    payload: str
    sha256: str
    size: int


@dataclass(frozen=True)
class PreservedEntry:
    operation_id: str
    source: str
    classification: str
    payload: str
    sha256: str
    size: int


@dataclass(frozen=True)
class MigrationPack:
    root: Path
    candidate_id: str
    source_manifest_sha256: str
    mapping_manifest_sha256: str
    source_file_count: int
    source_total_bytes: int
    canonical_outputs: tuple[PackEntry, ...]
    project_initial_states: tuple[ProjectStateEntry, ...]
    preserved_outputs: tuple[PreservedEntry, ...]
    root_index_size: int
    manifest_raw: bytes

    @property
    def digest(self) -> str:
        return sha256(self.manifest_raw).hexdigest()

    @property
    def pack_sha256(self) -> str:
        return self.digest

    @property
    def canonical_total_bytes(self) -> int:
        return sum(item.size for item in self.canonical_outputs)

    @property
    def project_state_total_bytes(self) -> int:
        return sum(item.size for item in self.project_initial_states)

    @property
    def preserved_total_bytes(self) -> int:
        return sum(item.size for item in self.preserved_outputs)

    def public_summary(self) -> dict[str, Any]:
        preservation_counts = {name: 0 for name in sorted(PRESERVATION_CLASSIFICATIONS)}
        for item in self.preserved_outputs:
            preservation_counts[item.classification] += 1
        return {
            "schema": MIGRATION_PACK_SCHEMA,
            "candidate_id": self.candidate_id,
            "pack_sha256": self.digest,
            "source_manifest_sha256": self.source_manifest_sha256,
            "mapping_manifest_sha256": self.mapping_manifest_sha256,
            "source_file_count": self.source_file_count,
            "source_total_bytes": self.source_total_bytes,
            "canonical_file_count": len(self.canonical_outputs),
            "canonical_total_bytes": self.canonical_total_bytes,
            "project_state_count": len(self.project_initial_states),
            "project_state_total_bytes": self.project_state_total_bytes,
            "preserved_file_count": len(self.preserved_outputs),
            "preserved_total_bytes": self.preserved_total_bytes,
            "preservation_counts": preservation_counts,
            "has_root_index": self.root_index_size >= 0,
            "root_index_bytes": max(self.root_index_size, 0),
        }


def keys_exact(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise MigrationPackBlocked(
            f"{label}: keys mismatch missing={sorted(expected-set(value))} "
            f"extra={sorted(set(value)-expected)}"
        )


def identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise MigrationPackBlocked(f"{label}: invalid identifier")
    return value


def relative_path(value: Any, label: str) -> str:
    try:
        return validate_relative_path(value, label)
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc


def digest_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise MigrationPackBlocked(f"{label}: invalid SHA-256")
    return value


def bounded_int(value: Any, label: str, maximum: int, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise MigrationPackBlocked(f"{label}: invalid integer")
    return value


def real_directory(path: Path, label: str) -> Path:
    try:
        return _require_real_directory(path, label)
    except _PilotPackBlocked as exc:
        raise MigrationPackBlocked(str(exc)) from exc


def small_file(path: Path, label: str) -> bytes:
    try:
        return _read_regular_file(path, label=label, max_bytes=MAX_MIGRATION_MANIFEST_BYTES)
    except _PilotPackBlocked as exc:
        raise MigrationPackBlocked(str(exc)) from exc


def source_file(root: Path, relative: str, label: str) -> bytes:
    try:
        resolved = _resolve_source(root, relative)
        return _read_regular_file(resolved, label=label, max_bytes=MAX_MIGRATION_FILE_BYTES)
    except _PilotPackBlocked as exc:
        raise MigrationPackBlocked(str(exc)) from exc


def write_new(path: Path, raw: bytes) -> None:
    try:
        _write_new(path, raw)
    except _PilotPackBlocked as exc:
        raise MigrationPackBlocked(str(exc)) from exc


def atomic_write_new(path: Path, raw: bytes) -> None:
    parent = real_directory(path.parent, "migration output parent")
    output = parent / path.name
    if output.exists() or output.is_symlink():
        raise MigrationPackBlocked(f"migration output already exists: {output.name}")
    staging = parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    try:
        write_new(staging, raw)
        staging.rename(output)
    except Exception:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass
        raise
