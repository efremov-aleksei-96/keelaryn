from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class CoreError(Exception):
    """Base error for deterministic protocol failures."""


class ProtocolError(CoreError):
    """Input/state violates the protocol while canonical need not be UNKNOWN."""


class RecoveryBlocked(CoreError):
    """Canonical state cannot be classified safely."""


class InjectedCrash(BaseException):
    """Test-only abrupt process termination. Never catch this inside Core."""


class FaultInjector:
    def __init__(self, point: str | None = None):
        self.point = point
        self.fired = False

    def hit(self, point: str) -> None:
        if self.point == point and not self.fired:
            self.fired = True
            raise InjectedCrash(point)


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
STAGES_SAFE = {"CLAIM", "SNAPSHOT", "ENTER_UNSAFE", "ABORT_PRECOMMIT"}
STAGES_UNSAFE = {"APPLY", "WAIT_POSTCHECK", "ROLLBACK", "FINALIZE_COMMIT", "FINALIZE_ROLLBACK"}
ALL_STAGES = STAGES_SAFE | STAGES_UNSAFE


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ProtocolError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def strict_json_bytes(raw: bytes, *, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"{label}: invalid UTF-8") from exc
    try:
        return json.loads(text, object_pairs_hook=_strict_object)
    except ProtocolError:
        raise
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"{label}: invalid JSON: {exc}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_bytes(data: bytes) -> dict[str, Any]:
    return {"state": "PRESENT", "sha256": sha256_bytes(data), "size": len(data)}


def _assert_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ProtocolError(f"{label}: keys mismatch missing={missing} extra={extra}")


def _assert_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ProtocolError(f"{label}: invalid identifier")
    return value


def _assert_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ProtocolError(f"{label}: invalid sha256")
    return value


