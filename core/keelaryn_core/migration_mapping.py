from __future__ import annotations

from pathlib import Path

from .migration_common import (
    CLASSIFICATIONS,
    MAX_MIGRATION_FILES,
    CanonicalOutput,
    MigrationMapping,
    MigrationPackBlocked,
    ProjectStateOutput,
    RootIndexOutput,
    digest_hex,
    identifier,
    keys_exact,
    relative_path,
    small_file,
)
from .migration_source import verify_migration_source
from .protocol import ProtocolError, strict_json_bytes


def _preservation_destination(
    classification: str,
    destination_value,
    *,
    candidate_id: str,
    label: str,
) -> str:
    destination = relative_path(destination_value, f"{label}.destination")
    parts = destination.split("/")
    if classification == "PROJECT_WORK_IMPORT":
        if len(parts) < 5 or parts[0:2] != ["work", "projects"] or parts[3] != "migration-import":
            raise MigrationPackBlocked(
                f"{label}.destination: PROJECT_WORK_IMPORT must be under "
                "work/projects/<project_id>/migration-import/"
            )
        identifier(parts[2], f"{label}.destination project_id")
    elif classification == "ARCHIVE_ONLY":
        if len(parts) < 4 or parts[0:2] != ["archive", "migration"] or parts[2] != candidate_id:
            raise MigrationPackBlocked(
                f"{label}.destination: ARCHIVE_ONLY must be under "
                f"archive/migration/{candidate_id}/"
            )
    else:
        raise MigrationPackBlocked(f"{label}: destination is not allowed for classification")
    return destination


def parse_mapping(raw: bytes, source) -> MigrationMapping:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_MAPPING")
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationPackBlocked("MIGRATION_MAPPING: must be object")
    required_keys = {
        "schema",
        "candidate_id",
        "source_manifest_sha256",
        "source_actions",
        "canonical_outputs",
        "root_index",
    }
    allowed_keys = required_keys | {"project_initial_states"}
    if not required_keys.issubset(value) or not set(value).issubset(allowed_keys):
        raise MigrationPackBlocked(
            f"MIGRATION_MAPPING: keys mismatch missing={sorted(required_keys-set(value))} "
            f"extra={sorted(set(value)-allowed_keys)}"
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
    preservation_destinations: dict[str, str] = {}
    for index, item in enumerate(raw_actions):
        label = f"MIGRATION_MAPPING.source_actions[{index}]"
        if not isinstance(item, dict):
            raise MigrationPackBlocked(f"{label}: must be object")
        if set(item) not in ({"source", "classification"}, {"source", "classification", "destination"}):
            raise MigrationPackBlocked(f"{label}: invalid keys")
        name = relative_path(item["source"], f"{label}.source")
        classification = item["classification"]
        if name not in source_set:
            raise MigrationPackBlocked(f"{label}: source not in frozen manifest")
        if not isinstance(classification, str) or classification not in CLASSIFICATIONS:
            raise MigrationPackBlocked(f"{label}: invalid classification")
        if name in actions:
            raise MigrationPackBlocked("MIGRATION_MAPPING: duplicate source action")
        has_destination = "destination" in item
        if classification in {"PROJECT_WORK_IMPORT", "ARCHIVE_ONLY"}:
            if not has_destination:
                raise MigrationPackBlocked(f"{label}: preservation classification requires destination")
            preservation_destinations[name] = _preservation_destination(
                classification,
                item["destination"],
                candidate_id=candidate,
                label=label,
            )
        elif has_destination:
            raise MigrationPackBlocked(f"{label}: destination only allowed for preservation classification")
        actions[name] = classification
    if set(actions) != source_set:
        raise MigrationPackBlocked("MIGRATION_MAPPING: source action coverage mismatch")
    if len(set(preservation_destinations.values())) != len(preservation_destinations):
        raise MigrationPackBlocked("MIGRATION_MAPPING: duplicate preservation destination")

    required_project_ids = {
        destination.split("/")[2]
        for source_name, destination in preservation_destinations.items()
        if actions[source_name] == "PROJECT_WORK_IMPORT"
    }
    raw_project_states = value.get("project_initial_states", [])
    if not isinstance(raw_project_states, list) or len(raw_project_states) > MAX_MIGRATION_FILES:
        raise MigrationPackBlocked("MIGRATION_MAPPING.project_initial_states: invalid count")
    project_states: list[ProjectStateOutput] = []
    project_ids: set[str] = set()
    prepared_paths: set[str] = set()
    for index, item in enumerate(raw_project_states):
        label = f"MIGRATION_MAPPING.project_initial_states[{index}]"
        if not isinstance(item, dict):
            raise MigrationPackBlocked(f"{label}: must be object")
        keys_exact(item, {"project_id", "prepared_path"}, label)
        project_id = identifier(item["project_id"], f"{label}.project_id")
        prepared_path = relative_path(item["prepared_path"], f"{label}.prepared_path")
        if project_id in project_ids:
            raise MigrationPackBlocked("MIGRATION_MAPPING: duplicate project initial state")
        if prepared_path in prepared_paths:
            raise MigrationPackBlocked("MIGRATION_MAPPING: duplicate project state prepared_path")
        project_ids.add(project_id)
        prepared_paths.add(prepared_path)
        project_states.append(ProjectStateOutput(project_id, prepared_path))
    if project_ids != required_project_ids:
        raise MigrationPackBlocked(
            "MIGRATION_MAPPING: project initial state coverage must exactly match PROJECT_WORK_IMPORT projects"
        )

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
        tuple(sorted(preservation_destinations.items())),
        tuple(sorted(project_states, key=lambda item: item.project_id)),
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
