from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .protocol import (
    STAGES_SAFE,
    FaultInjector,
    ProtocolError,
    RecoveryBlocked,
    canonical_json_bytes,
    sha256_bytes,
    strict_json_bytes,
    validate_change,
    validate_master,
    validate_ready,
    validate_relative_path,
)


@dataclass(frozen=True)
class Observed:
    state: str
    fingerprint: dict[str, Any] | None
    detail: str | None = None


class StorageRuntime:
    def __init__(self, hub_root: str | Path, *, fault: FaultInjector | None = None):
        self.root = Path(hub_root)
        self.canonical = self.root / "canonical"
        self.work = self.root / "work" / "reconciliation"
        self.changes = self.work / "changes"
        self.postchecks = self.work / "postcheck"
        self.control = self.root / "control"
        self.active_control = self.control / "active"
        self.atomic_dir = self.control / ".atomic"
        self.history_root = self.root / "history"
        self.master_path = self.root / "MASTER.json"
        self.fault = fault or FaultInjector()
        self.last_terminal_outcome: str | None = None

    @staticmethod
    def bootstrap(hub_root: str | Path) -> None:
        root = Path(hub_root)
        for path in (
            root / "canonical",
            root / "work" / "projects",
            root / "work" / "reconciliation" / "changes",
            root / "work" / "reconciliation" / "postcheck",
            root / "control" / ".atomic",
            root / "history",
        ):
            path.mkdir(parents=True, exist_ok=True)
        master = root / "MASTER.json"
        if master.exists():
            raise ProtocolError("MASTER.json already exists")
        data = {
            "schema": "keelaryn.master.v1",
            "state": "READY",
            "canonical_read_status": "SAFE",
            "canonical_epoch": 0,
            "active_change": None,
            "current_stage": None,
            "last_completed_change": None,
        }
        tmp = root / ".MASTER.json.bootstrap.tmp"
        with open(tmp, "xb") as fh:
            raw = canonical_json_bytes(data)
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, master)
        StorageRuntime._fsync_dir(root)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _regular_file(path: Path) -> bool:
        try:
            st = path.lstat()
        except FileNotFoundError:
            return False
        return stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode)

    @staticmethod
    def _real_dir(path: Path) -> bool:
        try:
            st = path.lstat()
        except FileNotFoundError:
            return False
        return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)

    def _require_infra(self) -> None:
        if not self._real_dir(self.root):
            raise ProtocolError("Hub root must be a real directory")
        for path in (self.canonical, self.changes, self.postchecks, self.control, self.atomic_dir, self.history_root):
            if not self._real_dir(path):
                raise ProtocolError(f"required real directory missing/unsafe: {path}")
        if not self._regular_file(self.master_path):
            raise ProtocolError("MASTER.json missing or unsafe")

    def _read_raw(self, path: Path, label: str) -> bytes:
        if not self._regular_file(path):
            raise ProtocolError(f"{label}: missing or non-regular file")
        return path.read_bytes()

    def _load_json(self, path: Path, label: str) -> tuple[Any, bytes]:
        raw = self._read_raw(path, label)
        return strict_json_bytes(raw, label=label), raw

    def _load_master(self) -> dict[str, Any]:
        value, _ = self._load_json(self.master_path, "MASTER")
        return validate_master(value)

    def _temp_path(self, destination: Path) -> Path:
        digest = hashlib.sha256(str(destination.absolute()).encode("utf-8")).hexdigest()
        return self.atomic_dir / f"{digest}.tmp"

    def _prepare_temp(self, destination: Path) -> Path:
        temp = self._temp_path(destination)
        if temp.exists() or temp.is_symlink():
            try:
                st = temp.lstat()
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                    raise ProtocolError(f"unsafe atomic temp residue: {temp}")
                temp.unlink()
                self._fsync_dir(temp.parent)
        return temp

    def _atomic_write(self, destination: Path, data: bytes, *, label: str) -> None:
        if not self._real_dir(destination.parent):
            raise ProtocolError(f"{label}: destination parent missing/unsafe")
        temp = self._prepare_temp(destination)
        with open(temp, "xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        self.fault.hit(f"atomic.{label}.after_temp_fsync")
        os.replace(temp, destination)
        self._fsync_dir(destination.parent)
        if destination.parent != self.atomic_dir:
            self._fsync_dir(self.atomic_dir)
        self.fault.hit(f"atomic.{label}.after_replace")

    def _atomic_copy(self, source: Path, destination: Path, expected: dict[str, Any], *, label: str) -> None:
        if expected["state"] != "PRESENT":
            raise ProtocolError(f"{label}: expected PRESENT")
        if not self._regular_file(source):
            raise ProtocolError(f"{label}: source missing/unsafe")
        if not self._real_dir(destination.parent):
            raise ProtocolError(f"{label}: destination parent missing/unsafe")
        temp = self._prepare_temp(destination)
        h = hashlib.sha256()
        size = 0
        with open(source, "rb") as src, open(temp, "xb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        actual = {"state": "PRESENT", "sha256": h.hexdigest(), "size": size}
        if actual != expected:
            temp.unlink(missing_ok=True)
            self._fsync_dir(self.atomic_dir)
            raise ProtocolError(f"{label}: source fingerprint mismatch")
        self.fault.hit(f"atomic.{label}.after_temp_fsync")
        os.replace(temp, destination)
        self._fsync_dir(destination.parent)
        if destination.parent != self.atomic_dir:
            self._fsync_dir(self.atomic_dir)
        self.fault.hit(f"atomic.{label}.after_replace")
        if self._fingerprint_regular(destination) != expected:
            raise ProtocolError(f"{label}: copied fingerprint mismatch")

    def _atomic_json(self, destination: Path, value: Any, *, label: str) -> None:
        self._atomic_write(destination, canonical_json_bytes(value), label=label)

    def _write_master(self, value: dict[str, Any], *, label: str) -> None:
        validate_master(value)
        self._atomic_json(self.master_path, value, label=label)

    def _fingerprint_regular(self, path: Path) -> dict[str, Any]:
        if not self._regular_file(path):
            raise ProtocolError(f"not a regular file: {path}")
        h = hashlib.sha256()
        size = 0
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        return {"state": "PRESENT", "sha256": h.hexdigest(), "size": size}

    def _safe_target(self, relative: str) -> Path:
        validate_relative_path(relative, "target")
        current = self.canonical
        if not self._real_dir(current):
            raise ProtocolError("canonical root unsafe")
        parts = relative.split("/")
        for part in parts[:-1]:
            current = current / part
            if not self._real_dir(current):
                raise ProtocolError(f"target parent missing/unsafe: {relative}")
        return current / parts[-1]

    def _safe_existing_file(self, base: Path, relative: str, label: str) -> Path:
        validate_relative_path(relative, label)
        current = base
        if not self._real_dir(current):
            raise ProtocolError(f"{label}: base unsafe")
        parts = relative.split("/")
        for part in parts[:-1]:
            current = current / part
            if not self._real_dir(current):
                raise ProtocolError(f"{label}: parent missing/unsafe")
        path = current / parts[-1]
        if not self._regular_file(path):
            raise ProtocolError(f"{label}: file missing/unsafe")
        return path

    def _observe_target(self, relative: str) -> Observed:
        try:
            target = self._safe_target(relative)
        except ProtocolError as exc:
            return Observed("UNKNOWN", None, str(exc))
        try:
            st = target.lstat()
        except FileNotFoundError:
            return Observed("ABSENT", {"state": "ABSENT"})
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            return Observed("UNKNOWN", None, "target is symlink or non-regular")
        try:
            fp = self._fingerprint_regular(target)
        except (OSError, ProtocolError) as exc:
            return Observed("UNKNOWN", None, str(exc))
        return Observed("PRESENT", fp)

    def _classify(self, entry: dict[str, Any]) -> tuple[str, Observed]:
        observed = self._observe_target(entry["target"])
        if observed.state == "UNKNOWN":
            return "UNKNOWN", observed
        if observed.fingerprint == entry["old"]:
            return "OLD", observed
        if observed.fingerprint == entry["new"]:
            return "NEW", observed
        return "UNKNOWN", observed

    def _active_identity(self, master: dict[str, Any]) -> dict[str, Any]:
        active = master.get("active_change")
        if not isinstance(active, dict):
            raise ProtocolError("missing active identity")
        return active

    def _master_stage(self, master: dict[str, Any], stage: str, *, read_status: str | None = None) -> dict[str, Any]:
        out = json.loads(json.dumps(master))
        out["state"] = "ACTIVE"
        out["current_stage"] = stage
        out["canonical_read_status"] = read_status or ("SAFE" if stage in STAGES_SAFE else "UNSAFE")
        return out

    def _discover_ready(self) -> list[Path]:
        found: list[Path] = []
        for child in self.changes.iterdir():
            try:
                st = child.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(st.st_mode):
                if (child / "READY.json").exists():
                    raise ProtocolError("symlinked change directory is forbidden")
                continue
            if not stat.S_ISDIR(st.st_mode):
                continue
            ready = child / "READY.json"
            if ready.exists() or ready.is_symlink():
                found.append(ready)
        return sorted(found, key=lambda p: str(p))

    def _load_ready_change(self, ready_path: Path) -> tuple[dict[str, Any], dict[str, Any], bytes, Path]:
        ready_value, _ = self._load_json(ready_path, "READY")
        ready = validate_ready(ready_value)
        change_dir = ready_path.parent
        if change_dir.name != ready["change_id"]:
            raise ProtocolError("READY change_id must equal change directory name")
        change_value, raw = self._load_json(change_dir / "CHANGE.json", "CHANGE")
        change = validate_change(change_value)
        if ready["change_id"] != change["change_id"]:
            raise ProtocolError("READY/CHANGE change_id mismatch")
        if ready["change_sha256"] != sha256_bytes(raw):
            raise ProtocolError("READY/CHANGE exact hash mismatch")
        return ready, change, raw, change_dir

    def _prepared_source(self, change_dir: Path, op: dict[str, Any]) -> Path:
        return self._safe_existing_file(change_dir, op["prepared_path"], f"prepared:{op['operation_id']}")

    def _validate_old_targets(self, operations: Iterable[dict[str, Any]], *, blocked_on_unknown: bool = False) -> None:
        for op in operations:
            entry = {"target": op["target"], "old": op["old"], "new": op["new"]}
            classification, observed = self._classify(entry)
            if classification != "OLD":
                if blocked_on_unknown:
                    self._block_from_observed("TARGET_UNKNOWN", op, observed, "target no longer matches OLD")
                    raise RecoveryBlocked(op["target"])
                raise ProtocolError(f"target does not match OLD: {op['target']}")

    def _preflight(self, master: dict[str, Any], ready_path: Path) -> tuple[dict[str, Any], bytes, Path]:
        ready, change, raw, change_dir = self._load_ready_change(ready_path)
        if change["base_canonical_epoch"] != master["canonical_epoch"]:
            raise ProtocolError("stale base_canonical_epoch")
        hist_path = self.history_root / change["change_id"]
        if hist_path.exists() or hist_path.is_symlink():
            raise ProtocolError("change_id already has durable history")
        for op in change["operations"]:
            self._safe_target(op["target"])
            if op["kind"] in ("ADD", "REPLACE"):
                source = self._prepared_source(change_dir, op)
                if self._fingerprint_regular(source) != op["new"]:
                    raise ProtocolError(f"prepared fingerprint mismatch: {op['operation_id']}")
        self._validate_old_targets(change["operations"])
        return change, raw, change_dir
