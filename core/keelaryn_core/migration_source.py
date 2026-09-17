from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from .migration_common import (
    MAX_MIGRATION_FILES,
    MAX_MIGRATION_FILE_BYTES,
    MAX_MIGRATION_TOTAL_BYTES,
    MIGRATION_SELECTION_SCHEMA,
    MIGRATION_SOURCE_SCHEMA,
    MigrationPackBlocked,
    MigrationSource,
    SourceEntry,
    atomic_write_new,
    bounded_int,
    digest_hex,
    identifier,
    keys_exact,
    real_directory,
    relative_path,
    small_file,
    source_file,
)
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


def parse_selection(raw: bytes) -> tuple[str, tuple[str, ...]]:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_SELECTION")
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationPackBlocked("MIGRATION_SELECTION: must be object")
    keys_exact(value, {"schema", "candidate_id", "sources"}, "MIGRATION_SELECTION")
    if value["schema"] != MIGRATION_SELECTION_SCHEMA:
        raise MigrationPackBlocked("MIGRATION_SELECTION: unsupported schema")
    candidate = identifier(value["candidate_id"], "MIGRATION_SELECTION.candidate_id")
    raw_sources = value["sources"]
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= MAX_MIGRATION_FILES:
        raise MigrationPackBlocked("MIGRATION_SELECTION.sources: invalid count")
    sources = tuple(
        relative_path(item, f"MIGRATION_SELECTION.sources[{index}]")
        for index, item in enumerate(raw_sources)
    )
    if len(sources) != len(set(sources)):
        raise MigrationPackBlocked("MIGRATION_SELECTION: duplicate source")
    return candidate, tuple(sorted(sources))


def parse_source(raw: bytes) -> MigrationSource:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_SOURCE")
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationPackBlocked("MIGRATION_SOURCE: must be object")
    keys_exact(value, {"schema", "candidate_id", "entries"}, "MIGRATION_SOURCE")
    if value["schema"] != MIGRATION_SOURCE_SCHEMA:
        raise MigrationPackBlocked("MIGRATION_SOURCE: unsupported schema")
    candidate = identifier(value["candidate_id"], "MIGRATION_SOURCE.candidate_id")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not 1 <= len(raw_entries) <= MAX_MIGRATION_FILES:
        raise MigrationPackBlocked("MIGRATION_SOURCE.entries: invalid count")

    entries: list[SourceEntry] = []
    seen: set[str] = set()
    total = 0
    for index, item in enumerate(raw_entries):
        label = f"MIGRATION_SOURCE.entries[{index}]"
        if not isinstance(item, dict):
            raise MigrationPackBlocked(f"{label}: must be object")
        keys_exact(item, {"source", "sha256", "size"}, label)
        source = relative_path(item["source"], f"{label}.source")
        digest = digest_hex(item["sha256"], f"{label}.sha256")
        size = bounded_int(item["size"], f"{label}.size", MAX_MIGRATION_FILE_BYTES)
        if source in seen:
            raise MigrationPackBlocked("MIGRATION_SOURCE: duplicate source")
        seen.add(source)
        total += size
        if total > MAX_MIGRATION_TOTAL_BYTES:
            raise MigrationPackBlocked("MIGRATION_SOURCE: selected bytes exceed limit")
        entries.append(SourceEntry(source, digest, size))

    if [item.source for item in entries] != sorted(item.source for item in entries):
        raise MigrationPackBlocked("MIGRATION_SOURCE: entries must be sorted")
    return MigrationSource(candidate, tuple(entries), raw)


def capture_migration_source(
    source_root: str | Path,
    selection_manifest: str | Path,
    output_manifest: str | Path,
) -> MigrationSource:
    root = real_directory(Path(source_root), "migration source root")
    selection_raw = small_file(Path(selection_manifest), "migration selection manifest")
    candidate, names = parse_selection(selection_raw)

    fingerprints: dict[str, tuple[str, int]] = {}
    total = 0
    for name in names:
        raw = source_file(root, name, f"migration source {name}")
        fingerprint = (sha256(raw).hexdigest(), len(raw))
        fingerprints[name] = fingerprint
        total += len(raw)
        if total > MAX_MIGRATION_TOTAL_BYTES:
            raise MigrationPackBlocked("migration source selection exceeds total size limit")

    # Required second observation: a capture is invalid if bytes drift after the
    # first fingerprint pass even though each individual read was internally stable.
    for name in names:
        raw = source_file(root, name, f"migration source recheck {name}")
        if (sha256(raw).hexdigest(), len(raw)) != fingerprints[name]:
            raise MigrationPackBlocked(f"migration source changed after capture: {name}")

    manifest_raw = canonical_json_bytes(
        {
            "schema": MIGRATION_SOURCE_SCHEMA,
            "candidate_id": candidate,
            "entries": [
                {"source": name, "sha256": fingerprints[name][0], "size": fingerprints[name][1]}
                for name in names
            ],
        }
    )
    atomic_write_new(Path(output_manifest), manifest_raw)
    return parse_source(manifest_raw)


def verify_migration_source(source_manifest: str | Path) -> MigrationSource:
    return parse_source(small_file(Path(source_manifest), "migration source manifest"))
