from __future__ import annotations

import shutil
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any

from .migration_common import (
    MAX_MIGRATION_FILES,
    MAX_MIGRATION_FILE_BYTES,
    MAX_MIGRATION_TOTAL_BYTES,
    MIGRATION_MAPPING_NAME,
    MIGRATION_PACK_NAME,
    MIGRATION_PACK_SCHEMA,
    MIGRATION_SOURCE_NAME,
    PRESERVATION_CLASSIFICATIONS,
    MigrationMapping,
    MigrationPack,
    MigrationPackBlocked,
    PackEntry,
    PreservedEntry,
    bounded_int,
    digest_hex,
    keys_exact,
    real_directory,
    relative_path,
    small_file,
    source_file,
    write_new,
)
from .migration_mapping import parse_mapping, verify_migration_mapping
from .migration_source import (
    capture_migration_source,
    parse_source,
    verify_migration_source,
)
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


def build_migration_pack(
    source_root: str | Path,
    source_manifest: str | Path,
    mapping_manifest: str | Path,
    output_dir: str | Path,
    *,
    prepared_root: str | Path | None = None,
) -> MigrationPack:
    root = real_directory(Path(source_root), "migration source root")
    source_raw = small_file(Path(source_manifest), "migration source manifest")
    source = parse_source(source_raw)
    mapping_raw = small_file(Path(mapping_manifest), "migration mapping manifest")
    mapping = parse_mapping(mapping_raw, source)

    prepared = None
    if (
        any(item.payload_kind == "PREPARED" for item in mapping.canonical_outputs)
        or mapping.root_index
    ):
        if prepared_root is None:
            raise MigrationPackBlocked("prepared_root is required by migration mapping")
        prepared = real_directory(Path(prepared_root), "migration prepared root")

    source_by_name = {item.source: item for item in source.entries}

    for item in source.entries:
        raw = source_file(root, item.source, f"frozen migration source {item.source}")
        if (sha256(raw).hexdigest(), len(raw)) != (item.sha256, item.size):
            raise MigrationPackBlocked(
                f"migration source drift from frozen manifest: {item.source}"
            )

    output = Path(output_dir)
    parent = real_directory(output.parent, "migration pack output parent")
    output = parent / output.name
    if output.exists() or output.is_symlink():
        raise MigrationPackBlocked("migration pack output already exists")
    staging = parent / f".{output.name}.tmp-{uuid.uuid4().hex}"

    try:
        staging.mkdir(mode=0o700)
        authority = staging / "authority"
        canonical = staging / "canonical"
        authority.mkdir(mode=0o700)
        canonical.mkdir(mode=0o700)
        write_new(authority / MIGRATION_SOURCE_NAME, source_raw)
        write_new(authority / MIGRATION_MAPPING_NAME, mapping_raw)

        packed_outputs: list[dict[str, Any]] = []
        canonical_total = 0
        for index, item in enumerate(
            sorted(mapping.canonical_outputs, key=lambda value: value.target),
            start=1,
        ):
            operation_id = f"canonical-{index:05d}"
            payload = f"canonical/{operation_id}.bin"
            if item.payload_kind == "SOURCE":
                source_entry = source_by_name[item.payload_value]
                raw = source_file(
                    root,
                    source_entry.source,
                    f"migration source payload {source_entry.source}",
                )
                if (sha256(raw).hexdigest(), len(raw)) != (
                    source_entry.sha256,
                    source_entry.size,
                ):
                    raise MigrationPackBlocked(
                        f"migration source drift during copy: {source_entry.source}"
                    )
            else:
                assert prepared is not None
                raw = source_file(
                    prepared,
                    item.payload_value,
                    f"migration prepared payload {item.payload_value}",
                )
            canonical_total += len(raw)
            if canonical_total > MAX_MIGRATION_TOTAL_BYTES:
                raise MigrationPackBlocked(
                    "migration canonical payload exceeds total size limit"
                )
            write_new(canonical / f"{operation_id}.bin", raw)
            packed_outputs.append(
                {
                    "operation_id": operation_id,
                    "target": item.target,
                    "semantic_sources": list(item.semantic_sources),
                    "payload": payload,
                    "sha256": sha256(raw).hexdigest(),
                    "size": len(raw),
                }
            )

        preserved_actions = sorted(
            (source_name, classification)
            for source_name, classification in mapping.actions
            if classification in PRESERVATION_CLASSIFICATIONS
        )
        packed_preserved: list[dict[str, Any]] = []
        preserved_total = 0
        if preserved_actions:
            preserved = staging / "preserved"
            preserved.mkdir(mode=0o700)
            for index, (source_name, classification) in enumerate(
                preserved_actions,
                start=1,
            ):
                operation_id = f"preserved-{index:05d}"
                payload = f"preserved/{operation_id}.bin"
                source_entry = source_by_name[source_name]
                raw = source_file(
                    root,
                    source_entry.source,
                    f"migration preserved payload {source_entry.source}",
                )
                if (sha256(raw).hexdigest(), len(raw)) != (
                    source_entry.sha256,
                    source_entry.size,
                ):
                    raise MigrationPackBlocked(
                        f"migration source drift during preservation copy: {source_entry.source}"
                    )
                preserved_total += len(raw)
                if preserved_total > MAX_MIGRATION_TOTAL_BYTES:
                    raise MigrationPackBlocked(
                        "migration preserved payload exceeds total size limit"
                    )
                write_new(preserved / f"{operation_id}.bin", raw)
                packed_preserved.append(
                    {
                        "operation_id": operation_id,
                        "source": source_name,
                        "classification": classification,
                        "payload": payload,
                        "sha256": sha256(raw).hexdigest(),
                        "size": len(raw),
                    }
                )

        packed_index = None
        if mapping.root_index:
            assert prepared is not None
            root_payload = staging / "root"
            root_payload.mkdir(mode=0o700)
            raw = source_file(
                prepared,
                mapping.root_index.prepared_path,
                "migration prepared root INDEX",
            )
            write_new(root_payload / "INDEX.md", raw)
            packed_index = {
                "semantic_sources": list(mapping.root_index.semantic_sources),
                "payload": "root/INDEX.md",
                "sha256": sha256(raw).hexdigest(),
                "size": len(raw),
            }

        for source_entry in source.entries:
            raw = source_file(
                root,
                source_entry.source,
                f"migration source final recheck {source_entry.source}",
            )
            if (sha256(raw).hexdigest(), len(raw)) != (
                source_entry.sha256,
                source_entry.size,
            ):
                raise MigrationPackBlocked(
                    f"migration source drift during pack build: {source_entry.source}"
                )

        pack_raw = canonical_json_bytes(
            {
                "schema": MIGRATION_PACK_SCHEMA,
                "candidate_id": source.candidate_id,
                "source_manifest": {
                    "path": f"authority/{MIGRATION_SOURCE_NAME}",
                    "sha256": source.digest,
                    "size": len(source_raw),
                },
                "mapping_manifest": {
                    "path": f"authority/{MIGRATION_MAPPING_NAME}",
                    "sha256": mapping.digest,
                    "size": len(mapping_raw),
                },
                "canonical_outputs": packed_outputs,
                "preserved_outputs": packed_preserved,
                "root_index": packed_index,
                "source_file_count": len(source.entries),
                "source_total_bytes": source.total_bytes,
                "canonical_file_count": len(packed_outputs),
                "canonical_total_bytes": canonical_total,
                "preserved_file_count": len(packed_preserved),
                "preserved_total_bytes": preserved_total,
            }
        )
        write_new(staging / MIGRATION_PACK_NAME, pack_raw)
        staging.rename(output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return verify_migration_pack(output)


def verify_migration_pack(pack_dir: str | Path) -> MigrationPack:
    root = real_directory(Path(pack_dir), "migration pack root")
    names = {item.name for item in root.iterdir()}
    expected = {MIGRATION_PACK_NAME, "authority", "canonical"}
    if "root" in names:
        expected.add("root")
    if "preserved" in names:
        expected.add("preserved")
    if names != expected:
        raise MigrationPackBlocked(
            "migration pack root contains missing or unexpected material"
        )

    authority = real_directory(root / "authority", "migration authority directory")
    if {item.name for item in authority.iterdir()} != {
        MIGRATION_SOURCE_NAME,
        MIGRATION_MAPPING_NAME,
    }:
        raise MigrationPackBlocked(
            "migration authority directory contains missing or unexpected material"
        )

    source_raw = small_file(
        authority / MIGRATION_SOURCE_NAME,
        "packed migration source manifest",
    )
    mapping_raw = small_file(
        authority / MIGRATION_MAPPING_NAME,
        "packed migration mapping manifest",
    )
    source = parse_source(source_raw)
    mapping = parse_mapping(mapping_raw, source)

    pack_raw = small_file(root / MIGRATION_PACK_NAME, "migration pack manifest")
    try:
        value = strict_json_bytes(pack_raw, label="MIGRATION_PACK")
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationPackBlocked("MIGRATION_PACK: must be object")
    keys_exact(
        value,
        {
            "schema",
            "candidate_id",
            "source_manifest",
            "mapping_manifest",
            "canonical_outputs",
            "preserved_outputs",
            "root_index",
            "source_file_count",
            "source_total_bytes",
            "canonical_file_count",
            "canonical_total_bytes",
            "preserved_file_count",
            "preserved_total_bytes",
        },
        "MIGRATION_PACK",
    )
    if (
        value["schema"] != MIGRATION_PACK_SCHEMA
        or value["candidate_id"] != source.candidate_id
    ):
        raise MigrationPackBlocked("MIGRATION_PACK: schema/candidate mismatch")

    for label, descriptor, expected_path, raw in (
        (
            "source_manifest",
            value["source_manifest"],
            f"authority/{MIGRATION_SOURCE_NAME}",
            source_raw,
        ),
        (
            "mapping_manifest",
            value["mapping_manifest"],
            f"authority/{MIGRATION_MAPPING_NAME}",
            mapping_raw,
        ),
    ):
        if not isinstance(descriptor, dict):
            raise MigrationPackBlocked(f"MIGRATION_PACK.{label}: must be object")
        keys_exact(
            descriptor,
            {"path", "sha256", "size"},
            f"MIGRATION_PACK.{label}",
        )
        if descriptor["path"] != expected_path:
            raise MigrationPackBlocked(f"MIGRATION_PACK.{label}: path mismatch")
        if (
            descriptor["sha256"] != sha256(raw).hexdigest()
            or descriptor["size"] != len(raw)
        ):
            raise MigrationPackBlocked(
                f"packed migration {label} authority fingerprint mismatch"
            )

    source_file_count = bounded_int(
        value["source_file_count"],
        "MIGRATION_PACK.source_file_count",
        MAX_MIGRATION_FILES,
        minimum=1,
    )
    source_total_bytes = bounded_int(
        value["source_total_bytes"],
        "MIGRATION_PACK.source_total_bytes",
        MAX_MIGRATION_TOTAL_BYTES,
    )
    if (
        source_file_count != len(source.entries)
        or source_total_bytes != source.total_bytes
    ):
        raise MigrationPackBlocked("MIGRATION_PACK: source summary mismatch")

    raw_outputs = value["canonical_outputs"]
    mapping_outputs = sorted(mapping.canonical_outputs, key=lambda item: item.target)
    if not isinstance(raw_outputs, list) or len(raw_outputs) != len(mapping_outputs):
        raise MigrationPackBlocked("MIGRATION_PACK: canonical output count mismatch")
    canonical_file_count = bounded_int(
        value["canonical_file_count"],
        "MIGRATION_PACK.canonical_file_count",
        MAX_MIGRATION_FILES,
        minimum=1,
    )
    canonical_total_declared = bounded_int(
        value["canonical_total_bytes"],
        "MIGRATION_PACK.canonical_total_bytes",
        MAX_MIGRATION_TOTAL_BYTES,
    )

    canonical = real_directory(root / "canonical", "migration canonical payload directory")
    entries: list[PackEntry] = []
    expected_files: set[str] = set()
    total = 0
    for index, (packed, mapped) in enumerate(zip(raw_outputs, mapping_outputs), start=1):
        label = f"MIGRATION_PACK.canonical_outputs[{index-1}]"
        if not isinstance(packed, dict):
            raise MigrationPackBlocked(f"{label}: must be object")
        keys_exact(
            packed,
            {"operation_id", "target", "semantic_sources", "payload", "sha256", "size"},
            label,
        )
        operation_id = f"canonical-{index:05d}"
        payload = f"canonical/{operation_id}.bin"
        if packed["operation_id"] != operation_id or packed["payload"] != payload:
            raise MigrationPackBlocked(f"{label}: deterministic payload identity mismatch")
        target = relative_path(packed["target"], f"{label}.target")
        packed_semantic = packed["semantic_sources"]
        if not isinstance(packed_semantic, list) or not packed_semantic:
            raise MigrationPackBlocked(f"{label}.semantic_sources: invalid")
        semantic = tuple(
            relative_path(value, f"{label}.semantic_sources[{semantic_index}]")
            for semantic_index, value in enumerate(packed_semantic)
        )
        if len(semantic) != len(set(semantic)):
            raise MigrationPackBlocked(f"{label}.semantic_sources: duplicates")
        if target != mapped.target or semantic != mapped.semantic_sources:
            raise MigrationPackBlocked("MIGRATION_PACK: canonical output authority mismatch")
        digest = digest_hex(packed["sha256"], f"{label}.sha256")
        size = bounded_int(packed["size"], f"{label}.size", MAX_MIGRATION_FILE_BYTES)
        raw = source_file(canonical, f"{operation_id}.bin", f"migration pack payload {operation_id}")
        if sha256(raw).hexdigest() != digest or len(raw) != size:
            raise MigrationPackBlocked(
                f"migration canonical payload fingerprint mismatch: {operation_id}"
            )
        total += size
        expected_files.add(f"{operation_id}.bin")
        entries.append(PackEntry(operation_id, target, semantic, payload, digest, size))

    if {item.name for item in canonical.iterdir()} != expected_files:
        raise MigrationPackBlocked(
            "migration canonical payload directory contains unexpected material"
        )
    if canonical_file_count != len(entries) or canonical_total_declared != total:
        raise MigrationPackBlocked("MIGRATION_PACK: canonical summary mismatch")

    preserved_actions = sorted(
        (source_name, classification)
        for source_name, classification in mapping.actions
        if classification in PRESERVATION_CLASSIFICATIONS
    )
    raw_preserved = value["preserved_outputs"]
    if not isinstance(raw_preserved, list) or len(raw_preserved) != len(preserved_actions):
        raise MigrationPackBlocked("MIGRATION_PACK: preserved output count mismatch")
    preserved_file_count = bounded_int(
        value["preserved_file_count"],
        "MIGRATION_PACK.preserved_file_count",
        MAX_MIGRATION_FILES,
    )
    preserved_total_declared = bounded_int(
        value["preserved_total_bytes"],
        "MIGRATION_PACK.preserved_total_bytes",
        MAX_MIGRATION_TOTAL_BYTES,
    )
    preserved_entries: list[PreservedEntry] = []
    preserved_total = 0
    if preserved_actions:
        preserved = real_directory(root / "preserved", "migration preserved payload directory")
        preserved_expected_files: set[str] = set()
        for index, (packed, expected_action) in enumerate(
            zip(raw_preserved, preserved_actions),
            start=1,
        ):
            label = f"MIGRATION_PACK.preserved_outputs[{index-1}]"
            if not isinstance(packed, dict):
                raise MigrationPackBlocked(f"{label}: must be object")
            keys_exact(
                packed,
                {"operation_id", "source", "classification", "payload", "sha256", "size"},
                label,
            )
            operation_id = f"preserved-{index:05d}"
            payload = f"preserved/{operation_id}.bin"
            if packed["operation_id"] != operation_id or packed["payload"] != payload:
                raise MigrationPackBlocked(f"{label}: deterministic payload identity mismatch")
            source_name = relative_path(packed["source"], f"{label}.source")
            classification = packed["classification"]
            if (
                (source_name, classification) != expected_action
                or classification not in PRESERVATION_CLASSIFICATIONS
            ):
                raise MigrationPackBlocked("MIGRATION_PACK: preserved output authority mismatch")
            digest = digest_hex(packed["sha256"], f"{label}.sha256")
            size = bounded_int(packed["size"], f"{label}.size", MAX_MIGRATION_FILE_BYTES)
            raw = source_file(
                preserved,
                f"{operation_id}.bin",
                f"migration preserved payload {operation_id}",
            )
            source_entry = next(item for item in source.entries if item.source == source_name)
            if (
                sha256(raw).hexdigest() != digest
                or len(raw) != size
                or digest != source_entry.sha256
                or size != source_entry.size
            ):
                raise MigrationPackBlocked(
                    f"migration preserved payload fingerprint mismatch: {operation_id}"
                )
            preserved_total += size
            preserved_expected_files.add(f"{operation_id}.bin")
            preserved_entries.append(
                PreservedEntry(
                    operation_id,
                    source_name,
                    classification,
                    payload,
                    digest,
                    size,
                )
            )
        if {item.name for item in preserved.iterdir()} != preserved_expected_files:
            raise MigrationPackBlocked(
                "migration preserved payload directory contains unexpected material"
            )
    elif (root / "preserved").exists():
        raise MigrationPackBlocked("MIGRATION_PACK: unexpected preserved payload directory")

    if (
        preserved_file_count != len(preserved_entries)
        or preserved_total_declared != preserved_total
    ):
        raise MigrationPackBlocked("MIGRATION_PACK: preserved summary mismatch")

    packed_index = value["root_index"]
    if mapping.root_index is None:
        if packed_index is not None or (root / "root").exists():
            raise MigrationPackBlocked("MIGRATION_PACK: unexpected root INDEX")
        root_index_size = -1
    else:
        if not isinstance(packed_index, dict):
            raise MigrationPackBlocked("MIGRATION_PACK: missing root INDEX")
        keys_exact(
            packed_index,
            {"semantic_sources", "payload", "sha256", "size"},
            "MIGRATION_PACK.root_index",
        )
        packed_semantic = packed_index["semantic_sources"]
        if not isinstance(packed_semantic, list) or not packed_semantic:
            raise MigrationPackBlocked(
                "MIGRATION_PACK.root_index.semantic_sources: invalid"
            )
        semantic = tuple(
            relative_path(
                value,
                f"MIGRATION_PACK.root_index.semantic_sources[{semantic_index}]",
            )
            for semantic_index, value in enumerate(packed_semantic)
        )
        if len(semantic) != len(set(semantic)):
            raise MigrationPackBlocked(
                "MIGRATION_PACK.root_index.semantic_sources: duplicates"
            )
        if (
            semantic != mapping.root_index.semantic_sources
            or packed_index["payload"] != "root/INDEX.md"
        ):
            raise MigrationPackBlocked("MIGRATION_PACK: root INDEX authority mismatch")
        root_digest = digest_hex(packed_index["sha256"], "MIGRATION_PACK.root_index.sha256")
        root_size = bounded_int(
            packed_index["size"],
            "MIGRATION_PACK.root_index.size",
            MAX_MIGRATION_FILE_BYTES,
        )
        root_dir = real_directory(root / "root", "migration root payload directory")
        if {item.name for item in root_dir.iterdir()} != {"INDEX.md"}:
            raise MigrationPackBlocked(
                "migration root payload directory contains unexpected material"
            )
        raw = source_file(root_dir, "INDEX.md", "migration pack root INDEX")
        if root_digest != sha256(raw).hexdigest() or root_size != len(raw):
            raise MigrationPackBlocked("migration root INDEX fingerprint mismatch")
        root_index_size = len(raw)

    return MigrationPack(
        root=root,
        candidate_id=source.candidate_id,
        source_manifest_sha256=source.digest,
        mapping_manifest_sha256=mapping.digest,
        source_file_count=len(source.entries),
        source_total_bytes=source.total_bytes,
        canonical_outputs=tuple(entries),
        preserved_outputs=tuple(preserved_entries),
        root_index_size=root_index_size,
        manifest_raw=pack_raw,
    )


__all__ = [
    "MIGRATION_MAPPING_NAME",
    "MIGRATION_PACK_NAME",
    "MigrationPack",
    "MigrationPackBlocked",
    "build_migration_pack",
    "capture_migration_source",
    "verify_migration_mapping",
    "verify_migration_pack",
    "verify_migration_source",
]
