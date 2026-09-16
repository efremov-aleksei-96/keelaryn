from __future__ import annotations

import re
from typing import Any

from .protocol import (
    ID_RE,
    ProtocolError,
    SHA_RE,
    validate_file_state,
    validate_relative_path,
)


DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,256}$")


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ProtocolError(f"{label}: keys mismatch missing={missing} extra={extra}")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ProtocolError(f"{label}: invalid identifier")
    return value


def _drive_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DRIVE_ID_RE.fullmatch(value):
        raise ProtocolError(f"{label}: invalid Drive object id")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ProtocolError(f"{label}: invalid sha256")
    return value


def _epoch(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProtocolError(f"{label}: invalid epoch")
    return value


def _size(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProtocolError(f"{label}: invalid size")
    return value


def _present(value: Any, label: str) -> dict[str, Any]:
    state = validate_file_state(value, label)
    if state["state"] != "PRESENT":
        raise ProtocolError(f"{label}: must be PRESENT")
    return state


def _source_identity(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{label}: must be object")
    _exact_keys(
        value,
        {"folder_id", "result_markdown_id", "result_marker_id", "result_markdown", "result_marker"},
        label,
    )
    _drive_id(value["folder_id"], f"{label}.folder_id")
    _drive_id(value["result_markdown_id"], f"{label}.result_markdown_id")
    _drive_id(value["result_marker_id"], f"{label}.result_marker_id")
    _present(value["result_markdown"], f"{label}.result_markdown")
    _present(value["result_marker"], f"{label}.result_marker")
    if value["result_markdown_id"] == value["result_marker_id"]:
        raise ProtocolError(f"{label}: RESULT.md and RESULT.json IDs must differ")
    return value


def _claimed_reserved(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{label}: must be object")
    _exact_keys(value, {"folder_id", "result_markdown_id", "result_marker_id", "claim_marker_id"}, label)
    ids = [
        _drive_id(value["folder_id"], f"{label}.folder_id"),
        _drive_id(value["result_markdown_id"], f"{label}.result_markdown_id"),
        _drive_id(value["result_marker_id"], f"{label}.result_marker_id"),
        _drive_id(value["claim_marker_id"], f"{label}.claim_marker_id"),
    ]
    if len(set(ids)) != len(ids):
        raise ProtocolError(f"{label}: reserved Drive IDs must be distinct")
    return value


def _claimed_identity(value: Any, label: str) -> dict[str, Any]:
    return _source_identity(value, label)


def validate_result_marker(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("RESULT: must be object")
    _exact_keys(
        value,
        {
            "schema",
            "state",
            "project_id",
            "result_id",
            "base_canonical_epoch",
            "result_markdown",
            "canonical_inputs",
            "expected_canonical_targets",
        },
        "RESULT",
    )
    if value["schema"] != "keelaryn.result.v1" or value["state"] != "READY_FOR_RECONCILIATION":
        raise ProtocolError("RESULT: invalid schema/state")
    _identifier(value["project_id"], "RESULT.project_id")
    _identifier(value["result_id"], "RESULT.result_id")
    _epoch(value["base_canonical_epoch"], "RESULT.base_canonical_epoch")
    _present(value["result_markdown"], "RESULT.result_markdown")

    canonical_inputs = value["canonical_inputs"]
    if not isinstance(canonical_inputs, list) or len(canonical_inputs) > 1000:
        raise ProtocolError("RESULT.canonical_inputs: invalid count")
    seen_inputs: set[str] = set()
    for index, entry in enumerate(canonical_inputs):
        label = f"RESULT.canonical_inputs[{index}]"
        if not isinstance(entry, dict):
            raise ProtocolError(f"{label}: must be object")
        _exact_keys(entry, {"path", "observed"}, label)
        path = validate_relative_path(entry["path"], f"{label}.path")
        if path in seen_inputs:
            raise ProtocolError("RESULT.canonical_inputs: duplicate path")
        seen_inputs.add(path)
        validate_file_state(entry["observed"], f"{label}.observed")

    targets = value["expected_canonical_targets"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 1000:
        raise ProtocolError("RESULT.expected_canonical_targets: invalid count")
    seen_targets: set[str] = set()
    for index, target in enumerate(targets):
        path = validate_relative_path(target, f"RESULT.expected_canonical_targets[{index}]")
        if path in seen_targets:
            raise ProtocolError("RESULT.expected_canonical_targets: duplicate path")
        seen_targets.add(path)
    return value


def validate_drive_result_claim_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("CLAIM_PLAN: must be object")
    _exact_keys(
        value,
        {"schema", "state", "project_id", "result_id", "base_canonical_epoch", "source", "claimed"},
        "CLAIM_PLAN",
    )
    if value["schema"] != "keelaryn.drive-result-claim-plan.v1" or value["state"] != "PREPARED":
        raise ProtocolError("CLAIM_PLAN: invalid schema/state")
    _identifier(value["project_id"], "CLAIM_PLAN.project_id")
    _identifier(value["result_id"], "CLAIM_PLAN.result_id")
    _epoch(value["base_canonical_epoch"], "CLAIM_PLAN.base_canonical_epoch")
    source = _source_identity(value["source"], "CLAIM_PLAN.source")
    claimed = _claimed_reserved(value["claimed"], "CLAIM_PLAN.claimed")
    all_ids = {
        source["folder_id"],
        source["result_markdown_id"],
        source["result_marker_id"],
        claimed["folder_id"],
        claimed["result_markdown_id"],
        claimed["result_marker_id"],
        claimed["claim_marker_id"],
    }
    if len(all_ids) != 7:
        raise ProtocolError("CLAIM_PLAN: source and claimed Drive identities must be distinct")
    return value


def validate_drive_result_claim(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("CLAIM: must be object")
    _exact_keys(
        value,
        {
            "schema",
            "state",
            "project_id",
            "result_id",
            "base_canonical_epoch",
            "claim_plan_id",
            "claim_plan_sha256",
            "claim_plan_size",
            "source",
            "claimed",
        },
        "CLAIM",
    )
    if value["schema"] != "keelaryn.drive-result-claim.v1" or value["state"] != "CLAIMED":
        raise ProtocolError("CLAIM: invalid schema/state")
    _identifier(value["project_id"], "CLAIM.project_id")
    _identifier(value["result_id"], "CLAIM.result_id")
    _epoch(value["base_canonical_epoch"], "CLAIM.base_canonical_epoch")
    _drive_id(value["claim_plan_id"], "CLAIM.claim_plan_id")
    _sha(value["claim_plan_sha256"], "CLAIM.claim_plan_sha256")
    _size(value["claim_plan_size"], "CLAIM.claim_plan_size")
    source = _source_identity(value["source"], "CLAIM.source")
    claimed = _claimed_identity(value["claimed"], "CLAIM.claimed")
    if source["folder_id"] == claimed["folder_id"]:
        raise ProtocolError("CLAIM: source and claimed folders must differ")
    if source["result_markdown"] != claimed["result_markdown"]:
        raise ProtocolError("CLAIM: claimed RESULT.md fingerprint differs from source")
    if source["result_marker"] != claimed["result_marker"]:
        raise ProtocolError("CLAIM: claimed RESULT.json fingerprint differs from source")
    if source["result_markdown_id"] == claimed["result_markdown_id"]:
        raise ProtocolError("CLAIM: claimed RESULT.md must be an independent Drive object")
    if source["result_marker_id"] == claimed["result_marker_id"]:
        raise ProtocolError("CLAIM: claimed RESULT.json must be an independent Drive object")
    return value


__all__ = [
    "validate_result_marker",
    "validate_drive_result_claim_plan",
    "validate_drive_result_claim",
]
