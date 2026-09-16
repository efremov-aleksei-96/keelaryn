from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Mapping


class DriveProcessLockError(RuntimeError):
    """Local VPS single-writer lock cannot be acquired safely."""


class DriveProcessLock:
    """Crash-released local single-writer lock for one Drive Hub.

    The Drive protocol remains fail-closed if multiple hosts are misconfigured,
    but the MVP VPS deployment intentionally has one writer process. This lock
    prevents two local bootstrap/once/serve processes from racing through
    pre-activation preparation.
    """

    def __init__(self, hub_root_id: str, *, env: Mapping[str, str] | None = None) -> None:
        if os.name != "posix":
            raise DriveProcessLockError("Drive VPS process locking requires a POSIX runtime")
        if not isinstance(hub_root_id, str) or not hub_root_id or hub_root_id != hub_root_id.strip():
            raise DriveProcessLockError("hub_root_id must be a non-empty trimmed string")
        source = os.environ if env is None else env
        configured = source.get("KEELARYN_RUNTIME_DIR")
        if configured:
            root = Path(configured)
            if not root.is_absolute():
                raise DriveProcessLockError("KEELARYN_RUNTIME_DIR must be absolute")
            self.runtime_dir = root
        else:
            xdg = source.get("XDG_RUNTIME_DIR")
            if xdg:
                base = Path(xdg)
                if not base.is_absolute():
                    raise DriveProcessLockError("XDG_RUNTIME_DIR must be absolute")
                self.runtime_dir = base / "keelaryn"
            else:
                self.runtime_dir = Path("/tmp") / f"keelaryn-{os.getuid()}"
        digest = hashlib.sha256(hub_root_id.encode("utf-8")).hexdigest()[:24]
        self.path = self.runtime_dir / f"drive-{digest}.lock"
        self._fd: int | None = None

    @staticmethod
    def _require_private_dir(path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as exc:
                raise DriveProcessLockError("cannot create Keelaryn runtime directory") from exc
            try:
                info = path.lstat()
            except OSError as exc:
                raise DriveProcessLockError("cannot inspect Keelaryn runtime directory") from exc
        except OSError as exc:
            raise DriveProcessLockError("cannot inspect Keelaryn runtime directory") from exc

        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise DriveProcessLockError("Keelaryn runtime path is not a real directory")
        if info.st_uid != os.getuid():
            raise DriveProcessLockError("Keelaryn runtime directory is not owned by the current user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise DriveProcessLockError("Keelaryn runtime directory permissions are too broad")

    def acquire(self) -> "DriveProcessLock":
        if self._fd is not None:
            raise DriveProcessLockError("Drive process lock is already held by this object")
        self._require_private_dir(self.runtime_dir)

        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - POSIX CI provides fcntl.
            raise DriveProcessLockError("POSIX flock support is unavailable") from exc

        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise DriveProcessLockError("cannot open Keelaryn Drive lock file safely") from exc

        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise DriveProcessLockError("Keelaryn Drive lock path is not a regular file")
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise DriveProcessLockError("Keelaryn Drive lock file ownership/permissions are unsafe")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DriveProcessLockError("another Keelaryn Drive poller already owns this Hub locally") from exc
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
            self._fd = fd
            return self
        except Exception:
            os.close(fd)
            raise

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "DriveProcessLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


__all__ = ["DriveProcessLock", "DriveProcessLockError"]
