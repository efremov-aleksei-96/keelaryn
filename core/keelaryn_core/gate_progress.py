from __future__ import annotations

import json
import os
import re
import stat
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO


PROGRESS_SCHEMA = "keelaryn.gate-progress.v1"
_TOKEN = re.compile(r"^[A-Z][A-Z0-9_:-]{0,63}$")
_MUTATION_STATES = {
    "READ_ONLY",
    "MUTATION_NOT_STARTED",
    "PRECOMMIT_VERIFIED",
    "COMMITTING",
    "MUTATION_ACTIVE",
    "COMMITTED",
    "MUTATION_COMMITTED",
    "POSTCOMMIT_VERIFYING",
    "VERIFIED",
}
_DURABLE_STATES = {"UNKNOWN", "ABSENT", "PRESENT"}
_ALLOWED_INPUT_KEYS = {
    "phase",
    "event",
    "mutation_state",
    "pass_index",
    "pass_total",
    "item_index",
    "item_total",
    "authority_state",
    "target_state",
    "evidence_state",
}


class GateProgressError(RuntimeError):
    """Sanitized progress/status channel cannot be maintained safely."""


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise GateProgressError(f"{label} is invalid")
    return value


def _counter(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GateProgressError(f"{label} is invalid")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class GateProgressJournal:
    """Private JSONL progress journal with sanitized live heartbeat output.

    The journal is append-only across runs. Each run has a fresh random run_id and
    monotonically increasing sequence. No caller-supplied free-form strings are
    accepted: phase/event/state values are restricted tokens and progress values
    are counters only, preventing Drive IDs, paths or payload names from leaking.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        operation: str,
        heartbeat_seconds: float = 30.0,
        stream: TextIO | None = None,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise GateProgressError("heartbeat interval must be positive")
        self.path = Path(path).absolute()
        self.operation = _token(operation, "operation")
        self.heartbeat_seconds = float(heartbeat_seconds)
        self.stream = sys.stderr if stream is None else stream
        self.run_id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._sequence = 0
        self._started = time.monotonic()
        self._phase_started = self._started
        self._last_progress = self._started
        self._phase = "PREFLIGHT"
        self._mutation_state = "MUTATION_NOT_STARTED"
        self._authority_state = "UNKNOWN"
        self._target_state = "UNKNOWN"
        self._evidence_state = "UNKNOWN"
        self._pass_index: int | None = None
        self._pass_total: int | None = None
        self._item_index: int | None = None
        self._item_total: int | None = None

        self._validate_path()
        self.record(
            {
                "phase": "PREFLIGHT",
                "event": "START",
                "mutation_state": "MUTATION_NOT_STARTED",
                "authority_state": "UNKNOWN",
                "target_state": "UNKNOWN",
                "evidence_state": "UNKNOWN",
            }
        )
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name="keelaryn-gate-progress",
            daemon=True,
        )
        self._thread.start()

    def _validate_path(self) -> None:
        parent = self.path.parent
        try:
            info = parent.stat(follow_symlinks=False)
        except OSError as exc:
            raise GateProgressError("progress journal parent cannot be inspected") from exc
        if parent.is_symlink() or not stat.S_ISDIR(info.st_mode):
            raise GateProgressError("progress journal parent must be one real directory")
        if os.name == "posix":
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise GateProgressError(
                    "progress journal parent must be owner-controlled mode 0700"
                )
        if self.path.exists() or self.path.is_symlink():
            try:
                existing = self.path.stat(follow_symlinks=False)
            except OSError as exc:
                raise GateProgressError("progress journal cannot be inspected") from exc
            if self.path.is_symlink() or not stat.S_ISREG(existing.st_mode):
                raise GateProgressError("progress journal must be one regular file")
            if os.name == "posix":
                if existing.st_uid != os.geteuid() or stat.S_IMODE(existing.st_mode) != 0o600:
                    raise GateProgressError(
                        "progress journal must be owner-controlled mode 0600"
                    )

    def _append(self, raw: bytes) -> None:
        existed = self.path.exists() or self.path.is_symlink()
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if existed:
            self._validate_path()
        else:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise GateProgressError("progress journal appeared during creation") from exc
        except OSError as exc:
            raise GateProgressError("progress journal cannot be opened") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise GateProgressError("progress journal descriptor is not regular")
            if os.name == "posix":
                if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
                    raise GateProgressError(
                        "progress journal descriptor must be owner-controlled mode 0600"
                    )
            payload = raw + b"\n"
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise GateProgressError(
                        "progress journal append made no forward progress"
                    )
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        if not existed:
            _fsync_dir(self.path.parent)

    def _event_value(self, event: str) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "schema": PROGRESS_SCHEMA,
            "operation": self.operation,
            "run_id": self.run_id,
            "sequence": self._sequence,
            "timestamp_utc": _utc_now(),
            "event": event,
            "phase": self._phase,
            "mutation_state": self._mutation_state,
            "authority_state": self._authority_state,
            "target_state": self._target_state,
            "evidence_state": self._evidence_state,
            "pass_index": self._pass_index,
            "pass_total": self._pass_total,
            "item_index": self._item_index,
            "item_total": self._item_total,
            "phase_elapsed_seconds": int(now - self._phase_started),
            "total_elapsed_seconds": int(now - self._started),
            "last_progress_age_seconds": int(now - self._last_progress),
        }

    def _publish_locked(self, event: str, *, activity: bool) -> dict[str, Any]:
        if self._failure is not None:
            raise GateProgressError("progress heartbeat previously failed") from self._failure
        self._sequence += 1
        if activity:
            self._last_progress = time.monotonic()
        value = self._event_value(event)
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._append(raw)
        if self.stream is not None:
            try:
                print("GATE_PROGRESS " + raw.decode("utf-8"), file=self.stream, flush=True)
            except OSError:
                # The durable 0600 journal is authoritative. A detached terminal
                # must not turn an otherwise intact status channel into a mutation.
                pass
        return value

    def record(self, update: Mapping[str, object]) -> dict[str, Any]:
        unknown = set(update) - _ALLOWED_INPUT_KEYS
        if unknown:
            raise GateProgressError("progress update contains unsupported keys")
        phase = _token(update.get("phase", self._phase), "phase")
        event = _token(update.get("event", "PROGRESS"), "event")
        mutation_state = update.get("mutation_state", self._mutation_state)
        if mutation_state not in _MUTATION_STATES:
            raise GateProgressError("mutation state is invalid")

        authority_state = update.get("authority_state", self._authority_state)
        target_state = update.get("target_state", self._target_state)
        evidence_state = update.get("evidence_state", self._evidence_state)
        if authority_state not in _DURABLE_STATES:
            raise GateProgressError("authority state is invalid")
        if target_state not in _DURABLE_STATES:
            raise GateProgressError("target state is invalid")
        if evidence_state not in _DURABLE_STATES:
            raise GateProgressError("evidence state is invalid")

        with self._lock:
            if phase != self._phase:
                self._phase = phase
                self._phase_started = time.monotonic()
                self._pass_index = None
                self._pass_total = None
                self._item_index = None
                self._item_total = None
            self._mutation_state = str(mutation_state)
            self._authority_state = str(authority_state)
            self._target_state = str(target_state)
            self._evidence_state = str(evidence_state)
            if "pass_index" in update:
                self._pass_index = _counter(update["pass_index"], "pass_index")
            if "pass_total" in update:
                self._pass_total = _counter(update["pass_total"], "pass_total")
            if "item_index" in update:
                self._item_index = _counter(update["item_index"], "item_index")
            if "item_total" in update:
                self._item_total = _counter(update["item_total"], "item_total")
            return self._publish_locked(event, activity=True)

    def heartbeat_once(self) -> dict[str, Any]:
        with self._lock:
            return self._publish_locked("HEARTBEAT", activity=False)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                self.heartbeat_once()
            except BaseException as exc:
                with self._lock:
                    self._failure = exc
                return

    def assert_healthy(self) -> None:
        with self._lock:
            if self._failure is not None:
                raise GateProgressError("progress heartbeat failed") from self._failure

    def finish(self, outcome: str, *, phase: str) -> dict[str, Any]:
        outcome = _token(outcome, "outcome")
        phase = _token(phase, "phase")
        self._stop.set()
        self._thread.join(timeout=max(1.0, min(self.heartbeat_seconds, 5.0)))
        with self._lock:
            self._phase = phase
            self._phase_started = time.monotonic()
            return self._publish_locked(outcome, activity=True)


__all__ = [
    "GateProgressError",
    "GateProgressJournal",
    "PROGRESS_SCHEMA",
]
