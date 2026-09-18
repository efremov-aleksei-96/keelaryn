from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from materialize_payload import PayloadMaterializeError, verify_release_directory

SCHEMA = "keelaryn.zero-vps-release-switch.v1"
TERMINAL_SCHEMA = "keelaryn.zero-vps-release-switch-terminal.v1"
ACTIVE_NAME = "ACTIVE_TRANSACTION.json"
LOCK_NAME = "LOCK"
TOOL_RELATIVE = Path("deploy/zero-based-vps/release_switch.py")


class ReleaseSwitchError(RuntimeError):
    pass


FaultHook = Callable[[str], None]


def _fault(hook: FaultHook | None, point: str) -> None:
    if hook is not None:
        hook(point)


def _commit(value: Any, label: str = "commit") -> str:
    if not isinstance(value, str) or len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise ReleaseSwitchError(f"invalid {label}")
    return value


def _sha256(value: Any, label: str = "sha256") -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ReleaseSwitchError(f"invalid {label}")
    return value


def _strict_json(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseSwitchError(f"{label} is not UTF-8") from exc

    def hook(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseSwitchError(f"{label} contains duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        raise ReleaseSwitchError(f"{label} is invalid JSON") from exc


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _real_dir(path: Path, label: str) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_dir():
        raise ReleaseSwitchError(f"{label} must be a real directory")
    return path


def _private_dir(path: Path, label: str, *, create: bool = False) -> Path:
    path = path.absolute()
    if create and not path.exists():
        path.mkdir(parents=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ReleaseSwitchError(f"{label} must be a real directory")
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReleaseSwitchError(f"cannot stat {label}") from exc
    if info.st_uid != os.geteuid():
        raise ReleaseSwitchError(f"{label} must be owned by the current effective user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ReleaseSwitchError(f"{label} must have mode 0700")
    return path


def _private_regular_file(path: Path, label: str) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise ReleaseSwitchError(f"{label} must be a regular file")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ReleaseSwitchError(f"{label} must be owner-controlled mode 0600")
    return path


def _atomic_create(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        _private_regular_file(path, f"immutable file {path.name}")
        if path.read_bytes() != data:
            raise ReleaseSwitchError(f"immutable file already exists with different identity: {path.name}")
        return
    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        try:
            os.link(temp, path)
        except FileExistsError:
            _private_regular_file(path, f"immutable raced file {path.name}")
            if path.read_bytes() != data:
                raise ReleaseSwitchError(f"immutable file raced with different identity: {path.name}")
        _private_regular_file(path, f"immutable file {path.name}")
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_symlink(current: Path, target: str) -> None:
    temp = current.parent / f".{current.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        os.symlink(target, temp)
        os.replace(temp, current)
        _fsync_dir(current.parent)
    finally:
        temp.unlink(missing_ok=True)


def _release_path(install_root: Path, commit: str) -> Path:
    releases = install_root / "releases"
    if releases.is_symlink() or not releases.is_dir():
        raise ReleaseSwitchError("install releases directory is missing/not real")
    release = releases / _commit(commit)
    if release.is_symlink() or not release.is_dir():
        raise ReleaseSwitchError(f"release directory missing/not real: {commit}")
    return release


def _release_identity(install_root: Path, commit: str) -> dict[str, Any]:
    try:
        identity = verify_release_directory(_release_path(install_root, commit), expected_source_commit=commit)
    except PayloadMaterializeError as exc:
        raise ReleaseSwitchError(f"release verification failed for {commit}: {exc}") from exc
    required = {"schema", "source_commit", "payload_sha256", "payload_size", "file_count"}
    if set(identity) != required or identity["source_commit"] != commit:
        raise ReleaseSwitchError("release identity has unexpected shape")
    return identity


def _link(commit: str) -> str:
    return f"releases/{_commit(commit)}"


def _read_current(install_root: Path) -> str:
    current = install_root / "current"
    if not current.is_symlink():
        raise ReleaseSwitchError("current must be a symlink")
    try:
        return os.readlink(current)
    except OSError as exc:
        raise ReleaseSwitchError("cannot read current symlink") from exc


def _current_commit(install_root: Path) -> str:
    value = _read_current(install_root)
    if not value.startswith("releases/"):
        raise ReleaseSwitchError("current symlink is not in canonical releases/<commit> form")
    return _commit(value.removeprefix("releases/"), "current commit")


def _classify(install_root: Path, old_commit: str, new_commit: str) -> str:
    try:
        value = _read_current(install_root)
    except ReleaseSwitchError:
        return "UNKNOWN"
    if value == _link(old_commit):
        return "OLD"
    if value == _link(new_commit):
        return "NEW"
    return "UNKNOWN"


def _parse_record(raw: bytes) -> dict[str, Any]:
    value = _strict_json(raw, ACTIVE_NAME)
    if not isinstance(value, dict) or set(value) != {"schema", "transaction_id", "old", "new"} or value["schema"] != SCHEMA:
        raise ReleaseSwitchError("active transaction has invalid root/schema")
    txid = value["transaction_id"]
    if not isinstance(txid, str) or len(txid) != 32 or any(ch not in "0123456789abcdef" for ch in txid):
        raise ReleaseSwitchError("active transaction has invalid transaction_id")
    for side in ("old", "new"):
        item = value[side]
        if not isinstance(item, dict) or set(item) != {"source_commit", "payload_sha256", "payload_size", "file_count"}:
            raise ReleaseSwitchError(f"active transaction {side} identity invalid")
        _commit(item["source_commit"], f"{side} source_commit")
        _sha256(item["payload_sha256"], f"{side} payload_sha256")
        if not isinstance(item["payload_size"], int) or isinstance(item["payload_size"], bool) or item["payload_size"] < 0:
            raise ReleaseSwitchError(f"active transaction {side} payload_size invalid")
        if not isinstance(item["file_count"], int) or isinstance(item["file_count"], bool) or item["file_count"] < 1:
            raise ReleaseSwitchError(f"active transaction {side} file_count invalid")
    if value["old"]["source_commit"] == value["new"]["source_commit"]:
        raise ReleaseSwitchError("release switch cannot target the already-active commit")
    return value


def _terminal_bytes(record_raw: bytes, record: dict[str, Any], outcome: str) -> bytes:
    if outcome not in {"ACCEPTED", "ROLLED_BACK"}:
        raise ReleaseSwitchError("invalid terminal outcome")
    return _json({
        "schema": TERMINAL_SCHEMA,
        "transaction_id": record["transaction_id"],
        "active_transaction_sha256": hashlib.sha256(record_raw).hexdigest(),
        "outcome": outcome,
        "old_commit": record["old"]["source_commit"],
        "new_commit": record["new"]["source_commit"],
    })


def _parse_terminal(raw: bytes, record_raw: bytes, record: dict[str, Any]) -> dict[str, Any]:
    value = _strict_json(raw, "terminal marker")
    required = {"schema", "transaction_id", "active_transaction_sha256", "outcome", "old_commit", "new_commit"}
    if not isinstance(value, dict) or set(value) != required or value["schema"] != TERMINAL_SCHEMA:
        raise ReleaseSwitchError("terminal marker has invalid root/schema")
    if value["transaction_id"] != record["transaction_id"]:
        raise ReleaseSwitchError("terminal marker transaction mismatch")
    if value["active_transaction_sha256"] != hashlib.sha256(record_raw).hexdigest():
        raise ReleaseSwitchError("terminal marker does not bind exact active transaction")
    if value["old_commit"] != record["old"]["source_commit"] or value["new_commit"] != record["new"]["source_commit"]:
        raise ReleaseSwitchError("terminal marker release identity mismatch")
    if value["outcome"] not in {"ACCEPTED", "ROLLED_BACK"}:
        raise ReleaseSwitchError("terminal marker has invalid outcome")
    return value


class ReleaseSwitch:
    def __init__(
        self,
        install_root: Path,
        state_root: Path,
        *,
        fault_hook: FaultHook | None = None,
        executing_tool: Path | None = None,
    ):
        self.install_root = _real_dir(install_root, "install root")
        self.state_root = _private_dir(state_root, "deployment state root", create=True)
        self.fault_hook = fault_hook
        self.executing_tool = executing_tool
        self.active_path = self.state_root / ACTIVE_NAME
        self.terminal_root = self.state_root / "terminal"
        self.history_root = self.state_root / "history"
        self.terminal_root.mkdir(mode=0o700, exist_ok=True)
        self.history_root.mkdir(mode=0o700, exist_ok=True)
        self.terminal_root = _private_dir(self.terminal_root, "deployment terminal directory")
        self.history_root = _private_dir(self.history_root, "deployment history directory")
        _fsync_dir(self.state_root)

    @contextmanager
    def locked(self) -> Iterator[None]:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.state_root / LOCK_NAME, flags, 0o600)
        except OSError as exc:
            raise ReleaseSwitchError("cannot open deployment lock without following symlinks") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ReleaseSwitchError("deployment lock must be owner-controlled regular file mode 0600")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ReleaseSwitchError("another local release-switch process holds the deployment lock") from exc
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _load_active(self) -> tuple[bytes, dict[str, Any]]:
        try:
            _private_regular_file(self.active_path, "active release-switch transaction")
        except ReleaseSwitchError as exc:
            raise ReleaseSwitchError("no valid private active release-switch transaction") from exc
        try:
            raw = self.active_path.read_bytes()
        except OSError as exc:
            raise ReleaseSwitchError("cannot read active release-switch transaction") from exc
        return raw, _parse_record(raw)

    def _required_tool_commit_unlocked(self) -> str:
        if self.active_path.exists() or self.active_path.is_symlink():
            _, record = self._load_active()
            return record["old"]["source_commit"]
        return _current_commit(self.install_root)

    def _assert_tool_identity_unlocked(self) -> None:
        if self.executing_tool is None:
            return
        commit = self._required_tool_commit_unlocked()
        expected = _release_path(self.install_root, commit) / TOOL_RELATIVE
        if expected.is_symlink() or not expected.is_file():
            raise ReleaseSwitchError("required release-switch tool is missing/not regular")
        try:
            actual_resolved = self.executing_tool.resolve(strict=True)
            expected_resolved = expected.resolve(strict=True)
        except OSError as exc:
            raise ReleaseSwitchError("cannot resolve release-switch tool identity") from exc
        if actual_resolved != expected_resolved:
            raise ReleaseSwitchError(
                f"active deployment transaction must continue with release-switch tool from OLD commit {commit}"
            )

    def _terminal_path(self, txid: str) -> Path:
        return self.terminal_root / f"{txid}.json"

    def _history_path(self, txid: str) -> Path:
        return self.history_root / f"{txid}.json"

    def _load_terminal(self, record_raw: bytes, record: dict[str, Any]) -> dict[str, Any] | None:
        path = self._terminal_path(record["transaction_id"])
        if not path.exists() and not path.is_symlink():
            return None
        _private_regular_file(path, "deployment terminal marker")
        return _parse_terminal(path.read_bytes(), record_raw, record)

    def _verify_side(self, record: dict[str, Any], side: str) -> None:
        expected = record[side]
        identity = _release_identity(self.install_root, expected["source_commit"])
        for key in ("payload_sha256", "payload_size", "file_count"):
            if identity[key] != expected[key]:
                raise ReleaseSwitchError(f"{side} release identity changed after prepare: {key}")

    def _verify_both(self, record: dict[str, Any]) -> None:
        self._verify_side(record, "old")
        self._verify_side(record, "new")

    def prepare(self, new_commit: str) -> dict[str, Any]:
        new_commit = _commit(new_commit, "new commit")
        with self.locked():
            self._assert_tool_identity_unlocked()
            if self.active_path.exists() or self.active_path.is_symlink():
                raise ReleaseSwitchError("an active release-switch transaction already exists")
            old_commit = _current_commit(self.install_root)
            if old_commit == new_commit:
                raise ReleaseSwitchError("new commit is already active")
            old_identity = _release_identity(self.install_root, old_commit)
            new_identity = _release_identity(self.install_root, new_commit)
            record = {
                "schema": SCHEMA,
                "transaction_id": uuid.uuid4().hex,
                "old": {key: old_identity[key] for key in ("source_commit", "payload_sha256", "payload_size", "file_count")},
                "new": {key: new_identity[key] for key in ("source_commit", "payload_sha256", "payload_size", "file_count")},
            }
            raw = _json(record)
            if self._history_path(record["transaction_id"]).exists() or self._terminal_path(record["transaction_id"]).exists():
                raise ReleaseSwitchError("new transaction identity collides with existing durable state")
            _atomic_create(self.active_path, raw)
            _fault(self.fault_hook, "prepare.after_active_create")
            if _classify(self.install_root, old_commit, new_commit) != "OLD":
                raise ReleaseSwitchError("current changed while preparing deployment")
            return self.status_unlocked()

    def apply(self) -> dict[str, Any]:
        with self.locked():
            self._assert_tool_identity_unlocked()
            record_raw, record = self._load_active()
            terminal = self._load_terminal(record_raw, record)
            if terminal is not None:
                self._finalize(record_raw, record, terminal)
                return self.status_unlocked()
            self._verify_both(record)
            old_commit = record["old"]["source_commit"]
            new_commit = record["new"]["source_commit"]
            state = _classify(self.install_root, old_commit, new_commit)
            if state == "OLD":
                _atomic_symlink(self.install_root / "current", _link(new_commit))
                _fault(self.fault_hook, "apply.after_current_swap")
                state = _classify(self.install_root, old_commit, new_commit)
            if state != "NEW":
                raise ReleaseSwitchError("cannot apply release switch: current identity is UNKNOWN")
            self._verify_both(record)
            return self.status_unlocked()

    def accept(self) -> dict[str, Any]:
        with self.locked():
            self._assert_tool_identity_unlocked()
            record_raw, record = self._load_active()
            terminal = self._load_terminal(record_raw, record)
            if terminal is not None:
                if terminal["outcome"] != "ACCEPTED":
                    raise ReleaseSwitchError("transaction already has ROLLED_BACK terminal authority")
                self._finalize(record_raw, record, terminal)
                return self.status_unlocked()
            self._verify_both(record)
            if _classify(self.install_root, record["old"]["source_commit"], record["new"]["source_commit"]) != "NEW":
                raise ReleaseSwitchError("accept requires current to be exact NEW release")
            terminal_raw = _terminal_bytes(record_raw, record, "ACCEPTED")
            _atomic_create(self._terminal_path(record["transaction_id"]), terminal_raw)
            _fault(self.fault_hook, "accept.after_terminal_create")
            self._finalize(record_raw, record, _parse_terminal(terminal_raw, record_raw, record))
            return self.status_unlocked()

    def rollback(self) -> dict[str, Any]:
        with self.locked():
            self._assert_tool_identity_unlocked()
            record_raw, record = self._load_active()
            terminal = self._load_terminal(record_raw, record)
            if terminal is not None:
                if terminal["outcome"] != "ROLLED_BACK":
                    raise ReleaseSwitchError("transaction already has ACCEPTED terminal authority")
                self._finalize(record_raw, record, terminal)
                return self.status_unlocked()
            # NEW may be corrupt; that can be exactly why post-publication verification failed.
            # Rollback therefore requires the durable transaction plus exact OLD only.
            self._verify_side(record, "old")
            old_commit = record["old"]["source_commit"]
            new_commit = record["new"]["source_commit"]
            state = _classify(self.install_root, old_commit, new_commit)
            if state == "NEW":
                _atomic_symlink(self.install_root / "current", _link(old_commit))
                _fault(self.fault_hook, "rollback.after_current_swap")
                state = _classify(self.install_root, old_commit, new_commit)
            if state != "OLD":
                raise ReleaseSwitchError("cannot rollback release switch: current identity is UNKNOWN")
            self._verify_side(record, "old")
            terminal_raw = _terminal_bytes(record_raw, record, "ROLLED_BACK")
            _atomic_create(self._terminal_path(record["transaction_id"]), terminal_raw)
            _fault(self.fault_hook, "rollback.after_terminal_create")
            self._finalize(record_raw, record, _parse_terminal(terminal_raw, record_raw, record))
            return self.status_unlocked()

    def _finalize(self, record_raw: bytes, record: dict[str, Any], terminal: dict[str, Any]) -> None:
        expected = "NEW" if terminal["outcome"] == "ACCEPTED" else "OLD"
        if _classify(self.install_root, record["old"]["source_commit"], record["new"]["source_commit"]) != expected:
            raise ReleaseSwitchError("terminal authority conflicts with current symlink identity")
        history = self._history_path(record["transaction_id"])
        if history.exists() or history.is_symlink():
            _private_regular_file(history, "deployment history record")
            if history.read_bytes() != record_raw:
                raise ReleaseSwitchError("deployment history identity conflict")
            if self.active_path.exists() or self.active_path.is_symlink():
                _private_regular_file(self.active_path, "active release-switch transaction")
                if self.active_path.read_bytes() != record_raw:
                    raise ReleaseSwitchError("active/history deployment identity conflict")
                self.active_path.unlink()
                _fsync_dir(self.state_root)
            return
        if self.active_path.is_symlink() or not self.active_path.is_file() or self.active_path.read_bytes() != record_raw:
            raise ReleaseSwitchError("active transaction changed before finalization")
        os.replace(self.active_path, history)
        _fsync_dir(self.history_root)
        _fsync_dir(self.state_root)
        _fault(self.fault_hook, "finalize.after_active_archive")

    def status_unlocked(self) -> dict[str, Any]:
        if not self.active_path.exists() and not self.active_path.is_symlink():
            return {"status": "IDLE"}
        record_raw, record = self._load_active()
        terminal = self._load_terminal(record_raw, record)
        state = _classify(self.install_root, record["old"]["source_commit"], record["new"]["source_commit"])
        if terminal is not None:
            expected = "NEW" if terminal["outcome"] == "ACCEPTED" else "OLD"
            return {
                "status": "FINALIZE_PENDING" if state == expected else "BLOCKED",
                "transaction_id": record["transaction_id"],
                "current_state": state,
                "terminal": terminal["outcome"],
            }
        return {
            "status": {"OLD": "PREPARED", "NEW": "APPLIED", "UNKNOWN": "BLOCKED"}[state],
            "transaction_id": record["transaction_id"],
            "current_state": state,
            "old_commit": record["old"]["source_commit"],
            "new_commit": record["new"]["source_commit"],
        }

    def status(self) -> dict[str, Any]:
        with self.locked():
            self._assert_tool_identity_unlocked()
            return self.status_unlocked()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-zero-release-switch")
    parser.add_argument("--install-root", type=Path, default=Path("/opt/keelaryn"))
    parser.add_argument("--state-root", type=Path, default=Path("/var/lib/keelaryn/deployment"))
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--new-commit", required=True)
    sub.add_parser("apply")
    sub.add_parser("accept")
    sub.add_parser("rollback")
    sub.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        switch = ReleaseSwitch(
            args.install_root,
            args.state_root,
            executing_tool=Path(__file__),
        )
        result = (
            switch.prepare(args.new_commit)
            if args.command == "prepare"
            else switch.apply()
            if args.command == "apply"
            else switch.accept()
            if args.command == "accept"
            else switch.rollback()
            if args.command == "rollback"
            else switch.status()
        )
    except (ReleaseSwitchError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
