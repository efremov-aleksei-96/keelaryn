from __future__ import annotations

import re
from typing import Any

from .protocol import ID_RE, ProtocolError, SHA_RE, validate_file_state

DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,256}$")
OWNER_KINDS = {"PROJECT", "RECONCILIATION"}


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise ProtocolError(f"{label}: keys mismatch missing={sorted(keys-set(value))} extra={sorted(set(value)-keys)}")


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ProtocolError(f"{label}: invalid identifier")
    return value


def _drive_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DRIVE_ID_RE.fullmatch(value):
        raise ProtocolError(f"{label}: invalid Drive object id")
    return value


def _present(value: Any, label: str) -> dict[str, Any]:
    state = validate_file_state(value, label)
    if state["state"] != "PRESENT":
        raise ProtocolError(f"{label}: must be PRESENT")
    return state


def _object_state(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{label}: must be object")
    _exact(value, {"file_id", "fingerprint"}, label)
    _drive_id(value["file_id"], f"{label}.file_id")
    _present(value["fingerprint"], f"{label}.fingerprint")
    return value


def _owner_kind(value: Any, label: str) -> str:
    if value not in OWNER_KINDS:
        raise ProtocolError(f"{label}: invalid owner kind")
    return value


def validate_work_state_update_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("WORK_STATE_PLAN: must be object")
    keys = {
        "schema", "state", "owner_kind", "owner_id", "owner_folder_id", "update_id",
        "update_folder_id", "plan_file_id", "old", "new", "done_marker_id",
    }
    _exact(value, keys, "WORK_STATE_PLAN")
    if value["schema"] != "keelaryn.work-state-update-plan.v1" or value["state"] != "PREPARED":
        raise ProtocolError("WORK_STATE_PLAN: invalid schema/state")
    _owner_kind(value["owner_kind"], "WORK_STATE_PLAN.owner_kind")
    _id(value["owner_id"], "WORK_STATE_PLAN.owner_id")
    _id(value["update_id"], "WORK_STATE_PLAN.update_id")
    ids = [
        _drive_id(value["owner_folder_id"], "WORK_STATE_PLAN.owner_folder_id"),
        _drive_id(value["update_folder_id"], "WORK_STATE_PLAN.update_folder_id"),
        _drive_id(value["plan_file_id"], "WORK_STATE_PLAN.plan_file_id"),
        _drive_id(value["done_marker_id"], "WORK_STATE_PLAN.done_marker_id"),
    ]
    old = _object_state(value["old"], "WORK_STATE_PLAN.old")
    new = _object_state(value["new"], "WORK_STATE_PLAN.new")
    ids.extend([old["file_id"], new["file_id"]])
    if len(set(ids)) != len(ids):
        raise ProtocolError("WORK_STATE_PLAN: Drive identities must be distinct")
    if old["fingerprint"] == new["fingerprint"]:
        raise ProtocolError("WORK_STATE_PLAN: no-op STATE update forbidden")
    return value


def validate_work_state_update(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("WORK_STATE_DONE: must be object")
    keys = {
        "schema", "state", "owner_kind", "owner_id", "update_id", "plan_file_id",
        "plan_sha256", "plan_size", "old", "new",
    }
    _exact(value, keys, "WORK_STATE_DONE")
    if value["schema"] != "keelaryn.work-state-update.v1" or value["state"] != "APPLIED":
        raise ProtocolError("WORK_STATE_DONE: invalid schema/state")
    _owner_kind(value["owner_kind"], "WORK_STATE_DONE.owner_kind")
    _id(value["owner_id"], "WORK_STATE_DONE.owner_id")
    _id(value["update_id"], "WORK_STATE_DONE.update_id")
    _drive_id(value["plan_file_id"], "WORK_STATE_DONE.plan_file_id")
    if not isinstance(value["plan_sha256"], str) or not SHA_RE.fullmatch(value["plan_sha256"]):
        raise ProtocolError("WORK_STATE_DONE.plan_sha256: invalid sha256")
    if not isinstance(value["plan_size"], int) or isinstance(value["plan_size"], bool) or value["plan_size"] < 0:
        raise ProtocolError("WORK_STATE_DONE.plan_size: invalid size")
    old = _object_state(value["old"], "WORK_STATE_DONE.old")
    new = _object_state(value["new"], "WORK_STATE_DONE.new")
    if old["file_id"] == new["file_id"] or old["fingerprint"] == new["fingerprint"]:
        raise ProtocolError("WORK_STATE_DONE: old/new identities must differ")
    return value


__all__ = ["OWNER_KINDS", "validate_work_state_update_plan", "validate_work_state_update"]
