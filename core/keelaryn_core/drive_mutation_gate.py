from __future__ import annotations

import json
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


MUTATION_GATE_ROOT_ENV = "KEELARYN_MUTATION_GATE_ROOT"
LOCK_NAME = "LOCK"
INHIBIT_NAME = "INHIBIT.json"
INHIBIT_SCHEMA = "keelaryn.drive-mutation-inhibit.v1"
INHIBIT_KEYS = {
    "schema",
    "transaction_id",
    "active_transaction_sha256",
    "source_commit",
    "tool_sha256",
    "old_selector_sha256",
    "new_selector_sha256",
}


class DriveMutationGateError(RuntimeError):
    """A local production Drive mutation gate cannot be acquired safely."""


def _hex(value: Any, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise DriveMutationGateError(f"{label} is invalid")
    return value


def _trusted_owner(uid: int) -> bool:
    return uid in {0, os.geteuid()}


def _gate_root(path: Path) -> Path:
    path = path.absolute()
    try:
        info = path.lstat()
    except OSError as exc:
        raise DriveMutationGateError("cannot inspect Drive mutation gate root") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise DriveMutationGateError("Drive mutation gate root must be a real directory")
    if not _trusted_owner(info.st_uid):
        raise DriveMutationGateError("Drive mutation gate root has untrusted owner")
    if stat.S_IMODE(info.st_mode) != 0o2750:
        raise DriveMutationGateError("Drive mutation gate root must have mode 2750")
    return path


def _regular(path: Path, label: str, mode: int) -> Path:
    path = path.absolute()
    try:
        info = path.lstat()
    except OSError as exc:
        raise DriveMutationGateError(f"cannot inspect {label}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise DriveMutationGateError(f"{label} must be a regular file")
    if not _trusted_owner(info.st_uid) or stat.S_IMODE(info.st_mode) != mode:
        raise DriveMutationGateError(
            f"{label} must have trusted owner and mode {mode:04o}"
        )
    return path


def _open_lock(root: Path, *, write: bool) -> int:
    root = _gate_root(root)
    flags = os.O_RDWR if write else os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(root / LOCK_NAME, flags)
    except OSError as exc:
        raise DriveMutationGateError(
            "cannot open Drive mutation gate lock without following symlinks"
        ) from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or not _trusted_owner(info.st_uid)
            or stat.S_IMODE(info.st_mode) != 0o640
        ):
            raise DriveMutationGateError(
                "Drive mutation gate lock must have trusted owner and mode 0640"
            )
        return fd
    except Exception:
        os.close(fd)
        raise


def parse_mutation_inhibit(raw: bytes) -> dict[str, str]:
    try:
        value = strict_json_bytes(raw, label="DRIVE_MUTATION_INHIBIT")
    except ProtocolError as exc:
        raise DriveMutationGateError(str(exc)) from exc
    if (
        not isinstance(value, dict)
        or set(value) != INHIBIT_KEYS
        or value.get("schema") != INHIBIT_SCHEMA
    ):
        raise DriveMutationGateError("Drive mutation inhibit has invalid keys/schema")
    _hex(value["transaction_id"], 32, "mutation inhibit transaction_id")
    _hex(
        value["active_transaction_sha256"],
        64,
        "mutation inhibit active_transaction_sha256",
    )
    _hex(value["source_commit"], 40, "mutation inhibit source_commit")
    _hex(value["tool_sha256"], 64, "mutation inhibit tool_sha256")
    _hex(value["old_selector_sha256"], 64, "mutation inhibit old_selector_sha256")
    _hex(value["new_selector_sha256"], 64, "mutation inhibit new_selector_sha256")
    if raw != canonical_json_bytes(value):
        raise DriveMutationGateError("Drive mutation inhibit is not canonical JSON bytes")
    return dict(value)


def mutation_inhibit_bytes(value: Mapping[str, Any]) -> bytes:
    raw = canonical_json_bytes(dict(value))
    parse_mutation_inhibit(raw)
    return raw


def read_mutation_inhibit(root: Path) -> dict[str, str] | None:
    root = _gate_root(root)
    path = root / INHIBIT_NAME
    if not path.exists() and not path.is_symlink():
        return None
    _regular(path, "Drive mutation inhibit", 0o640)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DriveMutationGateError("cannot read Drive mutation inhibit") from exc
    return parse_mutation_inhibit(raw)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_create(root: Path, raw: bytes) -> None:
    path = root / INHIBIT_NAME
    if path.exists() or path.is_symlink():
        _regular(path, "Drive mutation inhibit", 0o640)
        if path.read_bytes() != raw:
            raise DriveMutationGateError(
                "existing Drive mutation inhibit has different identity"
            )
        return
    temp = root / f".{INHIBIT_NAME}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        try:
            os.fchmod(fd, 0o640)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        try:
            os.link(temp, path)
        except FileExistsError:
            _regular(path, "Drive mutation inhibit", 0o640)
            if path.read_bytes() != raw:
                raise DriveMutationGateError(
                    "Drive mutation inhibit raced with different identity"
                )
        _regular(path, "Drive mutation inhibit", 0o640)
        _fsync_dir(root)
    finally:
        temp.unlink(missing_ok=True)


class DriveMutationGate:
    """Shared lock held for the full lifetime of one production Drive mutation."""

    def __init__(self, root: Path):
        if os.name != "posix":
            raise DriveMutationGateError("Drive mutation gate requires a POSIX runtime")
        self.root = _gate_root(root)
        self._fd: int | None = None

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "DriveMutationGate":
        source = os.environ if env is None else env
        raw = source.get(MUTATION_GATE_ROOT_ENV, "")
        if not raw:
            raise DriveMutationGateError(
                f"{MUTATION_GATE_ROOT_ENV} is required for Drive mutation"
            )
        root = Path(raw)
        if not root.is_absolute():
            raise DriveMutationGateError(
                f"{MUTATION_GATE_ROOT_ENV} must be an absolute path"
            )
        return cls(root)

    def acquire(self) -> "DriveMutationGate":
        if self._fd is not None:
            raise DriveMutationGateError("Drive mutation gate is already held")
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover
            raise DriveMutationGateError("POSIX flock support is unavailable") from exc
        fd = _open_lock(self.root, write=False)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DriveMutationGateError(
                    "Drive mutation gate is exclusively held for production cutover"
                ) from exc
            if read_mutation_inhibit(self.root) is not None:
                raise DriveMutationGateError(
                    "Drive mutations are inhibited by an active production cutover"
                )
            self._fd = fd
            return self
        except Exception:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
            raise

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "DriveMutationGate":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class DriveMutationGateAdmin:
    """Exclusive administrative side used by the Hub cutover transaction."""

    def __init__(self, root: Path):
        if os.name != "posix":
            raise DriveMutationGateError("Drive mutation gate requires a POSIX runtime")
        self.root = _gate_root(root)

    @contextmanager
    def locked(self) -> Iterator[None]:
        import fcntl

        fd = _open_lock(self.root, write=True)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DriveMutationGateError(
                    "an active Drive mutation still holds the production mutation gate"
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def read(self) -> dict[str, str] | None:
        return read_mutation_inhibit(self.root)

    def publish(self, value: Mapping[str, Any]) -> dict[str, str]:
        raw = mutation_inhibit_bytes(value)
        _atomic_create(self.root, raw)
        return parse_mutation_inhibit(raw)

    def clear(self, expected: Mapping[str, Any]) -> None:
        raw = mutation_inhibit_bytes(expected)
        path = self.root / INHIBIT_NAME
        _regular(path, "Drive mutation inhibit", 0o640)
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise DriveMutationGateError("cannot read Drive mutation inhibit") from exc
        if current != raw:
            raise DriveMutationGateError(
                "Drive mutation inhibit changed before release"
            )
        path.unlink()
        _fsync_dir(self.root)


__all__ = [
    "DriveMutationGate",
    "DriveMutationGateAdmin",
    "DriveMutationGateError",
    "INHIBIT_NAME",
    "INHIBIT_SCHEMA",
    "LOCK_NAME",
    "MUTATION_GATE_ROOT_ENV",
    "mutation_inhibit_bytes",
    "parse_mutation_inhibit",
    "read_mutation_inhibit",
]
