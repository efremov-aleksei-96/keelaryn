from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .protocol import ProtocolError, RecoveryBlocked


class AbortMixin:
    """SAFE-only abort: remove known Core-owned partial state without trusting its bytes."""

    def _assert_only_known_paths(self, root: Path, allowed_files: set[str]) -> None:
        if not root.exists() and not root.is_symlink():
            return
        if not self._real_dir(root):
            raise ProtocolError(f"abort cleanup root unsafe: {root}")
        actual_files: set[str] = set()
        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            base_path = Path(base)
            for name in dirs:
                path = base_path / name
                if path.is_symlink() or not self._real_dir(path):
                    raise ProtocolError(f"abort cleanup directory unsafe: {path}")
            for name in files:
                path = base_path / name
                if path.is_symlink() or not self._regular_file(path):
                    raise ProtocolError(f"abort cleanup file unsafe: {path}")
                actual_files.add(path.relative_to(root).as_posix())
        extra = actual_files - allowed_files
        if extra:
            raise ProtocolError(f"unexpected abort cleanup material: {sorted(extra)}")

    def _stage_abort_precommit(self, master: dict[str, Any]) -> bool:
        identity = self._active_identity(master)
        try:
            change, raw = self._load_cleanup_change(master)
            if change is None or raw is None:
                raise ProtocolError("cannot authenticate active change during abort")

            # The only condition that matters for canonical safety is that every
            # target is still OLD. Core-owned partial staged/snapshot bytes may be
            # corrupt; that is a valid reason for this SAFE abort and does not make
            # them user data that must be preserved.
            for op in change["operations"]:
                entry = {"target": op["target"], "old": op["old"], "new": op["new"]}
                classification, observed = self._classify(entry)
                if classification != "OLD":
                    self._block(master, "TARGET_UNKNOWN", op, observed, "precommit abort found canonical target not OLD")

            history_dir = self._history_dir(master)
            if history_dir.exists() or history_dir.is_symlink():
                allowed_history = {"HISTORY.json"}
                allowed_history.update(
                    f"old/{op['operation_id']}.bin"
                    for op in change["operations"]
                    if op["kind"] in ("REPLACE", "DELETE")
                )
                self._assert_only_known_paths(history_dir, allowed_history)
                self._remove_known_tree(history_dir, fault_prefix="abort.history")

            if self.active_control.exists() or self.active_control.is_symlink():
                allowed_control = {"CHANGE.json", "CONTROL.json"}
                allowed_control.update(
                    op["prepared_path"]
                    for op in change["operations"]
                    if op["kind"] in ("ADD", "REPLACE")
                )
                self._assert_only_known_paths(self.active_control, allowed_control)
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
