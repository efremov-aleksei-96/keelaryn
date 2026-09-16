from __future__ import annotations

from typing import Any

from .protocol import ProtocolError, RecoveryBlocked, validate_change, validate_control, validate_history


class PreparationMixin:
    def _stage_claim(self, master: dict[str, Any]) -> bool:
        identity = self._active_identity(master)
        source_dir = self._source_change_dir(identity)
        try:
            value, source_raw = self._load_json(source_dir / "CHANGE.json", "source CHANGE")
            change = validate_change(value)
            if change["change_id"] != identity["change_id"] or self._control_identity({
                "change_id": change["change_id"],
                "change_sha256": self._sha(source_raw),
                "base_canonical_epoch": change["base_canonical_epoch"],
            }) != identity:
                raise ProtocolError("source CHANGE identity changed after activation")

            if self.active_control.exists() or self.active_control.is_symlink():
                if not self._real_dir(self.active_control):
                    raise ProtocolError("active control path unsafe")
            else:
                self.active_control.mkdir()
                self._fsync_dir(self.control)

            claimed = self._control_change_path()
            if claimed.exists() or claimed.is_symlink():
                if self._read_raw(claimed, "CONTROL CHANGE") != source_raw:
                    raise ProtocolError("partial claim has different CHANGE")
            else:
                self._atomic_write(claimed, source_raw, label="claim.change")

            for op in change["operations"]:
                if op["kind"] not in ("ADD", "REPLACE"):
                    continue
                source = self._prepared_source(source_dir, op)
                destination = self.active_control / op["prepared_path"]
                self._ensure_relative_parent(self.active_control, op["prepared_path"])
                if destination.exists() or destination.is_symlink():
                    if not self._regular_file(destination) or self._fingerprint_regular(destination) != op["new"]:
                        raise ProtocolError(f"partial staged claim mismatch: {op['operation_id']}")
                else:
                    self._atomic_copy(source, destination, op["new"], label=f"claim.prepared.{op['operation_id']}")

            control = {"schema": "keelaryn.control.v1", **identity}
            control_path = self.active_control / "CONTROL.json"
            if control_path.exists() or control_path.is_symlink():
                existing, _ = self._load_json(control_path, "CONTROL")
                validated = validate_control(existing)
                if self._control_identity(validated) != identity:
                    raise ProtocolError("partial CONTROL identity mismatch")
            else:
                self._atomic_json(control_path, control, label="claim.control")
            self._verify_claim_tree(change, source_raw, identity)
        except RecoveryBlocked:
            raise
        except Exception:
            self._write_master(self._master_stage(master, "ABORT_PRECOMMIT"), label="master.claim_abort")
            return True

        self._write_master(self._master_stage(master, "SNAPSHOT"), label="master.claim_done")
        return True

    def _stage_snapshot(self, master: dict[str, Any]) -> bool:
        try:
            change, _ = self._load_control_change(master)
            history_dir = self._history_dir(master)
            if history_dir.exists() or history_dir.is_symlink():
                if not self._real_dir(history_dir):
                    raise ProtocolError("history path unsafe")
            else:
                history_dir.mkdir()
                self._fsync_dir(self.history_root)

            old_dir = history_dir / "old"
            if old_dir.exists() or old_dir.is_symlink():
                if not self._real_dir(old_dir):
                    raise ProtocolError("history old path unsafe")
            else:
                old_dir.mkdir()
                self._fsync_dir(history_dir)

            entries = []
            for op in change["operations"]:
                snapshot_path = None
                if op["kind"] in ("REPLACE", "DELETE"):
                    snapshot_path = f"old/{op['operation_id']}.bin"
                    target = self._safe_target(op["target"])
                    destination = history_dir / snapshot_path
                    if destination.exists() or destination.is_symlink():
                        if not self._regular_file(destination) or self._fingerprint_regular(destination) != op["old"]:
                            raise ProtocolError(f"history snapshot mismatch: {op['operation_id']}")
                    else:
                        self._atomic_copy(target, destination, op["old"], label=f"snapshot.{op['operation_id']}")
                entries.append({
                    "operation_id": op["operation_id"],
                    "kind": op["kind"],
                    "target": op["target"],
                    "old": op["old"],
                    "new": op["new"],
                    "snapshot_path": snapshot_path,
                })

            identity = self._active_identity(master)
            history = {
                "schema": "keelaryn.history.v1",
                "status": "VERIFIED",
                "change_id": identity["change_id"],
                "change_sha256": identity["change_sha256"],
                "base_canonical_epoch": identity["base_canonical_epoch"],
                "entries": entries,
            }
            validate_history(history)
            manifest = history_dir / "HISTORY.json"
            if manifest.exists() or manifest.is_symlink():
                existing, _ = self._load_json(manifest, "HISTORY")
                if validate_history(existing) != history:
                    raise ProtocolError("existing HISTORY manifest differs")
            else:
                self._atomic_json(manifest, history, label="snapshot.history")
            self._verify_history_snapshots(history)
        except RecoveryBlocked:
            raise
        except Exception:
            self._write_master(self._master_stage(master, "ABORT_PRECOMMIT"), label="master.snapshot_abort")
            return True

        self._write_master(self._master_stage(master, "ENTER_UNSAFE"), label="master.snapshot_done")
        return True

    def _stage_enter_unsafe(self, master: dict[str, Any]) -> bool:
        try:
            change, raw = self._load_control_change(master)
            self._verify_claim_tree(change, raw, self._active_identity(master))
            history, _ = self._history_manifest(master)
            self._verify_history_snapshots(history)
            self._validate_old_targets(change["operations"])
            for op in change["operations"]:
                self._safe_target(op["target"])
        except RecoveryBlocked:
            raise
        except Exception:
            self._write_master(self._master_stage(master, "ABORT_PRECOMMIT"), label="master.enter_unsafe_abort")
            return True

        self._write_master(
            self._master_stage(master, "APPLY", read_status="UNSAFE"),
            label="master.enter_unsafe",
        )
        return True

    @staticmethod
    def _sha(raw: bytes) -> str:
        from .protocol import sha256_bytes
        return sha256_bytes(raw)
