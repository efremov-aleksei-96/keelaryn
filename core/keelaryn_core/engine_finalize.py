from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .protocol import ProtocolError, RecoveryBlocked, sha256_bytes, validate_change, validate_history, validate_ready


class FinalizeMixin:
    def _stage_finalize_commit(self, master: dict[str, Any]) -> bool:
        history = self._unsafe_history(master)
        classes = self._classifications(history)
        unknown = next((item for item in classes if item[1] == "UNKNOWN"), None)
        if unknown is not None:
            entry, _, observed = unknown
            self._block(master, "FINAL_STATE_INVALID", entry, observed, "UNKNOWN target during commit finalization")
        if any(classification == "OLD" for _, classification, _ in classes):
            self._write_master(
                self._master_stage(master, "ROLLBACK", read_status="UNSAFE"),
                label="master.finalize_commit_rollback",
            )
            return True
        try:
            self._cleanup_consumed(master)
        except RecoveryBlocked:
            raise
        except Exception as exc:
            self._block(master, "FINAL_STATE_INVALID", None, None, f"commit cleanup conflict: {exc}")
        self._finish_ready(master, "COMMITTED")
        return True

    def _stage_finalize_rollback(self, master: dict[str, Any]) -> bool:
        history = self._unsafe_history(master)
        classes = self._classifications(history)
        unknown = next((item for item in classes if item[1] == "UNKNOWN"), None)
        if unknown is not None:
            entry, _, observed = unknown
            self._block(master, "FINAL_STATE_INVALID", entry, observed, "UNKNOWN target during rollback finalization")
        if any(classification == "NEW" for _, classification, _ in classes):
            self._write_master(
                self._master_stage(master, "ROLLBACK", read_status="UNSAFE"),
                label="master.finalize_rollback_retry",
            )
            return True
        try:
            self._cleanup_consumed(master)
        except RecoveryBlocked:
            raise
        except Exception as exc:
            self._block(master, "FINAL_STATE_INVALID", None, None, f"rollback cleanup conflict: {exc}")
        self._finish_ready(master, "ROLLED_BACK")
        return True

    def _finish_ready(self, master: dict[str, Any], outcome: str) -> None:
        identity = self._active_identity(master)
        completed_epoch = identity["base_canonical_epoch"] + 1
        final = {
            "schema": "keelaryn.master.v1",
            "state": "READY",
            "canonical_read_status": "SAFE",
            "canonical_epoch": completed_epoch,
            "active_change": None,
            "current_stage": None,
            "last_completed_change": {
                "change_id": identity["change_id"],
                "change_sha256": identity["change_sha256"],
                "outcome": outcome,
                "completed_epoch": completed_epoch,
            },
        }
        self._write_master(final, label=f"master.finalize.{outcome.lower()}")
        self.last_terminal_outcome = outcome

    def _expected_change_files(self, change: dict[str, Any], raw: bytes) -> dict[str, bytes | dict[str, Any]]:
        expected: dict[str, bytes | dict[str, Any]] = {"CHANGE.json": raw}
        for op in change["operations"]:
            if op["kind"] in ("ADD", "REPLACE"):
                expected[op["prepared_path"]] = op["new"]
        return expected

    def _assert_no_unknown_files(
        self,
        root: Path,
        expected: dict[str, bytes | dict[str, Any]],
        *,
        allow_ready: bool = False,
    ) -> None:
        if not root.exists() and not root.is_symlink():
            return
        if not self._real_dir(root):
            raise ProtocolError(f"cleanup root unsafe: {root}")
        allowed = set(expected)
        if allow_ready:
            allowed.add("READY.json")
        actual_files: set[str] = set()
        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            base_path = Path(base)
            for name in dirs:
                if (base_path / name).is_symlink():
                    raise ProtocolError(f"unexpected symlink during cleanup: {base_path / name}")
            for name in files:
                path = base_path / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or not self._regular_file(path):
                    raise ProtocolError(f"unsafe cleanup file: {path}")
                actual_files.add(relative)
        extra = actual_files - allowed
        if extra:
            raise ProtocolError(f"unexpected cleanup material: {sorted(extra)}")
        for relative in actual_files:
            if relative == "READY.json":
                continue
            expected_value = expected[relative]
            path = root / relative
            if isinstance(expected_value, bytes):
                if path.read_bytes() != expected_value:
                    raise ProtocolError(f"cleanup exact bytes mismatch: {relative}")
            elif self._fingerprint_regular(path) != expected_value:
                raise ProtocolError(f"cleanup fingerprint mismatch: {relative}")

    def _remove_known_tree(self, root: Path, *, fault_prefix: str) -> None:
        if not root.exists() and not root.is_symlink():
            return
        if not self._real_dir(root):
            raise ProtocolError(f"cleanup root unsafe: {root}")
        for base, dirs, files in os.walk(root, topdown=False, followlinks=False):
            base_path = Path(base)
            for name in files:
                path = base_path / name
                if not self._regular_file(path):
                    raise ProtocolError(f"cleanup file unsafe: {path}")
                path.unlink()
                self._fsync_dir(path.parent)
                self.fault.hit(f"{fault_prefix}.after_file_delete")
            for name in dirs:
                path = base_path / name
                if not self._real_dir(path):
                    raise ProtocolError(f"cleanup directory unsafe: {path}")
                path.rmdir()
                self._fsync_dir(path.parent)
        root.rmdir()
        self._fsync_dir(root.parent)
        self.fault.hit(f"{fault_prefix}.after_root_delete")

    def _load_cleanup_change(self, master: dict[str, Any]) -> tuple[dict[str, Any] | None, bytes | None]:
        identity = self._active_identity(master)
        control_change = self._control_change_path()
        source_change = self._source_change_dir(identity) / "CHANGE.json"
        selected = control_change if self._regular_file(control_change) else source_change if self._regular_file(source_change) else None
        if selected is None:
            return None, None
        value, raw = self._load_json(selected, "cleanup CHANGE")
        change = validate_change(value)
        if change["change_id"] != identity["change_id"] or sha256_bytes(raw) != identity["change_sha256"]:
            raise ProtocolError("cleanup CHANGE identity mismatch")
        if change["base_canonical_epoch"] != identity["base_canonical_epoch"]:
            raise ProtocolError("cleanup CHANGE base epoch mismatch")
        return change, raw

    def _cleanup_consumed(self, master: dict[str, Any]) -> None:
        identity = self._active_identity(master)
        source_dir = self._source_change_dir(identity)
        control_change = self._control_change_path()
        change, raw = self._load_cleanup_change(master)

        if source_dir.exists() or source_dir.is_symlink():
            if change is None or raw is None:
                raise ProtocolError("remaining source change cannot be authenticated")
            expected = self._expected_change_files(change, raw)
            self._assert_no_unknown_files(source_dir, expected, allow_ready=True)
            ready_path = source_dir / "READY.json"
            if ready_path.exists() or ready_path.is_symlink():
                ready_value, _ = self._load_json(ready_path, "cleanup READY")
                ready = validate_ready(ready_value)
                if ready["change_id"] != identity["change_id"] or ready["change_sha256"] != identity["change_sha256"]:
                    raise ProtocolError("cleanup READY identity mismatch")
            self._remove_known_tree(source_dir, fault_prefix="cleanup.change")

        accepted = self.active_control / "POSTCHECK.json"
        source_post = self.postchecks / f"{identity['change_id']}.json"
        if source_post.exists() or source_post.is_symlink():
            if not self._regular_file(source_post):
                raise ProtocolError("cleanup post-check source unsafe")
            if not self._regular_file(accepted) or source_post.read_bytes() != accepted.read_bytes():
                raise ProtocolError("cleanup post-check differs from accepted decision")
            source_post.unlink()
            self._fsync_dir(self.postchecks)
            self.fault.hit("cleanup.postcheck.after_delete")

        if not self.active_control.exists() and not self.active_control.is_symlink():
            return
        if not self._real_dir(self.active_control):
            raise ProtocolError("active control cleanup root unsafe")

        if self._regular_file(control_change):
            if change is None or raw is None:
                raise ProtocolError("control CHANGE exists but is unauthenticated")
            expected = self._expected_change_files(change, raw)
            control_json = self.active_control / "CONTROL.json"
            if control_json.exists() or control_json.is_symlink():
                expected["CONTROL.json"] = self._control_json_bytes(identity)
            if accepted.exists() or accepted.is_symlink():
                expected["POSTCHECK.json"] = accepted.read_bytes()
            if (self.active_control / "RECOVERY_BLOCK.json").exists():
                raise ProtocolError("cannot finalize with RECOVERY_BLOCK residue")
            self._assert_no_unknown_files(self.active_control, expected)

            for base, dirs, files in os.walk(self.active_control, topdown=False, followlinks=False):
                base_path = Path(base)
                for name in files:
                    path = base_path / name
                    if path == control_change:
                        continue
                    if not self._regular_file(path):
                        raise ProtocolError(f"cleanup file unsafe: {path}")
                    path.unlink()
                    self._fsync_dir(path.parent)
                    self.fault.hit("cleanup.control.after_file_delete")
                for name in dirs:
                    path = base_path / name
                    if path.exists():
                        if not self._real_dir(path):
                            raise ProtocolError(f"cleanup directory unsafe: {path}")
                        try:
                            path.rmdir()
                        except OSError:
                            pass
                        else:
                            self._fsync_dir(path.parent)
            if self._regular_file(control_change):
                control_change.unlink()
                self._fsync_dir(self.active_control)
                self.fault.hit("cleanup.control.after_change_delete")

        # Once CHANGE is gone, only empty directories may remain. This is the
        # crash-safe partial-cleanup state authenticated by MASTER + HISTORY.
        for base, dirs, files in os.walk(self.active_control, topdown=False, followlinks=False):
            if files:
                raise ProtocolError(f"unauthenticated control files remain: {files}")
            base_path = Path(base)
            for name in dirs:
                path = base_path / name
                if not self._real_dir(path):
                    raise ProtocolError(f"cleanup directory unsafe: {path}")
                path.rmdir()
                self._fsync_dir(path.parent)
        self.active_control.rmdir()
        self._fsync_dir(self.control)
        self.fault.hit("cleanup.control.after_root_delete")

    def _stage_abort_precommit(self, master: dict[str, Any]) -> bool:
        identity = self._active_identity(master)
        try:
            change, raw = self._load_cleanup_change(master)
            if change is None or raw is None:
                raise ProtocolError("cannot authenticate active change during abort")
            for op in change["operations"]:
                entry = {"target": op["target"], "old": op["old"], "new": op["new"]}
                classification, observed = self._classify(entry)
                if classification != "OLD":
                    self._block(master, "TARGET_UNKNOWN", op, observed, "precommit abort found canonical target not OLD")

            history_dir = self._history_dir(master)
            if history_dir.exists() or history_dir.is_symlink():
                self._assert_partial_history_known(history_dir, change)
                self._remove_known_tree(history_dir, fault_prefix="abort.history")

            if self.active_control.exists() or self.active_control.is_symlink():
                expected = self._expected_change_files(change, raw)
                if (self.active_control / "CONTROL.json").exists():
                    expected["CONTROL.json"] = self._control_json_bytes(identity)
                self._assert_no_unknown_files(self.active_control, expected)
                self._remove_known_tree(self.active_control, fault_prefix="abort.control")
        except RecoveryBlocked:
            raise
        except Exception as exc:
            self._block(master, "FINAL_STATE_INVALID", None, None, f"precommit abort cleanup conflict: {exc}")

        final = json.loads(json.dumps(master))
        final.update(state="READY", canonical_read_status="SAFE", active_change=None, current_stage=None)
        self._write_master(final, label="master.abort_precommit")
        self.last_terminal_outcome = "ABORTED_PRECOMMIT"
        return True

    def _assert_partial_history_known(self, history_dir: Path, change: dict[str, Any]) -> None:
        allowed: dict[str, bytes | dict[str, Any]] = {}
        for op in change["operations"]:
            if op["kind"] in ("REPLACE", "DELETE"):
                allowed[f"old/{op['operation_id']}.bin"] = op["old"]
        manifest = history_dir / "HISTORY.json"
        if manifest.exists() or manifest.is_symlink():
            value, raw = self._load_json(manifest, "HISTORY")
            validate_history(value)
            allowed["HISTORY.json"] = raw
        self._assert_no_unknown_files(history_dir, allowed)
