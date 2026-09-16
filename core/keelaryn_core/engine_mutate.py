from __future__ import annotations

from typing import Any

from .protocol import ProtocolError, RecoveryBlocked, strict_json_bytes, validate_postcheck


class MutationMixin:
    def _stage_apply(self, master: dict[str, Any]) -> bool:
        change, _ = self._unsafe_change(master)
        history = self._unsafe_history(master)
        entries = {entry["operation_id"]: entry for entry in history["entries"]}
        try:
            for op in change["operations"]:
                entry = entries[op["operation_id"]]
                classification, observed = self._classify(entry)
                if classification == "NEW":
                    continue
                if classification == "UNKNOWN":
                    self._block(master, "TARGET_UNKNOWN", op, observed, "target is neither OLD nor NEW during APPLY")

                self.fault.hit(f"apply.{op['operation_id']}.before")
                target = self._safe_target(op["target"])

                if op["kind"] in ("REPLACE", "DELETE"):
                    fresh, fresh_observed = self._classify(entry)
                    if fresh == "UNKNOWN":
                        self._block(master, "TARGET_UNKNOWN", op, fresh_observed, "destructive target changed before mutation")
                    if fresh == "NEW":
                        continue

                if op["kind"] in ("ADD", "REPLACE"):
                    staged = self._safe_existing_file(self.active_control, op["prepared_path"], f"staged:{op['operation_id']}")
                    if self._fingerprint_regular(staged) != op["new"]:
                        self._block(master, "STAGED_INPUT_INVALID", op, None, "staged new bytes changed during APPLY")
                    self._atomic_copy(staged, target, op["new"], label=f"publish.{op['operation_id']}")
                else:
                    if not self._regular_file(target):
                        self._block(master, "TARGET_UNKNOWN", op, self._observe_target(op["target"]), "DELETE target is no longer exact OLD")
                    target.unlink()
                    self._fsync_dir(target.parent)

                final, final_observed = self._classify(entry)
                if final != "NEW":
                    self._block(master, "TARGET_UNKNOWN", op, final_observed, "operation did not produce NEW")
                self.fault.hit(f"apply.{op['operation_id']}.after")
        except RecoveryBlocked:
            raise
        except Exception:
            states = self._classifications(history)
            unknown = next((item for item in states if item[1] == "UNKNOWN"), None)
            if unknown is not None:
                entry, _, observed = unknown
                self._block(master, "TARGET_UNKNOWN", entry, observed, "APPLY failure left UNKNOWN target")
            self._write_master(
                self._master_stage(master, "ROLLBACK", read_status="UNSAFE"),
                label="master.apply_error_rollback",
            )
            return True

        self._write_master(
            self._master_stage(master, "WAIT_POSTCHECK", read_status="UNSAFE"),
            label="master.apply_done",
        )
        return True

    def _stage_wait_postcheck(self, master: dict[str, Any]) -> bool:
        history = self._unsafe_history(master)
        classes = self._classifications(history)
        unknown = next((item for item in classes if item[1] == "UNKNOWN"), None)
        if unknown is not None:
            entry, _, observed = unknown
            self._block(master, "TARGET_UNKNOWN", entry, observed, "target UNKNOWN while waiting for semantic post-check")
        if any(classification == "OLD" for _, classification, _ in classes):
            self._write_master(
                self._master_stage(master, "ROLLBACK", read_status="UNSAFE"),
                label="master.wait_integrity_rollback",
            )
            return True

        identity = self._active_identity(master)
        source = self.postchecks / f"{identity['change_id']}.json"
        if not source.exists() and not source.is_symlink():
            return False
        try:
            if not self._regular_file(source):
                return False
            raw = source.read_bytes()
            post = validate_postcheck(strict_json_bytes(raw, label="POSTCHECK"))
            if (
                post["change_id"] != identity["change_id"]
                or post["change_sha256"] != identity["change_sha256"]
                or post["base_canonical_epoch"] != identity["base_canonical_epoch"]
            ):
                return False
        except ProtocolError:
            return False

        accepted = self.active_control / "POSTCHECK.json"
        if accepted.exists() or accepted.is_symlink():
            if self._read_raw(accepted, "accepted POSTCHECK") != raw:
                self._block(master, "FINAL_STATE_INVALID", None, None, "accepted semantic post-check changed")
        else:
            self._atomic_write(accepted, raw, label="postcheck.accept")
        if self._read_raw(accepted, "accepted POSTCHECK") != raw:
            self._block(master, "FINAL_STATE_INVALID", None, None, "accepted semantic post-check copy mismatch")

        next_stage = "FINALIZE_COMMIT" if post["decision"] == "PASS" else "ROLLBACK"
        self._write_master(
            self._master_stage(master, next_stage, read_status="UNSAFE"),
            label="master.postcheck_decision",
        )
        return True

    def _stage_rollback(self, master: dict[str, Any]) -> bool:
        history = self._unsafe_history(master)
        history_dir = self._history_dir(master)
        for entry in reversed(history["entries"]):
            classification, observed = self._classify(entry)
            if classification == "OLD":
                continue
            if classification == "UNKNOWN":
                self._block(master, "TARGET_UNKNOWN", entry, observed, "target is neither OLD nor NEW during ROLLBACK")

            self.fault.hit(f"rollback.{entry['operation_id']}.before")
            target = self._safe_target(entry["target"])
            if entry["kind"] == "ADD":
                if not self._regular_file(target):
                    self._block(master, "TARGET_UNKNOWN", entry, self._observe_target(entry["target"]), "ADD rollback target is not exact NEW")
                target.unlink()
                self._fsync_dir(target.parent)
            else:
                snapshot = self._safe_existing_file(
                    history_dir,
                    entry["snapshot_path"],
                    f"history snapshot:{entry['operation_id']}",
                )
                if self._fingerprint_regular(snapshot) != entry["old"]:
                    self._block(master, "HISTORY_INVALID", entry, None, "rollback snapshot fingerprint mismatch")
                self._atomic_copy(
                    snapshot,
                    target,
                    entry["old"],
                    label=f"rollback.restore.{entry['operation_id']}",
                )

            final, final_observed = self._classify(entry)
            if final != "OLD":
                self._block(master, "TARGET_UNKNOWN", entry, final_observed, "rollback did not restore OLD")
            self.fault.hit(f"rollback.{entry['operation_id']}.after")

        self._write_master(
            self._master_stage(master, "FINALIZE_ROLLBACK", read_status="UNSAFE"),
            label="master.rollback_done",
        )
        return True
