from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .operation_request import OperationRequest, read_operation_request
from .operation_runtime import OperationRuntime, OperationRuntimeError, OperationSession


AGENT_SCHEMA = "keelaryn.operation-agent.v1"
RELAY_SCHEMA = "keelaryn.operation-relay-status.v1"

RELAY_ROOT_MODE = 0o750
RELAY_DIRECTORY_MODE = 0o770
RELAY_FILE_MODE = 0o640
LOCK_NAME = "LOCK"
PROCESSED_NAME = "processed"
REJECTED_NAME = "rejected"
_REQUEST_FILE = re.compile(r"^[0-9a-f]{32}\.json$")


@dataclass(frozen=True)
class OperationHandler:
    mutation_capable: bool
    requires_approval: bool
    callback: Callable[[OperationSession, OperationRequest], None]


def _runtime_selftest(session: OperationSession, request: OperationRequest) -> None:
    if request.profile != "DEFAULT":
        raise OperationRuntimeError("RUNTIME_SELFTEST requires DEFAULT profile")
    session.record(phase="SELFTEST", event="PHASE_BEGIN")
    session.record(phase="SELFTEST", event="PHASE_COMPLETE")


HANDLERS: dict[str, OperationHandler] = {
    "RUNTIME_SELFTEST": OperationHandler(
        mutation_capable=False,
        requires_approval=False,
        callback=_runtime_selftest,
    ),
}


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



def _relay_dir(path: Path, label: str, *, mode: int) -> Path:
    path = path.absolute()
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationRuntimeError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise OperationRuntimeError(f"{label} must be one real directory")
    if os.name == "posix":
        if info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != mode:
            raise OperationRuntimeError(
                f"{label} group/mode is not exact {mode:04o}"
            )
    return path

def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_lock(path: Path) -> Path:
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationRuntimeError("operation agent lock cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise OperationRuntimeError("operation agent lock must be one regular file")
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OperationRuntimeError(
                "operation agent lock must be owner-controlled mode 0600"
            )
    return path


def _atomic_relay(path: Path, value: dict[str, object]) -> None:
    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, RELAY_FILE_MODE)
        try:
            os.fchmod(fd, RELAY_FILE_MODE)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temp.unlink(missing_ok=True)


