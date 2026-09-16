from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine_finalize import FinalizeMixin
from .engine_mutate import MutationMixin
from .engine_prepare import PreparationMixin
from .protocol import (
    ProtocolError,
    RecoveryBlocked,
    canonical_json_bytes,
    sha256_bytes,
    validate_change,
    validate_control,
    validate_history,
)
from .storage import Observed, StorageRuntime


class CoreEngine(PreparationMixin, MutationMixin, FinalizeMixin, StorageRuntime):
    """Restartable deterministic Core for the disposable local-filesystem MVP."""

    def run(self, *, max_steps: int = 100) -> str:
        self._require_infra()
        self.last_terminal_outcome = None
        for _ in range(max_steps):
            master = self._load_master()
            if master["state"] == "RECOVERY_BLOCKED":
                raise RecoveryBlocked("Core is RECOVERY_BLOCKED")
            if master["state"] == "READY":
                if self.active_control.exists() or self.active_control.is_symlink():
                    raise ProtocolError("READY with active control residue")
                ready = self._discover_ready()
                if not ready:
                    return self.last_terminal_outcome or "IDLE"
                if len(ready) != 1:
                    raise ProtocolError("multiple READY_FOR_COMMIT changes visible")
                self._activate(master, ready[0])
                continue

            stage = master["current_stage"]
            handler = {
                "CLAIM": self._stage_claim,
                "SNAPSHOT": self._stage_snapshot,
                "ENTER_UNSAFE": self._stage_enter_unsafe,
                "APPLY": self._stage_apply,
                "WAIT_POSTCHECK": self._stage_wait_postcheck,
                "ROLLBACK": self._stage_rollback,
                "FINALIZE_COMMIT": self._stage_finalize_commit,
                "FINALIZE_ROLLBACK": self._stage_finalize_rollback,
                "ABORT_PRECOMMIT": self._stage_abort_precommit,
            }.get(stage)
            if handler is None:
                raise ProtocolError(f"unsupported active stage: {stage}")
            progressed = handler(master)
            if not progressed and stage == "WAIT_POSTCHECK":
                return "WAIT_POSTCHECK"
            if self.last_terminal_outcome is not None:
                return self.last_terminal_outcome
        raise ProtocolError("max_steps exceeded")

    def _activate(self, master: dict[str, Any], ready_path: Path) -> None:
        change, raw, _ = self._preflight(master, ready_path)
        identity = {
            "change_id": change["change_id"],
            "change_sha256": sha256_bytes(raw),
            "base_canonical_epoch": change["base_canonical_epoch"],
        }
        active = json.loads(json.dumps(master))
        active.update(
            state="ACTIVE",
            canonical_read_status="SAFE",
            active_change=identity,
            current_stage="CLAIM",
        )
        self._write_master(active, label="master.activate")

    def _source_change_dir(self, identity: dict[str, Any]) -> Path:
        return self.changes / identity["change_id"]

    def _control_change_path(self) -> Path:
        return self.active_control / "CHANGE.json"

    @staticmethod
    def _control_identity(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "change_id": value["change_id"],
            "change_sha256": value["change_sha256"],
            "base_canonical_epoch": value["base_canonical_epoch"],
        }

    def _load_control_change(self, master: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        identity = self._active_identity(master)
        control_value, _ = self._load_json(self.active_control / "CONTROL.json", "CONTROL")
        control = validate_control(control_value)
        if self._control_identity(control) != identity:
            self._block(master, "MASTER_CONTROL_MISMATCH", None, None, "CONTROL identity differs from MASTER")
        value, raw = self._load_json(self._control_change_path(), "CONTROL CHANGE")
        change = validate_change(value)
        if change["change_id"] != identity["change_id"] or sha256_bytes(raw) != identity["change_sha256"]:
            self._block(master, "MASTER_CONTROL_MISMATCH", None, None, "claimed CHANGE identity differs from MASTER")
        if change["base_canonical_epoch"] != identity["base_canonical_epoch"]:
            self._block(master, "MASTER_CONTROL_MISMATCH", None, None, "claimed CHANGE base epoch differs from MASTER")
        return change, raw

    def _history_dir(self, master: dict[str, Any]) -> Path:
        return self.history_root / self._active_identity(master)["change_id"]

    def _history_manifest(self, master: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        path = self._history_dir(master) / "HISTORY.json"
        value, _ = self._load_json(path, "HISTORY")
        history = validate_history(value)
        identity = self._active_identity(master)
        if (
            history["change_id"] != identity["change_id"]
            or history["change_sha256"] != identity["change_sha256"]
            or history["base_canonical_epoch"] != identity["base_canonical_epoch"]
        ):
            raise ProtocolError("HISTORY identity mismatch")
        return history, path

    def _verify_history_snapshots(self, history: dict[str, Any]) -> None:
        history_dir = self.history_root / history["change_id"]
        for entry in history["entries"]:
            relative = entry["snapshot_path"]
            if relative is None:
                continue
            snapshot = self._safe_existing_file(history_dir, relative, f"history snapshot:{entry['operation_id']}")
            if self._fingerprint_regular(snapshot) != entry["old"]:
                raise ProtocolError(f"history snapshot fingerprint mismatch: {entry['operation_id']}")

    def _unsafe_history(self, master: dict[str, Any]) -> dict[str, Any]:
        try:
            history, _ = self._history_manifest(master)
            self._verify_history_snapshots(history)
            return history
        except RecoveryBlocked:
            raise
        except Exception as exc:
            self._block(master, "HISTORY_INVALID", None, None, f"invalid durable history: {exc}")
            raise AssertionError("unreachable")

    def _unsafe_change(self, master: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        try:
            return self._load_control_change(master)
        except RecoveryBlocked:
            raise
        except Exception as exc:
            self._block(master, "MASTER_CONTROL_MISMATCH", None, None, f"invalid active control/change: {exc}")
            raise AssertionError("unreachable")

    def _classifications(self, history: dict[str, Any]) -> list[tuple[dict[str, Any], str, Observed]]:
        result = []
        for entry in history["entries"]:
            classification, observed = self._classify(entry)
            result.append((entry, classification, observed))
        return result

    def _block(
        self,
        master: dict[str, Any],
        reason: str,
        entry: dict[str, Any] | None,
        observed: Observed | None,
        message: str,
    ) -> None:
        identity = self._active_identity(master)
        if self.active_control.exists() or self.active_control.is_symlink():
            if not self._real_dir(self.active_control):
                raise RecoveryBlocked(message)
        else:
            self.active_control.mkdir()
            self._fsync_dir(self.control)
        record = {
            "schema": "keelaryn.recovery-block.v1",
            "change_id": identity["change_id"],
            "change_sha256": identity["change_sha256"],
            "reason": reason,
            "operation_id": None if entry is None else entry.get("operation_id"),
            "target": None if entry is None else entry.get("target"),
            "observed": None if observed is None else observed.fingerprint,
            "message": message,
        }
        self._atomic_json(self.active_control / "RECOVERY_BLOCK.json", record, label="recovery.block")
        blocked = json.loads(json.dumps(master))
        blocked.update(state="RECOVERY_BLOCKED", canonical_read_status="UNSAFE", current_stage="RECOVERY_BLOCKED")
        self._write_master(blocked, label="master.recovery_blocked")
        raise RecoveryBlocked(message)

    def _ensure_relative_parent(self, base: Path, relative: str) -> None:
        current = base
        for part in relative.split("/")[:-1]:
            candidate = current / part
            if candidate.exists() or candidate.is_symlink():
                if not self._real_dir(candidate):
                    raise ProtocolError(f"unsafe controlled-tree parent: {relative}")
            else:
                candidate.mkdir()
                self._fsync_dir(current)
            current = candidate

    def _verify_claim_tree(self, change: dict[str, Any], raw: bytes, identity: dict[str, Any]) -> None:
        control_value, _ = self._load_json(self.active_control / "CONTROL.json", "CONTROL")
        control = validate_control(control_value)
        if self._control_identity(control) != identity:
            raise ProtocolError("CONTROL identity mismatch")
        if self._read_raw(self._control_change_path(), "CONTROL CHANGE") != raw:
            raise ProtocolError("claimed CHANGE bytes mismatch")
        for op in change["operations"]:
            if op["kind"] in ("ADD", "REPLACE"):
                staged = self._safe_existing_file(self.active_control, op["prepared_path"], f"staged:{op['operation_id']}")
                if self._fingerprint_regular(staged) != op["new"]:
                    raise ProtocolError(f"staged fingerprint mismatch: {op['operation_id']}")

    def _control_json_bytes(self, identity: dict[str, Any]) -> bytes:
        return canonical_json_bytes({"schema": "keelaryn.control.v1", **identity})
