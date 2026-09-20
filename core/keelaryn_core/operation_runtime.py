from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .gate_progress import GateProgressJournal


STATE_SCHEMA = "keelaryn.operation-runtime-state.v1"
RESULT_SCHEMA = "keelaryn.operation-runtime-result.v1"
HANDOFF_SCHEMA = "keelaryn.operation-runtime-handoff.v1"

_OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")
_TOKEN = re.compile(r"^[A-Z][A-Z0-9_:-]{0,63}$")
_OID = re.compile(r"^[0-9a-f]{40}$")

_EXECUTION_STATES = {
    "CREATED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "RECOVERY_REQUIRED",
}

_MUTATION_SEQUENCE = (
    "MUTATION_NOT_STARTED",
    "PRECOMMIT_VERIFIED",
    "COMMITTING",
    "COMMITTED",
    "POSTCOMMIT_VERIFYING",
    "VERIFIED",
)

_RECOVERY_BOUNDARY = {
    "COMMITTING",
    "COMMITTED",
    "POSTCOMMIT_VERIFYING",
}

_TERMINAL_EXECUTION = {
    "SUCCEEDED",
    "FAILED",
    "RECOVERY_REQUIRED",
}


class OperationRuntimeError(RuntimeError):
    """Durable operation state is invalid, unsafe, or ambiguous."""


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise OperationRuntimeError(f"{label} is invalid")
    return value


def _source_commit(value: object) -> str:
    if not isinstance(value, str) or _OID.fullmatch(value) is None:
        raise OperationRuntimeError(
            "source_commit must be exactly 40 lowercase hexadecimal characters"
        )
    return value


def _operation_id(value: object) -> str:
    if not isinstance(value, str) or _OPERATION_ID.fullmatch(value) is None:
        raise OperationRuntimeError("operation_id is invalid")
    return value


