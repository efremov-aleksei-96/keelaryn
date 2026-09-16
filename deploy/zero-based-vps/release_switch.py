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


class ReleaseSwitchError(RuntimeError):
    pass


FaultHook = Callable[[str], None]


def _fault(hook: FaultHook | None, point: str) -> None:
    if hook is not None:
        hook(point)


def _commit(value: Any, label: str = "commit") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReleaseSwitchError(f"invalid {label}")
    return value


def _sha256(value: Any, label: str = "sha256") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReleaseSwitchError(f"invalid {label}")
    return value


def _strict_json(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseSwitchError(f"{label} is not UTF-8") from exc

    def pairs_hook(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseSwitchError(f"{label} contains duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=pairs_hook)
    except json.JSONDecodeError as exc:
        raise ReleaseSwitchError(f"{label} is invalid JSON") from exc


def _canonical_json(value: Any) -> bytes:
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


def _real_dir(path: Path, label: str, *, create: bool = False, mode: int = 0o700) -> Path:
    path = path.absolute()
    if create and not path.exists():
        path.mkdir(parents=True, mode=mode)
    if path.is_symlink() or not path.is_dir():
        raise ReleaseSwitchError(f"{label} must be a real directory")
    return path


def _atomic_create(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise ReleaseSwitchError(f"cannot read existing immutable file: {path.name}") from exc
        if existing == data:
            return
        raise ReleaseSwitchError(f"immutable file already exists with different bytes: {path.name}")

    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            existing = path.read_bytes()
            if existing != data:
                raise ReleaseSwitchError(f"immutable file raced with different bytes: {path.name}")
        _fsync_dir(path.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _atomic_symlink(current: Path, target: str) -> None:
    temp = current.parent / f".{current.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        os.symlink(target, temp)
        os.replace(temp, current)
        _fsync_dir(current.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _identity(release: Path, commit: str) -> dict[str, Any]:
    try:
        identity = verify_release_directory(release, expected_source_commit=commit)
    except PayloadMaterializeError as exc:
        raise ReleaseSwitchError(f"release verification failed for {commit}: {exc}") from exc
    required = {"schema", "source_commit", "payload_sha256", "payload_size", "file_count"}
    if set(identity) != required or identity["source_commit"] != commit:
        raise ReleaseSwitchError("release identity has unexpected shape")
    return identity


def _release_path(install_root: Path, commit: str) -> Path:
    releases = install_root / "releases"
    if releases.is_symlink() or not releases.is_dir():
        raise ReleaseSwitchError("install releases directory is missing/not real")
    release = releases / commit
    if release.is_symlink() or not release.is_dir():
        raise ReleaseSwitchError(f"release directory missing/not real: {commit}")
    return release


def _expected_link(commit: str) -> str:
    return f"releases/{_commit(commit)}"


def _read_current_link(install_root: Path) -> str:
    current = install_root / "current"
    if not current.is_symlink():
        raise ReleaseSwitchError("current must be a symlink")
    try:
        value = os.readlink(current)
    except OSError as exc:
        raise ReleaseSwitchError("cannot read current symlink") from exc
    return value


def _classify_current(install_root: Path, old_commit: str, new_commit: str) -> str:
    try:
        value = _read_current_link(install_root)
    except ReleaseSwitchError:
        return "UNKNOWN"
    if value == _expected_link(old_commit):
        return "OLD"
    if value == _expected_link(new_commit):
        return "NEW"
    return "UNKNOWN"


def _record_bytes(record: dict[str, Any]) -> bytes:
    return _canonical_json(record)


def _parse_record(raw: bytes) -> dict[str, Any]:
    value = _strict_json(raw, ACTIVE_NAME)
    required = {"schema", "transaction_id", "old", "new"}
    if not isinstance(value, dict) or set(value) != required or value["schema"] != SCHEMA:
        raise ReleaseSwitchError("active transaction has invalid root/schema")
    txid = value["transaction_id"]
    if not isinstance(txid, str) or len(txid) != 32 or any(ch not in "0123456789abcdef" for ch in txid):
        raise ReleaseSwitchError("active transaction has invalid transaction_id")
    for side in ("old", "new"):
        item = value[side]
        required_identity = {"source_commit", "payload_sha256", "payload_size", "file_count"}
        if not isinstance(item, dict) or set(item) != required_identity:
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
    return _canonical_json(
        {
            "schema": TERMINAL_SCHEMA,
            "transaction_id": record["transaction_id"],
            "active_transaction_sha256": hashlib.sha256(record_raw).hexdigest(),
            "outcome": outcome,
            "old_commit": record["old"]["source_commit"],
            "new_commit": record["new"]["source_commit"],
        }
    )


def _parse_terminal(raw: bytes, record_raw: bytes, record: dict[str, Any]) -> dict[str, Any]:
    value = _strict_json(raw, "terminal marker")
    required = {
        "schema",
        "transaction_id",
        "active_transaction_sha256",
        "outcome",
        "old_commit",
        "new_commit",
    }
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
    def __init__(self, install_root: Path, state_root: Path, *, fault_hook: FaultHook | None = None):
        self.install_root = _real_dir(install_root, "install root")
        self.state_root = _real_dir(state_root, "deployment state root", create=True, mode=0o700)
        self.fault_hook = fault_hook
        self.active_path = self.state_root / ACTIVE_NAME
        self.terminal_root = self.state_root / "terminal"
        self.history_root = self.state_root / "history"
        self.terminal_root.mkdir(mode=0o700, exist_ok=True)
        self.history_root.mkdir(mode=0o700, exist_ok=True)
        if self.terminal_root.is_symlink() or self.history_root.is_symlink():
            raise ReleaseSwitchError("deployment state subdirectories must be real")

    @contextmanager
    def locked(self) -> Iterator[None]:
        lock_path = self.state_root / LOCK_NAME
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
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
        if self.active_path.is_symlink() or not self.active_path.is_file():
            raise ReleaseSwitchError("no valid active release-switch transaction")
        try:
            raw = self.active_path.read_bytes()
        except OSError as exc:
            raise ReleaseSwitchError("cannot read active release-switch transaction") from exc
        return raw, _parse_record(raw)

    def _terminal_path(self, txid: str) -> Path:
        return self.terminal_root / f"{txid}.json"

    def _history_path(self, txid: str) -> Path:
        return self.history_root / f"{txid}.json"

    def _load_terminal(self, record_raw: bytes, record: dict[str, Any]) -> dict[str, Any] | None:
        path = self._terminal_path(record["transaction_id"])
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise ReleaseSwitchError("terminal marker path is not a regular file")
        return _parse_terminal(path.read_bytes(), record_raw, record)

    def _verify_bound_releases(self, record: dict[str, Any]) -> None:
        for side in ("old", "new"):
            expected = record[side]
            commit = expected["source_commit"]
            identity = _identity(_release_path(self.install_root, commit), commit)
            for key in ("payload_sha256", "payload_size", "file_count"):
                if identity[key] != expected[key]:
                    raise ReleaseSwitchError(f"{side} release identity changed after prepare: {key}")

    def prepare(self, new_commit: str) -> dict[str, Any]:
        new_commit = _commit(new_commit, "new commit")
        with self.locked():
            if self.active_path.exists() or self.active_path.is_symlink():
                raise ReleaseSwitchError("an active release-switch transaction already exists")
            current_link = _read_current_link(self.install_root)
            prefix = "releases/"
            if not current_link.startswith(prefix):
                raise ReleaseSwitchError("current symlink is not in canonical releases/<commit> form")
            old_commit = _commit(current_link[len(prefix) :], "current commit")
            if old_commit == new_commit:
                raise ReleaseSwitchError("new commit is already active")

            old_identity = _identity(_release_path(self.install_root, old_commit), old_commit)
            new_identity = _identity(_release_path(self.install_root, new_commit), new_commit)
            record = {
                "schema": SCHEMA,
                "transaction_id": uuid.uuid4().hex,
                "old": {
                    "source_commit": old_commit,
                    "payload_sha256": old_identity["payload_sha256"],
                    "payload_size": old_identity["payload_size"],
                    "file_count": old_identity["file_count"],
                },
                "new": {
                    "source_commit": new_commit,
                    "payload_sha256": new_identity["payload_sha256"],
                    "payload_size": new_identity["payload_size"],
                    "file_count": new_identity["file_count"],
                },
            }
            raw = _record_bytes(record)
            history = self._history_path(record["transaction_id"])
            terminal = self._terminal_path(record["transaction_id"])
            if history.exists() or history.is_symlink() or terminal.exists() or terminal.is_symlink():
                raise ReleaseSwitchError("new transaction identity collides with existing durable state")
            _atomic_create(self.active_path, raw)
            _fault(self.fault_hook, "prepare.after_active_create")
            if _classify_current(self.install_root, old_commit, new_commit) != "OLD":
                raise ReleaseSwitchError("current changed while preparing deployment")
            return self.status_unlocked()

    def apply(self) -> dict[str, Any]:
        with self.locked():
            record_raw, record = self._load_active()
            terminal = self._load_terminal(record_raw, record)
            if terminal is not None:
                self._finalize_unlocked(record_raw, record, terminal)
                return self.status_unlocked()
            self._verify_bound_releases(record)
            old_commit = record["old"]["source_commit"]
            new_commit = record["new"]["source_commit"]
            state = _classify_current(self.install_root, old_commit, new_commit)
            if state == "OLD":
                _atomic_symlink(self.install_root / "current", _expected_link(new_commit))
                _fault(self.fault_hook, "apply.after_current_swap")
                state = _classify_current(self.install_root, old_commit, new_commit)
            if state != "NEW":
                raise ReleaseSwitchError("cannot apply release switch: current identity is UNKNOWN")
            self._verify_bound_releases(record)
            return self.status_unlocked()

    def accept(self) -> dict[str, Any]:
        with self.locked():
            record_raw, record = self._load_active()
            existing = self._load_terminal(record_raw, record)
            if existing is not None:
                if existing["outcome"] != "ACCEPTED":
                    raise ReleaseSwitchError("transaction already has ROLLED_BACK terminal authority")
                self._finalize_unlocked(record_raw, record, existing)
                return self.status_unlocked()
            self._verify_bound_releases(record)
            old_commit = record["old"]["source_commit"]
            new_commit = record["new"]["source_commit"]
            if _classify_current(self.install_root, old_commit, new_commit) != "NEW":
                raise ReleaseSwitchError("accept requires current to be exact NEW release")
            terminal_raw = _terminal_bytes(record_raw, record, "ACCEPTED")
            _atomic_create(self._terminal_path(record["transaction_id"]), terminal_raw)
            _fault(self.fault_hook, "accept.after_terminal_create")
            terminal = _parse_terminal(terminal_raw, record_raw, record)
            self._finalize_unlocked(record_raw, record, terminal)
            return self.status_unlocked()

    def rollback(self) -> dict[str, Any]:
        with self.locked():
            record_raw, record = self._load_active()
            existing = self._load_terminal(record_raw, record)
            if existing is not None:
                if existing["outcome"] != "ROLLED_BACK":
                    raise ReleaseSwitchError("transaction already has ACCEPTED terminal authority")
                self._finalize_unlocked(record_raw, record, existing)
                return self.status_unlocked()
            self._verify_bound_releases(record)
            old_commit = record["old"]["source_commit"]
            new_commit = record["new"]["source_commit"]
            state = _classify_current(self.install_root, old_commit, new_commit)
            if state == "NEW":
                _atomic_symlink(self.install_root / "current", _expected_link(old_commit))
                _fault(self.fault_hook, "rollback.after_current_swap")
                state = _classify_current(self.install_root, old_commit, new_commit)
            if state != "OLD":
                raise ReleaseSwitchError("cannot rollback release switch: current identity is UNKNOWN")
            self._verify_bound_releases(record)
            terminal_raw = _terminal_bytes(record_raw, record, "ROLLED_BACK")
            _atomic_create(self._terminal_path(record["transaction_id"]), terminal_raw)
            _fault(self.fault_hook, "rollback.after_terminal_create")
            terminal = _parse_terminal(terminal_raw, record_raw, record)
            self._finalize_unlocked(record_raw, record, terminal)
            return self.status_unlocked()

    def _finalize_unlocked(self, record_raw: bytes, record: dict[str, Any], terminal: dict[str, Any]) -> None:
        old_commit = record["old"]["source_commit"]
        new_commit = record["new"]["source_commit"]
        expected = "NEW" if terminal["outcome"] == "ACCEPTED" else "OLD"
        if _classify_current(self.install_root, old_commit, new_commit) != expected:
            raise ReleaseSwitchError("terminal authority conflicts with current symlink identity")
        history = self._history_path(record["transaction_id"])
        if history.exists() or history.is_symlink():
            if history.is_symlink() or not history.is_file() or history.read_bytes() != record_raw:
                raise ReleaseSwitchError("deployment history identity conflict")
            if self.active_path.exists() or self.active_path.is_symlink():
                if self.active_path.is_symlink() or self.active_path.read_bytes() != record_raw:
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
        old_commit = record["old"]["source_commit"]
        new_commit = record["new"]["source_commit"]
        state = _classify_current(self.install_root, old_commit, new_commit)
        if terminal is not None:
            expected = "NEW" if terminal["outcome"] == "ACCEPTED" else "OLD"
            status = "FINALIZE_PENDING" if state == expected else "BLOCKED"
            return {
                "status": status,
                "transaction_id": record["transaction_id"],
                "current_state": state,
                "terminal": terminal["outcome"],
            }
        status = {"OLD": "PREPARED", "NEW": "APPLIED", "UNKNOWN": "BLOCKED"}[state]
        return {
            "status": status,
            "transaction_id": record["transaction_id"],
            "current_state": state,
            "old_commit": old_commit,
            "new_commit": new_commit,
        }

    def status(self) -> dict[str, Any]:
        with self.locked():
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
        switch = ReleaseSwitch(args.install_root, args.state_root)
        if args.command == "prepare":
            result = switch.prepare(args.new_commit)
        elif args.command == "apply":
            result = switch.apply()
        elif args.command == "accept":
            result = switch.accept()
        elif args.command == "rollback":
            result = switch.rollback()
        else:
            result = switch.status()
    except (ReleaseSwitchError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
