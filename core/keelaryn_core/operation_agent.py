from __future__ import annotations

import argparse
import fcntl
import json
import os
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
LOCK_NAME = "LOCK"
INBOX_NAME = "inbox"


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


class OperationAgent:
    """Serialized allowlisted local operation dispatcher.

    v1 deliberately has no network transport and no arbitrary command execution.
    A later unprivileged transport may place strict request files into the private
    inbox; this privileged dispatcher trusts only schema-validated allowlisted
    requests bound to its exact source commit.
    """

    def __init__(
        self,
        operation_root: str | Path,
        control_root: str | Path,
        *,
        source_commit: str,
        handlers: dict[str, OperationHandler] | None = None,
    ) -> None:
        self.runtime = OperationRuntime(operation_root)
        self.control_root = _private_dir(
            Path(control_root),
            "operation control root",
            create=True,
        )
        self.inbox = _private_dir(
            self.control_root / INBOX_NAME,
            "operation inbox",
            create=True,
        )
        self.lock_path = _private_lock(self.control_root / LOCK_NAME)
        self.source_commit = source_commit
        if (
            len(source_commit) != 40
            or any(ch not in "0123456789abcdef" for ch in source_commit)
        ):
            raise OperationRuntimeError("operation agent source_commit is invalid")
        self.handlers = dict(HANDLERS if handlers is None else handlers)

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

    def process(self, request_path: str | Path) -> dict[str, object]:
        request_path = Path(request_path).absolute()
        if request_path.parent != self.inbox:
            raise OperationRuntimeError(
                "operation request must be directly inside the private inbox"
            )
        if request_path.name != request_path.stem + ".json":
            raise OperationRuntimeError("operation request filename is invalid")

        with self.locked():
            request = read_operation_request(request_path)
            if request_path.stem != request.request_id:
                raise OperationRuntimeError(
                    "operation request filename does not match request_id"
                )
            handler = self._validate_request(request)

            operation_dir = self.runtime._directory(request.request_id)
            if operation_dir.exists() or operation_dir.is_symlink():
                status = self.runtime.status(request.request_id)
                return {
                    "schema": AGENT_SCHEMA,
                    "request_id": request.request_id,
                    "disposition": "EXISTING",
                    "status": status,
                }

            self.runtime.create(
                operation=request.operation,
                source_commit=request.source_commit,
                mutation_capable=request.mutation_capable,
                timeout_seconds=request.timeout_seconds,
                operation_id=request.request_id,
            )

            try:
                with self.runtime.session(
                    request.request_id,
                    heartbeat_seconds=15.0,
                ) as session:
                    handler.callback(session, request)
            except Exception:
                status = self.runtime.status(request.request_id)
                return {
                    "schema": AGENT_SCHEMA,
                    "request_id": request.request_id,
                    "disposition": "FAILED",
                    "status": status,
                }

            return {
                "schema": AGENT_SCHEMA,
                "request_id": request.request_id,
                "disposition": "COMPLETED",
                "status": self.runtime.status(request.request_id),
            }

    def process_pending_once(self) -> dict[str, object] | None:
        requests = sorted(
            path
            for path in self.inbox.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix == ".json"
        )
        if not requests:
            return None
        return self.process(requests[0])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-agent")
    parser.add_argument("--operation-root", required=True, type=Path)
    parser.add_argument("--control-root", required=True, type=Path)
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