def _materialized_source_commit() -> str:
    release = Path(__file__).resolve().parents[2]
    source = release / "SOURCE_COMMIT"
    if source.is_symlink() or not source.is_file():
        raise OperationRuntimeError(
            "operation agent must run from a materialized release or receive --source-commit"
        )
    try:
        value = source.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise OperationRuntimeError("materialized SOURCE_COMMIT is unreadable") from exc
    if (
        len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise OperationRuntimeError("materialized SOURCE_COMMIT is invalid")
    return value


class RelayProgressStream:
    def __init__(self, outbox: Path, operation_id: str, source_commit: str) -> None:
        self.outbox = outbox
        self.operation_id = operation_id
        self.source_commit = source_commit
        self.buffer = ""

    def write(self, data: str) -> int:
        self.buffer += data
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if not line.startswith("GATE_PROGRESS "):
                continue
            try:
                value = json.loads(line[len("GATE_PROGRESS "):])
                if value.get("schema") != "keelaryn.gate-progress.v1":
                    continue
                relay = {
                    "schema": RELAY_SCHEMA,
                    "operation_id": self.operation_id,
                    "operation": value["operation"],
                    "source_commit": self.source_commit,
                    "execution_state": "RUNNING",
                    "observed_state": "RUNNING",
                    "mutation_state": value["mutation_state"],
                    "phase": value["phase"],
                    "event": value["event"],
                    "sequence": value["sequence"],
                    "timestamp_utc": value["timestamp_utc"],
                    "next_action": "WAIT",
                    "terminal": False,
                    "outcome": None,
                }
                _atomic_relay(self.outbox / f"{self.operation_id}.json", relay)
            except Exception:
                pass
        return len(data)

    def flush(self) -> None:
        return None


class OperationAgent:
    """Serialized allowlisted dispatcher with a non-authoritative relay boundary."""

    def __init__(
        self,
        operation_root: str | Path,
        control_root: str | Path,
        transport_root: str | Path,
        *,
        source_commit: str,
        handlers: dict[str, OperationHandler] | None = None,
    ) -> None:
        self.runtime = OperationRuntime(operation_root)
        self.control_root = _private_dir(Path(control_root), "operation control root", create=True)
        self.processed = _private_dir(
            self.control_root / PROCESSED_NAME,
            "processed operation request archive",
            create=True,
        )
        self.rejected = _private_dir(
            self.control_root / REJECTED_NAME,
            "rejected operation request archive",
            create=True,
        )
        self.transport_root = Path(transport_root).absolute()
        self.inbox = self.transport_root / "inbox"
        self.outbox = self.transport_root / "outbox"
        self.lock_path = _private_lock(self.control_root / LOCK_NAME)
        self.source_commit = source_commit
        if (
            len(source_commit) != 40
            or any(ch not in "0123456789abcdef" for ch in source_commit)
        ):
            raise OperationRuntimeError("operation agent source_commit is invalid")
        self.handlers = dict(HANDLERS if handlers is None else handlers)

    def _relay_ready(self) -> bool:
        for path, label, mode in (
            (self.transport_root, "operation transport root", RELAY_ROOT_MODE),
            (self.inbox, "operation transport inbox", RELAY_DIRECTORY_MODE),
            (self.outbox, "operation transport outbox", RELAY_DIRECTORY_MODE),
        ):
            if not path.exists() and not path.is_symlink():
                return False
            _relay_dir(path, label, mode=mode)
        return True

    @contextmanager
    def locked(self) -> Iterator[None]:
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.lock_path, flags)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise OperationRuntimeError(
                    "another operation agent process holds the control lock"
                ) from exc
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _validate_request(self, request: OperationRequest) -> OperationHandler:
        if request.source_commit != self.source_commit:
            raise OperationRuntimeError(
                "operation request source_commit does not match exact agent release"
            )
        handler = self.handlers.get(request.operation)
        if handler is None:
            raise OperationRuntimeError("operation request is not allowlisted")
        if request.mutation_capable is not handler.mutation_capable:
            raise OperationRuntimeError(
                "operation request mutation capability disagrees with allowlist"
            )
        if handler.requires_approval:
            if request.approval != "REQUIRED":
                raise OperationRuntimeError(
                    "operation request approval policy disagrees with allowlist"
                )
            raise OperationRuntimeError(
                "approved mutation receipt verification is not implemented"
            )
        if request.approval != "NOT_REQUIRED":
            raise OperationRuntimeError(
                "read-only operation must not claim production approval"
            )
        return handler

    def _publish_final(self, request_id: str, *, outcome: str | None = None) -> None:
        status = self.runtime.status(request_id)
        relay = {
            "schema": RELAY_SCHEMA,
            "operation_id": status["operation_id"],
            "operation": status["operation"],
            "source_commit": status["source_commit"],
            "execution_state": status["execution_state"],
            "observed_state": status["observed_state"],
            "mutation_state": status["mutation_state"],
            "phase": status["phase"],
            "event": "TERMINAL" if status["terminal"] else "STATUS",
            "sequence": 0,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "next_action": status["next_action"],
            "terminal": status["terminal"],
            "outcome": outcome,
        }
        _atomic_relay(self.outbox / f"{request_id}.json", relay)

    def process(self, request_path: str | Path) -> dict[str, object]:
        if not self._relay_ready():
            raise OperationRuntimeError("operation transport relay is unavailable")
        request_path = Path(request_path).absolute()
        if request_path.parent != self.inbox:
            raise OperationRuntimeError(
                "operation request must be directly inside the transport inbox"
            )
        if _REQUEST_FILE.fullmatch(request_path.name) is None:
            raise OperationRuntimeError("operation request filename is invalid")

        with self.locked():
            request = read_operation_request(
                request_path,
                expected_mode=RELAY_FILE_MODE,
            )
            if request_path.stem != request.request_id:
                raise OperationRuntimeError(
                    "operation request filename does not match request_id"
                )
            handler = self._validate_request(request)

            operation_dir = self.runtime._directory(request.request_id)
            processed = self.processed / request_path.name
            if (
                (operation_dir.exists() or operation_dir.is_symlink())
                and not (processed.exists() or processed.is_symlink())
                and self.runtime.recover_initialization(request.request_id)
            ):
                operation_dir = self.runtime._directory(request.request_id)

            if operation_dir.exists() or operation_dir.is_symlink():
                if processed.exists() or processed.is_symlink():
                    if (
                        processed.is_symlink()
                        or not processed.is_file()
                        or processed.read_bytes() != request_path.read_bytes()
                    ):
                        raise OperationRuntimeError(
                            "request_id conflicts with processed request identity"
                        )

                result = self.runtime.recover_terminal(request.request_id)
                status = self.runtime.status(request.request_id)
                if not status["terminal"]:
                    result = self.runtime.interrupt(request.request_id)
                    status = self.runtime.status(request.request_id)
                    disposition = "INTERRUPTED"
                else:
                    disposition = "EXISTING"

                self._publish_final(
                    request.request_id,
                    outcome=None if result is None else str(result["outcome"]),
                )
                return {
                    "schema": AGENT_SCHEMA,
                    "request_id": request.request_id,
                    "disposition": disposition,
                    "status": status,
                }

            self.runtime.create(
                operation=request.operation,
                source_commit=request.source_commit,
                mutation_capable=request.mutation_capable,
                timeout_seconds=request.timeout_seconds,
                operation_id=request.request_id,
            )

            relay = RelayProgressStream(self.outbox, request.request_id, self.source_commit)
            try:
                with self.runtime.session(
                    request.request_id,
                    heartbeat_seconds=15.0,
                    stream=relay,
                ) as session:
                    handler.callback(session, request)
            except Exception:
                result = self.runtime.recover_terminal(request.request_id)
                status = self.runtime.status(request.request_id)
                if not status["terminal"]:
                    result = self.runtime.interrupt(request.request_id)
                    status = self.runtime.status(request.request_id)
                self._publish_final(
                    request.request_id,
                    outcome=None if result is None else str(result["outcome"]),
                )
                return {
                    "schema": AGENT_SCHEMA,
                    "request_id": request.request_id,
                    "disposition": "FAILED",
                    "status": status,
                }

            status = self.runtime.status(request.request_id)
            self._publish_final(request.request_id, outcome="PASS")
            return {
                "schema": AGENT_SCHEMA,
                "request_id": request.request_id,
                "disposition": "COMPLETED",
                "status": status,
            }

    def _archive(
        self,
        request_path: Path,
        destination: Path,
        *,
        conflict_suffix: bool = False,
    ) -> None:
        raw = request_path.read_bytes()
        target = destination / request_path.name
        if target.exists() or target.is_symlink():
            if not target.is_symlink() and target.is_file() and target.read_bytes() == raw:
                request_path.unlink()
                _fsync_dir(request_path.parent)
                return
            if not conflict_suffix:
                raise OperationRuntimeError(
                    "operation request archive conflicts with existing identity"
                )
            digest = hashlib.sha256(raw).hexdigest()[:16]
            target = destination / f"{request_path.stem}-{digest}.json"
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file() or target.read_bytes() != raw:
                    raise OperationRuntimeError(
                        "rejected operation request archive conflicts with existing identity"
                    )
                request_path.unlink()
                _fsync_dir(request_path.parent)
                return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(target, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        _fsync_dir(destination)
        request_path.unlink()
        _fsync_dir(request_path.parent)

    def process_pending_once(self) -> dict[str, object] | None:
        if not self._relay_ready():
            return None
        requests = sorted(
            path
            for path in self.inbox.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and _REQUEST_FILE.fullmatch(path.name)
        )
        if not requests:
            return None

        request_path = requests[0]
        try:
            result = self.process(request_path)
        except (OperationRuntimeError, OSError):
            self._archive(
                request_path,
                self.rejected,
                conflict_suffix=True,
            )
            return {
                "schema": AGENT_SCHEMA,
                "disposition": "REJECTED",
            }

        self._archive(request_path, self.processed)
        return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-agent")
    parser.add_argument("--operation-root", required=True, type=Path)
    parser.add_argument("--control-root", required=True, type=Path)
    parser.add_argument("--transport-root", required=True, type=Path)
    parser.add_argument("--source-commit")
    sub = parser.add_subparsers(dest="command", required=True)

    process = sub.add_parser("process")
    process.add_argument("--request", required=True, type=Path)

    serve = sub.add_parser("serve")
    serve.add_argument("--poll-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source_commit = args.source_commit or _materialized_source_commit()
        agent = OperationAgent(
            args.operation_root,
            args.control_root,
            args.transport_root,
            source_commit=source_commit,
        )

        if args.command == "process":
            print(
                json.dumps(
                    agent.process(args.request),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0

        if args.poll_seconds <= 0:
            raise OperationRuntimeError("poll-seconds must be positive")

        while True:
            result = agent.process_pending_once()
            if result is not None:
                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
            time.sleep(args.poll_seconds)
    except (OperationRuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
