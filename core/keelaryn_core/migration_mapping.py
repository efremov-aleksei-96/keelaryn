from __future__ import annotations

from pathlib import Path

from .migration_common import (
    CLASSIFICATIONS,
    MAX_MIGRATION_FILES,
    CanonicalOutput,
    MigrationMapping,
    MigrationPackBlocked,
    RootIndexOutput,
    digest_hex,
    identifier,
    keys_exact,
    relative_path,
    small_file,
)
from .migration_source import verify_migration_source
from .protocol import ProtocolError, strict_json_bytes


def parse_mapping(raw: bytes, source) -> MigrationMapping:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_MAPPING")
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationPackBlocked("MIGRATION_MAPPING: must be object")
    keys_exact(
        value,
        {
            "schema",
            "candidate_id",
            "source_manifest_sha256",
            "source_actions",
            "canonical_outputs",
            "root_index",
        },
        "MIGRATION_MAPPING",
    )
    if value["schema"] != "keelaryn.migration-mapping.v1":
        raise MigrationPackBlocked("MIGRATION_MAPPING: unsupported schema")
    candidate = identifier(value["candidate_id"], "MIGRATION_MAPPING.candidate_id")
    if candidate != source.candidate_id:
        raise MigrationPackBlocked("MIGRATION_MAPPING: candidate mismatch")
    source_digest = digest_hex(
        value["source_manifest_sha256"],
        "MIGRATION_MAPPING.source_manifest_sha256",
    )
    if source_digest != source.digest:
        raise MigrationPackBlocked("MIGRATION_MAPPING: source manifest digest mismatch")

    source_set = {item.source for item in source.entries}
    raw_actions = value["source_actions"]
    if not isinstance(raw_actions, list) or len(raw_actions) != len(source_set):
        raise MigrationPackBlocked("MIGRATION_MAPPING: must classify every source exactly once")
    actions: dict[str, str] = {}
    for index, item in enumerate(raw_actions):
        label = f"MIGRATION_MAPPING.source_actions[{index}]"
        if not isinstance(item, dict):
            raise MigrationPackBlocked(f"{label}: must be object")
        keys_exact(item, {"source", "classification"}, label)
        name = relative_path(item["source"], f"{label}.source")
        classification = item["classification"]
        if name not in source_set:
            raise MigrationPackBlocked(f"{label}: source not in frozen manifest")
        if not isinstance(classification, str) or classification not in CLASSIFICATIONS:
            raise MigrationPackBlocked(f"{label}: invalid classification")
        if name in actions:
            raise MigrationPackBlocked("MIGRATION_MAPPING: duplicate source action")
        actions[name] = classification
    if set(actions) != source_set:
        raise MigrationPackBlocked("MIGRATION_MAPPING: source action coverage mismatch")

    raw_outputs = value["canonical_outputs"]
    if not isinstance(raw_outputs, list) or not 1 <= len(raw_outputs) <= MAX_MIGRATION_FILES:
        raise MigrationPackBlocked("MIGRATION_MAPPING.canonical_outputs: invalid count")

    outputs: list[CanonicalOutput] = []
    targets: set[str] = set()
    canonical_owner: dict[str, str] = {}
    for index, item in enumerate(raw_outputs):
        label = f"MIGRATION_MAPPING.canonical_outputs[{index}]"
        if not isinstance(item, dict):
            raise MigrationPackBlocked(f"{label}: must be object")
        keys_exact(item, {"target", "semantic_sources", "payload"}, label)
        target = relative_path(item["target"], f"{label}.target")
        if target in targets:
            raise MigrationPackBlocked("MIGRATION_MAPPING: duplicate canonical target")
        targets.add(target)

        raw_semantic = item["semantic_sources"]
        if not isinstance(raw_semantic, list) or not raw_semantic:
            raise MigrationPackBlocked(f"{label}.semantic_sources: invalid")
        semantic = tuple(
            relative_path(value, f"{label}.semantic_sources[{source_index}]")
            for source_index, value in enumerate(raw_semantic)
        )
        if len(semantic) != len(set(semantic)):
            raise MigrationPackBlocked(f"{label}.semantic_sources: duplicates")
        for name in semantic:
            if name not in source_set or actions[name] != "CANONICAL_IMPORT":
                raise MigrationPackBlocked(
                    f"{label}: canonical output requires CANONICAL_IMPORT source"
                )
            if name in canonical_owner:
                raise MigrationPackBlocked(
                    "MIGRATION_MAPPING: one source maps to multiple canonical owners"
                )
            canonical_owner[name] = target

        payload = item["payload"]
        if not isinstance(payload, dict):
            raise MigrationPackBlocked(f"{label}.payload: must be object")
        kind = payload.get("kind")
        if kind == "SOURCE":
            keys_exact(payload, {"kind", "source"}, f"{label}.payload")
            payload_value = relative_path(payload["source"], f"{label}.payload.source")
            if semantic != (payload_value,):
                raise MigrationPackBlocked(
                    f"{label}: SOURCE payload must own exactly its source"
                )
        elif kind == "PREPARED":
            keys_exact(payload, {"kind", "prepared_path"}, f"{label}.payload")
            payload_value = relative_path(
                payload["prepared_path"],
                f"{label}.payload.prepared_path",
            )
        else:
            raise MigrationPackBlocked(f"{label}.payload: invalid kind")
        outputs.append(CanonicalOutput(target, semantic, kind, payload_value))

    expected = {
        name for name, classification in actions.items()
        if classification == "CANONICAL_IMPORT"
    }
    if set(canonical_owner) != expected:
        raise MigrationPackBlocked(
            "MIGRATION_MAPPING: every CANONICAL_IMPORT source needs exactly one owner"
        )

    raw_index = value["root_index"]
    if raw_index is None:
        root_index = None
    else:
        if not isinstance(raw_index, dict):
            raise MigrationPackBlocked("MIGRATION_MAPPING.root_index: must be object or null")
        keys_exact(
            raw_index,
            {"semantic_sources", "prepared_path"},
            "MIGRATION_MAPPING.root_index",
        )
        raw_semantic = raw_index["semantic_sources"]
        if not isinstance(raw_semantic, list) or not raw_semantic:
            raise MigrationPackBlocked(
                "MIGRATION_MAPPING.root_index.semantic_sources: invalid"
            )
        semantic = tuple(
            relative_path(value, f"MIGRATION_MAPPING.root_index.semantic_sources[{index}]")
            for index, value in enumerate(raw_semantic)
        )
        if len(semantic) != len(set(semantic)):
            raise MigrationPackBlocked(
                "MIGRATION_MAPPING.root_index.semantic_sources: duplicates"
            )
        for name in semantic:
            if (
                name not in source_set
                or actions[name] in {"DROP_TECHNICAL", "PROJECT_WORK_IMPORT", "ARCHIVE_ONLY"}
            ):
                raise MigrationPackBlocked(
                    "MIGRATION_MAPPING.root_index: invalid semantic source classification"
                )
        root_index = RootIndexOutput(
            semantic,
            relative_path(
                raw_index["prepared_path"],
                "MIGRATION_MAPPING.root_index.prepared_path",
            ),
        )

    routers = {
        name for name, classification in actions.items()
        if classification == "ROUTER_SOURCE"
    }
    indexed = set(root_index.semantic_sources) if root_index else set()
    if not routers.issubset(indexed):
        raise MigrationPackBlocked(
            "MIGRATION_MAPPING: every ROUTER_SOURCE must contribute to root_index"
        )

    return MigrationMapping(
        candidate,
        source_digest,
        tuple(sorted(actions.items())),
        tuple(outputs),
        root_index,
        raw,
    )


def verify_migration_mapping(
    source_manifest: str | Path,
    mapping_manifest: str | Path,
) -> MigrationMapping:
    source = verify_migration_source(source_manifest)
    return parse_mapping(
        small_file(Path(mapping_manifest), "migration mapping manifest"),
        source,
    )