def validate_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ProtocolError(f"{label}: invalid relative path length/type")
    if "\x00" in value or "\\" in value or value.startswith("/") or value.endswith("/") or "//" in value:
        raise ProtocolError(f"{label}: unsafe relative path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ProtocolError(f"{label}: unsafe path segment")
    return value


def validate_file_state(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{label}: file state must be object")
    state = value.get("state")
    if state == "ABSENT":
        _assert_exact_keys(value, {"state"}, label)
        return value
    if state == "PRESENT":
        _assert_exact_keys(value, {"state", "sha256", "size"}, label)
        _assert_sha(value["sha256"], f"{label}.sha256")
        if not isinstance(value["size"], int) or isinstance(value["size"], bool) or value["size"] < 0:
            raise ProtocolError(f"{label}.size: invalid size")
        return value
    raise ProtocolError(f"{label}: invalid state")


def validate_change(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("CHANGE: must be object")
    _assert_exact_keys(value, {"schema", "change_id", "base_canonical_epoch", "operations"}, "CHANGE")
    if value["schema"] != "keelaryn.change.v1":
        raise ProtocolError("CHANGE: unsupported schema")
    _assert_id(value["change_id"], "CHANGE.change_id")
    epoch = value["base_canonical_epoch"]
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ProtocolError("CHANGE.base_canonical_epoch: invalid")
    operations = value["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= 1000:
        raise ProtocolError("CHANGE.operations: invalid count")
    ids: set[str] = set()
    targets: set[str] = set()
    for index, op in enumerate(operations):
        label = f"CHANGE.operations[{index}]"
        if not isinstance(op, dict):
            raise ProtocolError(f"{label}: must be object")
        kind = op.get("kind")
        expected = {"operation_id", "kind", "target", "old", "new"}
        if kind in ("ADD", "REPLACE"):
            expected.add("prepared_path")
        _assert_exact_keys(op, expected, label)
        opid = _assert_id(op["operation_id"], f"{label}.operation_id")
        if opid in ids:
            raise ProtocolError("CHANGE: duplicate operation_id")
        ids.add(opid)
        target = validate_relative_path(op["target"], f"{label}.target")
        if target in targets:
            raise ProtocolError("CHANGE: duplicate target")
        targets.add(target)
        old = validate_file_state(op["old"], f"{label}.old")
        new = validate_file_state(op["new"], f"{label}.new")
        if kind == "ADD":
            if old["state"] != "ABSENT" or new["state"] != "PRESENT":
                raise ProtocolError(f"{label}: invalid ADD states")
            validate_relative_path(op["prepared_path"], f"{label}.prepared_path")
        elif kind == "REPLACE":
            if old["state"] != "PRESENT" or new["state"] != "PRESENT":
                raise ProtocolError(f"{label}: invalid REPLACE states")
            if old == new:
                raise ProtocolError(f"{label}: no-op REPLACE forbidden")
            validate_relative_path(op["prepared_path"], f"{label}.prepared_path")
        elif kind == "DELETE":
            if old["state"] != "PRESENT" or new["state"] != "ABSENT":
                raise ProtocolError(f"{label}: invalid DELETE states")
        else:
            raise ProtocolError(f"{label}: invalid kind")
    return value


def validate_ready(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("READY: must be object")
    _assert_exact_keys(value, {"schema", "state", "change_id", "change_sha256"}, "READY")
    if value["schema"] != "keelaryn.ready.v1" or value["state"] != "READY_FOR_COMMIT":
        raise ProtocolError("READY: invalid schema/state")
    _assert_id(value["change_id"], "READY.change_id")
    _assert_sha(value["change_sha256"], "READY.change_sha256")
    return value


def validate_control(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("CONTROL: must be object")
    _assert_exact_keys(value, {"schema", "change_id", "change_sha256", "base_canonical_epoch"}, "CONTROL")
    if value["schema"] != "keelaryn.control.v1":
        raise ProtocolError("CONTROL: invalid schema")
    _assert_id(value["change_id"], "CONTROL.change_id")
    _assert_sha(value["change_sha256"], "CONTROL.change_sha256")
    epoch = value["base_canonical_epoch"]
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ProtocolError("CONTROL.base_canonical_epoch: invalid")
    return value


def validate_postcheck(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("POSTCHECK: must be object")
    _assert_exact_keys(value, {"schema", "change_id", "change_sha256", "base_canonical_epoch", "decision", "reason"}, "POSTCHECK")
    if value["schema"] != "keelaryn.postcheck.v1":
        raise ProtocolError("POSTCHECK: invalid schema")
    _assert_id(value["change_id"], "POSTCHECK.change_id")
    _assert_sha(value["change_sha256"], "POSTCHECK.change_sha256")
    epoch = value["base_canonical_epoch"]
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ProtocolError("POSTCHECK.base_canonical_epoch: invalid")
    if value["decision"] not in ("PASS", "FAIL"):
        raise ProtocolError("POSTCHECK.decision: invalid")
    if not isinstance(value["reason"], str) or not value["reason"] or len(value["reason"]) > 16384:
        raise ProtocolError("POSTCHECK.reason: invalid")
    return value


def validate_history(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("HISTORY: must be object")
    _assert_exact_keys(value, {"schema", "status", "change_id", "change_sha256", "base_canonical_epoch", "entries"}, "HISTORY")
    if value["schema"] != "keelaryn.history.v1" or value["status"] != "VERIFIED":
        raise ProtocolError("HISTORY: invalid schema/status")
    _assert_id(value["change_id"], "HISTORY.change_id")
    _assert_sha(value["change_sha256"], "HISTORY.change_sha256")
    epoch = value["base_canonical_epoch"]
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ProtocolError("HISTORY.base_canonical_epoch: invalid")
    entries = value["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 1000:
        raise ProtocolError("HISTORY.entries: invalid")
    ids: set[str] = set()
    targets: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"HISTORY.entries[{index}]"
        if not isinstance(entry, dict):
            raise ProtocolError(f"{label}: must be object")
        _assert_exact_keys(entry, {"operation_id", "kind", "target", "old", "new", "snapshot_path"}, label)
        opid = _assert_id(entry["operation_id"], f"{label}.operation_id")
        target = validate_relative_path(entry["target"], f"{label}.target")
        if opid in ids or target in targets:
            raise ProtocolError("HISTORY: duplicate operation/target")
        ids.add(opid)
        targets.add(target)
        old = validate_file_state(entry["old"], f"{label}.old")
        new = validate_file_state(entry["new"], f"{label}.new")
        kind = entry["kind"]
        if kind == "ADD":
            if old["state"] != "ABSENT" or new["state"] != "PRESENT" or entry["snapshot_path"] is not None:
                raise ProtocolError(f"{label}: invalid ADD history")
        elif kind == "REPLACE":
            if old["state"] != "PRESENT" or new["state"] != "PRESENT":
                raise ProtocolError(f"{label}: invalid REPLACE history")
            validate_relative_path(entry["snapshot_path"], f"{label}.snapshot_path")
        elif kind == "DELETE":
            if old["state"] != "PRESENT" or new["state"] != "ABSENT":
                raise ProtocolError(f"{label}: invalid DELETE history")
            validate_relative_path(entry["snapshot_path"], f"{label}.snapshot_path")
        else:
            raise ProtocolError(f"{label}: invalid kind")
    return value


def validate_master(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError("MASTER: must be object")
    _assert_exact_keys(value, {"schema", "state", "canonical_read_status", "canonical_epoch", "active_change", "current_stage", "last_completed_change"}, "MASTER")
    if value["schema"] != "keelaryn.master.v1":
        raise ProtocolError("MASTER: invalid schema")
    epoch = value["canonical_epoch"]
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ProtocolError("MASTER.canonical_epoch: invalid")
    state = value["state"]
    read = value["canonical_read_status"]
    active = value["active_change"]
    stage = value["current_stage"]
    if state == "READY":
        if read != "SAFE" or active is not None or stage is not None:
            raise ProtocolError("MASTER: READY must be clean SAFE")
    elif state == "ACTIVE":
        if not isinstance(active, dict):
            raise ProtocolError("MASTER: ACTIVE requires active_change")
        _assert_exact_keys(active, {"change_id", "change_sha256", "base_canonical_epoch"}, "MASTER.active_change")
        _assert_id(active["change_id"], "MASTER.active_change.change_id")
        _assert_sha(active["change_sha256"], "MASTER.active_change.change_sha256")
        base = active["base_canonical_epoch"]
        if not isinstance(base, int) or isinstance(base, bool) or base < 0 or base != epoch:
            raise ProtocolError("MASTER: active base epoch mismatch")
        if stage not in ALL_STAGES:
            raise ProtocolError("MASTER: invalid ACTIVE stage")
        expected_read = "SAFE" if stage in STAGES_SAFE else "UNSAFE"
        if read != expected_read:
            raise ProtocolError("MASTER: read status/stage mismatch")
    elif state == "RECOVERY_BLOCKED":
        if read != "UNSAFE" or stage != "RECOVERY_BLOCKED" or not isinstance(active, dict):
            raise ProtocolError("MASTER: invalid RECOVERY_BLOCKED")
        _assert_exact_keys(active, {"change_id", "change_sha256", "base_canonical_epoch"}, "MASTER.active_change")
        _assert_id(active["change_id"], "MASTER.active_change.change_id")
        _assert_sha(active["change_sha256"], "MASTER.active_change.change_sha256")
        if active["base_canonical_epoch"] != epoch:
            raise ProtocolError("MASTER: blocked base epoch mismatch")
    else:
        raise ProtocolError("MASTER: invalid state")
    completed = value["last_completed_change"]
    if completed is not None:
        if not isinstance(completed, dict):
            raise ProtocolError("MASTER.last_completed_change: invalid")
        _assert_exact_keys(completed, {"change_id", "change_sha256", "outcome", "completed_epoch"}, "MASTER.last_completed_change")
        _assert_id(completed["change_id"], "MASTER.last_completed_change.change_id")
        _assert_sha(completed["change_sha256"], "MASTER.last_completed_change.change_sha256")
        if completed["outcome"] not in ("COMMITTED", "ROLLED_BACK"):
            raise ProtocolError("MASTER.last_completed_change.outcome: invalid")
        ce = completed["completed_epoch"]
        if not isinstance(ce, int) or isinstance(ce, bool) or ce < 1 or ce > epoch:
            raise ProtocolError("MASTER.last_completed_change.completed_epoch: invalid")
    return value