def _seconds(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OperationRuntimeError(f"{label} must be a positive integer")
    return value


def _utc(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _epoch(value: object, label: str) -> float:
    if not isinstance(value, str):
        raise OperationRuntimeError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationRuntimeError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise OperationRuntimeError(f"{label} must be timezone-aware")
    return parsed.timestamp()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _private_dir(path: Path, label: str, *, create: bool = False) -> Path:
    path = path.absolute()
    if create and not path.exists():
        path.mkdir(parents=True, mode=0o700)
        if os.name == "posix":
            os.chmod(path, 0o700)
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationRuntimeError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise OperationRuntimeError(f"{label} must be one real directory")
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise OperationRuntimeError(
                f"{label} must be owner-controlled mode 0700"
            )
    return path


def _private_file(path: Path, label: str) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationRuntimeError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise OperationRuntimeError(f"{label} must be one regular file")
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OperationRuntimeError(
                f"{label} must be owner-controlled mode 0600"
            )
    return path


def _atomic_replace_private(path: Path, raw: bytes) -> None:
    parent = _private_dir(path.parent, "operation state parent")
    temp = parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        os.replace(temp, path)
        _fsync_dir(parent)
    finally:
        temp.unlink(missing_ok=True)
    _private_file(path, "operation state file")


def _write_new_private(path: Path, raw: bytes, label: str) -> None:
    parent = _private_dir(path.parent, f"{label} parent")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise OperationRuntimeError(f"{label} already exists") from exc
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    _fsync_dir(parent)
    _private_file(path, label)


class OperationRuntime:
    """Durable status authority for long-running administrative operations.

    State and result files contain only sanitized tokens, source commit identity,
    counters and timestamps. Secrets, Drive IDs, paths and free-form exception
    text are deliberately outside this contract.
    """

    def __init__(self, root: str | Path, *, clock=time.time) -> None:
        self.root = _private_dir(
            Path(root),
            "operation runtime root",
            create=True,
        )
        self.clock = clock

    def _directory(self, operation_id: str) -> Path:
        return self.root / _operation_id(operation_id)

    def _state_path(self, operation_id: str) -> Path:
        return self._directory(operation_id) / "state.json"

    def _result_path(self, operation_id: str) -> Path:
        return self._directory(operation_id) / "result.json"

    def _handoff_path(self, operation_id: str) -> Path:
        return self._directory(operation_id) / "handoff.json"

    def _progress_path(self, operation_id: str) -> Path:
        return self._directory(operation_id) / "progress.jsonl"

    @property
    def latest_path(self) -> Path:
        return self.root / "LATEST"

    def _strict_state(self, value: Any) -> dict[str, Any]:
        expected = {
            "schema",
            "operation_id",
            "operation",
            "source_commit",
            "execution_state",
            "mutation_capable",
            "mutation_state",
            "phase",
            "timeout_seconds",
            "created_at_utc",
            "updated_at_utc",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise OperationRuntimeError("operation state has invalid keys")
        if value["schema"] != STATE_SCHEMA:
            raise OperationRuntimeError("operation state schema mismatch")
        _operation_id(value["operation_id"])
        _token(value["operation"], "operation")
        _source_commit(value["source_commit"])
        if value["execution_state"] not in _EXECUTION_STATES:
            raise OperationRuntimeError("execution_state is invalid")
        if not isinstance(value["mutation_capable"], bool):
            raise OperationRuntimeError("mutation_capable is invalid")
        _token(value["phase"], "phase")
        _seconds(value["timeout_seconds"], "timeout_seconds")
        _epoch(value["created_at_utc"], "created_at_utc")
        _epoch(value["updated_at_utc"], "updated_at_utc")
        if value["mutation_capable"]:
            if value["mutation_state"] not in _MUTATION_SEQUENCE:
                raise OperationRuntimeError("mutation_state is invalid")
        elif value["mutation_state"] != "READ_ONLY":
            raise OperationRuntimeError(
                "read-only operation cannot carry a mutation state"
            )
        return dict(value)

    def _read_state(self, operation_id: str) -> dict[str, Any]:
        path = _private_file(
            self._state_path(operation_id),
            "operation state",
        )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OperationRuntimeError("operation state is invalid JSON") from exc
        value = self._strict_state(value)
        if value["operation_id"] != operation_id:
            raise OperationRuntimeError("operation state identity mismatch")
        if path.read_bytes() != _canonical(value):
            raise OperationRuntimeError("operation state is not canonical JSON")
        return value

    def _write_state(self, value: Mapping[str, Any]) -> dict[str, Any]:
        strict = self._strict_state(dict(value))
        _atomic_replace_private(
            self._state_path(strict["operation_id"]),
            _canonical(strict),
        )
        self._write_handoff(strict)
        return strict

    def _next_action(self, state: Mapping[str, Any]) -> str:
        execution = state["execution_state"]
        mutation = state["mutation_state"]
        if execution == "SUCCEEDED":
            return "NONE"
        if execution == "RECOVERY_REQUIRED":
            return "READ_ONLY_RECONCILE"
        if execution == "FAILED":
            return "STOP"
        if execution == "CREATED":
            return "START"
        if mutation in _RECOVERY_BOUNDARY:
            return "WAIT_OR_RECONCILE"
        return "WAIT"

    def _write_handoff(self, state: Mapping[str, Any]) -> None:
        value = {
            "schema": HANDOFF_SCHEMA,
            "operation_id": state["operation_id"],
            "operation": state["operation"],
            "source_commit": state["source_commit"],
            "execution_state": state["execution_state"],
            "mutation_state": state["mutation_state"],
            "phase": state["phase"],
            "next_action": self._next_action(state),
        }
        _atomic_replace_private(
            self._handoff_path(state["operation_id"]),
            _canonical(value),
        )

    def _publish_latest(self, operation_id: str) -> None:
        _operation_id(operation_id)
        _atomic_replace_private(
            self.latest_path,
            (operation_id + "\n").encode("ascii"),
        )

    def resolve_operation_id(self, value: str) -> str:
        if value != "latest":
            return _operation_id(value)
        path = _private_file(self.latest_path, "operation runtime LATEST")
        try:
            observed = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise OperationRuntimeError("operation runtime LATEST is invalid") from exc
        return _operation_id(observed)

    def create(
        self,
        *,
        operation: str,
        source_commit: str,
        mutation_capable: bool,
        timeout_seconds: int,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        operation = _token(operation, "operation")
        source_commit = _source_commit(source_commit)
        timeout_seconds = _seconds(timeout_seconds, "timeout_seconds")
        if not isinstance(mutation_capable, bool):
            raise OperationRuntimeError("mutation_capable is invalid")
        oid = uuid.uuid4().hex if operation_id is None else _operation_id(operation_id)
        directory = self._directory(oid)
        if directory.exists() or directory.is_symlink():
            raise OperationRuntimeError("operation directory already exists")
        directory.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(directory, 0o700)
        _private_dir(directory, "operation directory")

        now = _utc(self.clock())
        state = {
            "schema": STATE_SCHEMA,
            "operation_id": oid,
            "operation": operation,
            "source_commit": source_commit,
            "execution_state": "CREATED",
            "mutation_capable": mutation_capable,
            "mutation_state": (
                "MUTATION_NOT_STARTED" if mutation_capable else "READ_ONLY"
            ),
            "phase": "PREFLIGHT",
            "timeout_seconds": timeout_seconds,
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        _write_new_private(
            self._state_path(oid),
            _canonical(state),
            "operation state",
        )
        self._write_handoff(state)
        self._publish_latest(oid)
        return dict(state)

    def start(self, operation_id: str) -> dict[str, Any]:
        oid = self.resolve_operation_id(operation_id)
        state = self._read_state(oid)
        if state["execution_state"] != "CREATED":
            raise OperationRuntimeError("only CREATED operation may start")
        state["execution_state"] = "RUNNING"
        state["updated_at_utc"] = _utc(self.clock())
        return self._write_state(state)

    def update(
        self,
        operation_id: str,
        *,
        phase: str | None = None,
        mutation_state: str | None = None,
    ) -> dict[str, Any]:
        oid = self.resolve_operation_id(operation_id)
        state = self._read_state(oid)
        if state["execution_state"] != "RUNNING":
            raise OperationRuntimeError("only RUNNING operation may advance")
        if phase is not None:
            state["phase"] = _token(phase, "phase")

        if mutation_state is not None:
            if not state["mutation_capable"]:
                if mutation_state != "READ_ONLY":
                    raise OperationRuntimeError(
                        "read-only operation cannot advance mutation state"
                    )
            else:
                if mutation_state not in _MUTATION_SEQUENCE:
                    raise OperationRuntimeError("mutation_state is invalid")
                current = _MUTATION_SEQUENCE.index(state["mutation_state"])
                requested = _MUTATION_SEQUENCE.index(mutation_state)
                if requested not in {current, current + 1}:
                    raise OperationRuntimeError(
                        "mutation state transition is not the next durable boundary"
                    )
            state["mutation_state"] = mutation_state

        state["updated_at_utc"] = _utc(self.clock())
        return self._write_state(state)

    def finish(
        self,
        operation_id: str,
        *,
        outcome: str,
        phase: str = "COMPLETE",
    ) -> dict[str, Any]:
        oid = self.resolve_operation_id(operation_id)
        state = self._read_state(oid)
        if state["execution_state"] != "RUNNING":
            raise OperationRuntimeError("only RUNNING operation may finish")
        phase = _token(phase, "phase")
        outcome = _token(outcome, "outcome")

        if outcome == "PASS":
            if state["mutation_capable"] and state["mutation_state"] not in {
                "MUTATION_NOT_STARTED",
                "VERIFIED",
            }:
                raise OperationRuntimeError(
                    "mutation-capable PASS requires no mutation or VERIFIED boundary"
                )
            execution = "SUCCEEDED"
        else:
            execution = (
                "RECOVERY_REQUIRED"
                if state["mutation_capable"]
                and state["mutation_state"] in _RECOVERY_BOUNDARY
                else "FAILED"
            )

        completed = _utc(self.clock())
        result = {
            "schema": RESULT_SCHEMA,
            "operation_id": oid,
            "operation": state["operation"],
            "source_commit": state["source_commit"],
            "outcome": outcome,
            "phase": phase,
            "mutation_state": state["mutation_state"],
            "execution_state": execution,
            "next_action": (
                "READ_ONLY_RECONCILE"
                if execution == "RECOVERY_REQUIRED"
                else ("NONE" if execution == "SUCCEEDED" else "STOP")
            ),
            "completed_at_utc": completed,
        }
        _write_new_private(
            self._result_path(oid),
            _canonical(result),
            "operation result",
        )
        state["execution_state"] = execution
        state["phase"] = phase
        state["updated_at_utc"] = completed
        self._write_state(state)
        return result

    def _latest_progress(self, operation_id: str) -> dict[str, Any] | None:
        path = self._progress_path(operation_id)
        if not path.exists() and not path.is_symlink():
            return None
        _private_file(path, "operation progress journal")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise OperationRuntimeError("operation progress journal is unreadable") from exc
        if not lines:
            return None
        try:
            value = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise OperationRuntimeError(
                "operation progress journal has invalid final record"
            ) from exc
        if not isinstance(value, dict) or value.get("schema") != "keelaryn.gate-progress.v1":
            raise OperationRuntimeError("operation progress journal schema mismatch")
        return value

    def status(self, operation_id: str = "latest") -> dict[str, Any]:
        oid = self.resolve_operation_id(operation_id)
        state = self._read_state(oid)
        progress = self._latest_progress(oid)

        reference = state["updated_at_utc"]
        if progress is not None:
            timestamp = progress.get("timestamp_utc")
            if isinstance(timestamp, str):
                reference = timestamp

        age = max(0, int(self.clock() - _epoch(reference, "progress timestamp")))
        observed = state["execution_state"]
        next_action = self._next_action(state)

        if (
            observed == "RUNNING"
            and age > state["timeout_seconds"]
        ):
            observed = "STALLED"
            next_action = (
                "READ_ONLY_RECONCILE"
                if state["mutation_capable"]
                and state["mutation_state"] in _RECOVERY_BOUNDARY
                else "CHECK_PROCESS"
            )

        return {
            "schema": "keelaryn.operation-runtime-status.v1",
            "operation_id": oid,
            "operation": state["operation"],
            "source_commit": state["source_commit"],
            "execution_state": state["execution_state"],
            "observed_state": observed,
            "mutation_state": state["mutation_state"],
            "phase": state["phase"],
            "last_progress_age_seconds": age,
            "timeout_seconds": state["timeout_seconds"],
            "next_action": next_action,
            "terminal": state["execution_state"] in _TERMINAL_EXECUTION,
        }

    def session(
        self,
        operation_id: str,
        *,
        heartbeat_seconds: float = 15.0,
        stream=None,
    ) -> "OperationSession":
        return OperationSession(
            self,
            self.resolve_operation_id(operation_id),
            heartbeat_seconds=heartbeat_seconds,
            stream=stream,
        )


class OperationSession:
    """Execution-side helper that couples durable state to GateProgressJournal."""

    def __init__(
        self,
        runtime: OperationRuntime,
        operation_id: str,
        *,
        heartbeat_seconds: float,
        stream=None,
    ) -> None:
        self.runtime = runtime
        self.operation_id = operation_id
        self.heartbeat_seconds = heartbeat_seconds
        self.stream = stream
        self.journal: GateProgressJournal | None = None

    def __enter__(self) -> "OperationSession":
        state = self.runtime.start(self.operation_id)
        self.journal = GateProgressJournal(
            self.runtime._progress_path(self.operation_id),
            operation=state["operation"],
            heartbeat_seconds=self.heartbeat_seconds,
            stream=self.stream,
        )
        return self

    def record(
        self,
        *,
        phase: str,
        event: str = "PROGRESS",
        mutation_state: str | None = None,
        **counters: object,
    ) -> dict[str, Any]:
        if self.journal is None:
            raise OperationRuntimeError("operation session is not active")
        state = self.runtime.update(
            self.operation_id,
            phase=phase,
            mutation_state=mutation_state,
        )
        update: dict[str, object] = {
            "phase": state["phase"],
            "event": event,
            "mutation_state": state["mutation_state"],
        }
        update.update(counters)
        return self.journal.record(update)

    def finish(self, outcome: str, *, phase: str = "COMPLETE") -> dict[str, Any]:
        if self.journal is None:
            raise OperationRuntimeError("operation session is not active")
        self.journal.finish(outcome, phase=phase)
        result = self.runtime.finish(
            self.operation_id,
            outcome=outcome,
            phase=phase,
        )
        self.journal = None
        return result

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.journal is None:
            return
        if exc_type is None:
            self.finish("PASS")
            return
        try:
            self.journal.finish("FAIL", phase="FAILED")
        finally:
            self.runtime.finish(
                self.operation_id,
                outcome="FAIL",
                phase="FAILED",
            )
            self.journal = None


__all__ = [
    "HANDOFF_SCHEMA",
    "OperationRuntime",
    "OperationRuntimeError",
    "OperationSession",
    "RESULT_SCHEMA",
    "STATE_SCHEMA",
]
