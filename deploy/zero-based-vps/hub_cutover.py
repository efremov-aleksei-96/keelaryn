from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

CORE_ROOT = Path(__file__).resolve().parents[2] / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from keelaryn_core.drive_mutation_gate import (  # noqa: E402
    DriveMutationGateAdmin,
    DriveMutationGateError,
    INHIBIT_SCHEMA,
)

SCHEMA = "keelaryn.zero-vps-hub-cutover.v1"
TERMINAL_SCHEMA = "keelaryn.zero-vps-hub-cutover-terminal.v1"
ACTIVE_NAME = "ACTIVE_TRANSACTION.json"
LOCK_NAME = "LOCK"
SELECTOR_KEY = "KEELARYN_HUB_ROOT_ID"
HUB_ID_RE = re.compile(r"[A-Za-z0-9_-]{10,256}")


class HubCutoverError(RuntimeError):
    pass


FaultHook = Callable[[str], None]


def _fault(hook: FaultHook | None, point: str) -> None:
    if hook is not None:
        hook(point)


def _source_commit(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise HubCutoverError("source commit must be exactly 40 lowercase hexadecimal characters")
    return value


def _hub_id(value: Any, label: str = "Hub root ID") -> str:
    if not isinstance(value, str) or not HUB_ID_RE.fullmatch(value):
        raise HubCutoverError(f"{label} is invalid")
    return value


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _strict_json(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HubCutoverError(f"{label} is not UTF-8") from exc

    def hook(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HubCutoverError(f"{label} contains duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        raise HubCutoverError(f"{label} is invalid JSON") from exc


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
    if path.is_symlink() or not path.is_dir():
        raise HubCutoverError(f"{label} must be a real directory")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise HubCutoverError(f"{label} must be owner-controlled mode 0700")
    return path


def _private_regular_file(path: Path, label: str) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise HubCutoverError(f"{label} must be a regular file")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise HubCutoverError(f"{label} must be owner-controlled mode 0600")
    return path


def _selector_parent(path: Path) -> Path:
    parent = path.absolute().parent
    if parent.is_symlink() or not parent.is_dir():
        raise HubCutoverError("selector parent must be a real directory")
    info = parent.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise HubCutoverError("selector parent must be owned by the current user and not group/world-writable")
    return parent


def _selector_bytes(hub_root_id: str) -> bytes:
    return f"{SELECTOR_KEY}={_hub_id(hub_root_id)}\n".encode("ascii")


def _parse_selector(raw: bytes) -> str:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise HubCutoverError("Hub selector is not ASCII") from exc
    prefix = f"{SELECTOR_KEY}="
    if not text.endswith("\n") or text.count("\n") != 1 or not text.startswith(prefix):
        raise HubCutoverError("Hub selector must contain exactly one canonical KEELARYN_HUB_ROOT_ID line")
    return _hub_id(text[len(prefix) : -1], "selector Hub root ID")


def _read_selector(path: Path) -> tuple[str, bytes]:
    if path.is_symlink() or not path.is_file():
        raise HubCutoverError("Hub selector must be one regular file")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise HubCutoverError("Hub selector must be owner-controlled mode 0600")
    raw = path.read_bytes()
    return _parse_selector(raw), raw


def _atomic_create(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        _private_regular_file(path, f"immutable file {path.name}")
        if path.read_bytes() != data:
            raise HubCutoverError(f"immutable file already exists with different identity: {path.name}")
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
                raise HubCutoverError(f"immutable file raced with different identity: {path.name}")
        _private_regular_file(path, f"immutable file {path.name}")
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_replace_selector(path: Path, expected_id: str, target_id: str) -> None:
    expected_id = _hub_id(expected_id, "expected Hub root ID")
    target_id = _hub_id(target_id, "target Hub root ID")
    current_id, _ = _read_selector(path)
    if current_id != expected_id:
        raise HubCutoverError("Hub selector changed before cutover commit")

    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    data = _selector_bytes(target_id)
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

        # Fresh validation at the durable commit boundary.
        commit_id, _ = _read_selector(path)
        if commit_id != expected_id:
            raise HubCutoverError("Hub selector changed at cutover commit boundary")
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)

    observed_id, observed_raw = _read_selector(path)
    if observed_id != target_id or observed_raw != data:
        raise HubCutoverError("durable Hub selector replacement did not become exact")


def _tool_identity(source_commit: str, executing_tool: Path) -> dict[str, str]:
    source_commit = _source_commit(source_commit)
    tool = executing_tool.absolute()
    if tool.is_symlink() or not tool.is_file():
        raise HubCutoverError("cutover tool must be a regular file")
    raw = tool.read_bytes()
    return {"source_commit": source_commit, "sha256": hashlib.sha256(raw).hexdigest()}


def _parse_record(raw: bytes) -> dict[str, Any]:
    value = _strict_json(raw, ACTIVE_NAME)
    required = {"schema", "transaction_id", "tool", "old_hub_root_id", "new_hub_root_id"}
    if not isinstance(value, dict) or set(value) != required or value["schema"] != SCHEMA:
        raise HubCutoverError("active Hub cutover transaction has invalid root/schema")
    txid = value["transaction_id"]
    if not isinstance(txid, str) or len(txid) != 32 or any(ch not in "0123456789abcdef" for ch in txid):
        raise HubCutoverError("active Hub cutover transaction has invalid transaction_id")
    tool = value["tool"]
    if not isinstance(tool, dict) or set(tool) != {"source_commit", "sha256"}:
        raise HubCutoverError("active Hub cutover tool identity is invalid")
    _source_commit(tool["source_commit"])
    if (
        not isinstance(tool["sha256"], str)
        or len(tool["sha256"]) != 64
        or any(ch not in "0123456789abcdef" for ch in tool["sha256"])
    ):
        raise HubCutoverError("active Hub cutover tool SHA-256 is invalid")
    old_id = _hub_id(value["old_hub_root_id"], "old Hub root ID")
    new_id = _hub_id(value["new_hub_root_id"], "new Hub root ID")
    if old_id == new_id:
        raise HubCutoverError("Hub cutover cannot target the already-active Hub")
    return value


def _terminal_bytes(record_raw: bytes, record: dict[str, Any], outcome: str) -> bytes:
    if outcome not in {"ACCEPTED", "ROLLED_BACK"}:
        raise HubCutoverError("invalid Hub cutover terminal outcome")
    return _json(
        {
            "schema": TERMINAL_SCHEMA,
            "transaction_id": record["transaction_id"],
            "active_transaction_sha256": hashlib.sha256(record_raw).hexdigest(),
            "outcome": outcome,
            "tool": record["tool"],
        }
    )


def _parse_terminal(raw: bytes, record_raw: bytes, record: dict[str, Any]) -> dict[str, Any]:
    value = _strict_json(raw, "Hub cutover terminal marker")
    required = {"schema", "transaction_id", "active_transaction_sha256", "outcome", "tool"}
    if not isinstance(value, dict) or set(value) != required or value["schema"] != TERMINAL_SCHEMA:
        raise HubCutoverError("Hub cutover terminal marker has invalid root/schema")
    if value["transaction_id"] != record["transaction_id"]:
        raise HubCutoverError("Hub cutover terminal marker transaction mismatch")
    if value["active_transaction_sha256"] != hashlib.sha256(record_raw).hexdigest():
        raise HubCutoverError("Hub cutover terminal marker does not bind exact active transaction")
    if value["tool"] != record["tool"] or value["outcome"] not in {"ACCEPTED", "ROLLED_BACK"}:
        raise HubCutoverError("Hub cutover terminal marker identity/outcome mismatch")
    return value


class HubSelectorCutover:
    """Durable restart-safe transaction for the single production Hub selector.

    The selector is a root/admin-controlled environment file containing exactly one
    ``KEELARYN_HUB_ROOT_ID`` assignment.  This tool never touches Google Drive or
    Hub bytes.  The caller owns service stop/start and post-cutover acceptance.
    ``accept`` is therefore an explicit acknowledgement that external read-only
    acceptance succeeded; ``rollback`` restores the exact OLD selector identity.
    """

    def __init__(
        self,
        selector_path: Path,
        state_root: Path,
        source_commit: str,
        *,
        mutation_gate_root: Path | None = None,
        executing_tool: Path | None = None,
        fault_hook: FaultHook | None = None,
    ):
        self.selector_path = selector_path.absolute()
        _selector_parent(self.selector_path)
        _read_selector(self.selector_path)
        self.state_root = _private_dir(state_root, "Hub cutover state root", create=True)
        self.terminal_root = self.state_root / "terminal"
        self.history_root = self.state_root / "history"
        self.terminal_root.mkdir(mode=0o700, exist_ok=True)
        self.history_root.mkdir(mode=0o700, exist_ok=True)
        self.terminal_root = _private_dir(self.terminal_root, "Hub cutover terminal directory")
        self.history_root = _private_dir(self.history_root, "Hub cutover history directory")
        self.active_path = self.state_root / ACTIVE_NAME
        self.executing_tool = (executing_tool or Path(__file__)).absolute()
        self.tool_identity = _tool_identity(source_commit, self.executing_tool)
        self.mutation_gate = (
            DriveMutationGateAdmin(mutation_gate_root)
            if mutation_gate_root is not None
            else None
        )
        self.fault_hook = fault_hook
        _fsync_dir(self.state_root)

    @contextmanager
    def locked(self) -> Iterator[None]:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.state_root / LOCK_NAME, flags, 0o600)
        except OSError as exc:
            raise HubCutoverError("cannot open Hub cutover lock without following symlinks") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise HubCutoverError("Hub cutover lock must be owner-controlled regular file mode 0600")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise HubCutoverError("another local Hub-cutover process holds the lock") from exc
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _load_active(self) -> tuple[bytes, dict[str, Any]]:
        try:
            _private_regular_file(self.active_path, "active Hub cutover transaction")
        except HubCutoverError as exc:
            raise HubCutoverError("no valid private active Hub cutover transaction") from exc
        raw = self.active_path.read_bytes()
        record = _parse_record(raw)
        if record["tool"] != self.tool_identity:
            raise HubCutoverError("active Hub cutover must continue with the exact prepared tool identity")
        return raw, record

    def _terminal_path(self, txid: str) -> Path:
        return self.terminal_root / f"{txid}.json"

    def _history_path(self, txid: str) -> Path:
        return self.history_root / f"{txid}.json"

    def _mutation_inhibit_value(
        self,
        record_raw: bytes,
        record: dict[str, Any],
    ) -> dict[str, str]:
        return {
            "schema": INHIBIT_SCHEMA,
            "transaction_id": record["transaction_id"],
            "active_transaction_sha256": hashlib.sha256(record_raw).hexdigest(),
            "source_commit": record["tool"]["source_commit"],
            "tool_sha256": record["tool"]["sha256"],
            "old_selector_sha256": hashlib.sha256(
                _selector_bytes(record["old_hub_root_id"])
            ).hexdigest(),
            "new_selector_sha256": hashlib.sha256(
                _selector_bytes(record["new_hub_root_id"])
            ).hexdigest(),
        }

    def _release_rollback_inhibit(
        self,
        record_raw: bytes,
        record: dict[str, Any],
        *,
        allow_absent: bool,
    ) -> None:
        if self.mutation_gate is None:
            return
        expected = self._mutation_inhibit_value(record_raw, record)
        with self.mutation_gate.locked():
            observed = self.mutation_gate.read()
            if observed is None:
                if allow_absent:
                    return
                raise HubCutoverError(
                    "production mutation inhibit disappeared before rollback settled"
                )
            if observed != expected:
                raise HubCutoverError(
                    "production mutation inhibit identity disagrees with rollback transaction"
                )
            self.mutation_gate.clear(expected)

    def release_mutation_inhibit_after_accept(
        self,
        transaction_id: str,
        expected_active_transaction_sha256: str,
        *,
        allow_absent: bool = False,
    ) -> dict[str, str]:
        if (
            not isinstance(transaction_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", transaction_id)
        ):
            raise HubCutoverError("accepted Hub cutover transaction ID is invalid")
        if (
            not isinstance(expected_active_transaction_sha256, str)
            or not re.fullmatch(
                r"[0-9a-f]{64}", expected_active_transaction_sha256
            )
        ):
            raise HubCutoverError(
                "accepted Hub cutover transaction SHA-256 is invalid"
            )
        with self.locked():
            if self.active_path.exists() or self.active_path.is_symlink():
                raise HubCutoverError(
                    "cannot release production mutation inhibit while Hub cutover remains active"
                )
            history = self._history_path(transaction_id)
            _private_regular_file(history, "accepted Hub cutover history record")
            record_raw = history.read_bytes()
            record = _parse_record(record_raw)
            if record["transaction_id"] != transaction_id:
                raise HubCutoverError("accepted Hub cutover history transaction mismatch")
            if record["tool"] != self.tool_identity:
                raise HubCutoverError("accepted Hub cutover history tool identity mismatch")
            if hashlib.sha256(record_raw).hexdigest() != expected_active_transaction_sha256:
                raise HubCutoverError("accepted Hub cutover history authority mismatch")
            terminal = self._load_terminal(record_raw, record)
            if terminal is None or terminal["outcome"] != "ACCEPTED":
                raise HubCutoverError("accepted Hub cutover terminal authority is missing")
            if self._classify(record) != "NEW":
                raise HubCutoverError("accepted Hub cutover selector is not exact NEW")

            if self.mutation_gate is None:
                return {"status": "IDLE"}
            expected = self._mutation_inhibit_value(record_raw, record)
            with self.mutation_gate.locked():
                observed = self.mutation_gate.read()
                if observed is None:
                    if allow_absent:
                        return {"status": "IDLE"}
                    raise HubCutoverError(
                        "production mutation inhibit disappeared before accepted finalization"
                    )
                if observed != expected:
                    raise HubCutoverError(
                        "production mutation inhibit identity disagrees with accepted transaction"
                    )
                self.mutation_gate.clear(expected)
            _fault(self.fault_hook, "accept.after_mutation_inhibit_release")
            return {"status": "IDLE"}

    def _load_terminal(self, record_raw: bytes, record: dict[str, Any]) -> dict[str, Any] | None:
        path = self._terminal_path(record["transaction_id"])
        if not path.exists() and not path.is_symlink():
            return None
        _private_regular_file(path, "Hub cutover terminal marker")
        return _parse_terminal(path.read_bytes(), record_raw, record)

    def _classify(self, record: dict[str, Any]) -> str:
        try:
            current, _ = _read_selector(self.selector_path)
        except HubCutoverError:
            return "UNKNOWN"
        if current == record["old_hub_root_id"]:
            return "OLD"
        if current == record["new_hub_root_id"]:
            return "NEW"
        return "UNKNOWN"

    def _settle_terminal(self, record_raw: bytes, record: dict[str, Any], terminal: dict[str, Any]) -> None:
        expected = record["new_hub_root_id"] if terminal["outcome"] == "ACCEPTED" else record["old_hub_root_id"]
        current, _ = _read_selector(self.selector_path)
        if current != expected:
            raise HubCutoverError("terminal Hub cutover outcome does not match durable selector")
        history = self._history_path(record["transaction_id"])
        _atomic_create(history, record_raw)
        _fault(self.fault_hook, "finalize.after_history_create")
        try:
            self.active_path.unlink()
        except FileNotFoundError:
            pass
        _fsync_dir(self.state_root)
        _fault(self.fault_hook, "finalize.after_active_unlink")

    def prepare(self, new_hub_root_id: str) -> dict[str, Any]:
        new_hub_root_id = _hub_id(new_hub_root_id, "new Hub root ID")
        with self.locked():
            if self.active_path.exists() or self.active_path.is_symlink():
                raise HubCutoverError("an active Hub cutover transaction already exists")
            old_hub_root_id, _ = _read_selector(self.selector_path)
            if old_hub_root_id == new_hub_root_id:
                raise HubCutoverError("new Hub root ID is already selected")

            if self.mutation_gate is None:
                transaction_id = uuid.uuid4().hex
                record = {
                    "schema": SCHEMA,
                    "transaction_id": transaction_id,
                    "tool": self.tool_identity,
                    "old_hub_root_id": old_hub_root_id,
                    "new_hub_root_id": new_hub_root_id,
                }
                raw = _json(record)
                _atomic_create(self.active_path, raw)
                _fault(self.fault_hook, "prepare.after_active_create")
                return {"status": "PREPARED", "transaction_id": transaction_id}

            with self.mutation_gate.locked():
                existing = self.mutation_gate.read()
                transaction_id = (
                    existing["transaction_id"]
                    if existing is not None
                    else uuid.uuid4().hex
                )
                record = {
                    "schema": SCHEMA,
                    "transaction_id": transaction_id,
                    "tool": self.tool_identity,
                    "old_hub_root_id": old_hub_root_id,
                    "new_hub_root_id": new_hub_root_id,
                }
                raw = _json(record)
                expected = self._mutation_inhibit_value(raw, record)
                if existing is not None and existing != expected:
                    raise HubCutoverError(
                        "existing production mutation inhibit belongs to a different transaction"
                    )
                self.mutation_gate.publish(expected)
                _fault(self.fault_hook, "prepare.after_mutation_inhibit_create")
                _atomic_create(self.active_path, raw)
                _fault(self.fault_hook, "prepare.after_active_create")
                return {"status": "PREPARED", "transaction_id": transaction_id}

    def status(self) -> dict[str, Any]:
        with self.locked():
            if not self.active_path.exists() and not self.active_path.is_symlink():
                if self.mutation_gate is not None:
                    inhibit = self.mutation_gate.read()
                    if inhibit is not None:
                        return {
                            "status": "INHIBITED_IDLE",
                            "transaction_id": inhibit["transaction_id"],
                        }
                return {"status": "IDLE"}
            record_raw, record = self._load_active()
            terminal = self._load_terminal(record_raw, record)
            if terminal is not None:
                expected = "NEW" if terminal["outcome"] == "ACCEPTED" else "OLD"
                observed = self._classify(record)
                if observed != expected:
                    return {"status": "BLOCKED", "reason": "terminal-selector-mismatch"}
                return {
                    "status": "FINALIZE_PENDING",
                    "terminal": terminal["outcome"],
                    "transaction_id": record["transaction_id"],
                }
            observed = self._classify(record)
            if observed == "OLD":
                return {"status": "PREPARED", "transaction_id": record["transaction_id"]}
            if observed == "NEW":
                return {"status": "APPLIED", "transaction_id": record["transaction_id"]}
            return {"status": "BLOCKED", "reason": "selector-identity-unknown", "transaction_id": record["transaction_id"]}

    def apply(self) -> dict[str, Any]:
        with self.locked():
            record_raw, record = self._load_active()
            if self._load_terminal(record_raw, record) is not None:
                raise HubCutoverError("terminal Hub cutover decision already exists")
            observed = self._classify(record)
            if observed == "NEW":
                return {"status": "APPLIED", "transaction_id": record["transaction_id"]}
            if observed != "OLD":
                raise HubCutoverError("Hub selector is neither exact OLD nor exact NEW identity")
            _fault(self.fault_hook, "apply.before_selector_replace")
            _atomic_replace_selector(
                self.selector_path,
                record["old_hub_root_id"],
                record["new_hub_root_id"],
            )
            _fault(self.fault_hook, "apply.after_selector_replace")
            return {"status": "APPLIED", "transaction_id": record["transaction_id"]}

    def accept(
        self,
        *,
        expected_active_transaction_sha256: str | None = None,
    ) -> dict[str, Any]:
        with self.locked():
            record_raw, record = self._load_active()
            if expected_active_transaction_sha256 is not None:
                if (
                    not isinstance(expected_active_transaction_sha256, str)
                    or len(expected_active_transaction_sha256) != 64
                    or any(
                        ch not in "0123456789abcdef"
                        for ch in expected_active_transaction_sha256
                    )
                ):
                    raise HubCutoverError(
                        "expected active Hub cutover transaction SHA-256 is invalid"
                    )
                if hashlib.sha256(record_raw).hexdigest() != expected_active_transaction_sha256:
                    raise HubCutoverError(
                        "active Hub cutover transaction changed at terminal accept boundary"
                    )

            def finalize_under_gate() -> dict[str, Any]:
                if self.mutation_gate is not None:
                    expected_inhibit = self._mutation_inhibit_value(record_raw, record)
                    observed_inhibit = self.mutation_gate.read()
                    if observed_inhibit != expected_inhibit:
                        raise HubCutoverError(
                            "production mutation inhibit does not bind exact terminal accept transaction"
                        )
                terminal = self._load_terminal(record_raw, record)
                if terminal is not None:
                    if terminal["outcome"] != "ACCEPTED":
                        raise HubCutoverError("Hub cutover was already terminally rolled back")
                    self._settle_terminal(record_raw, record, terminal)
                else:
                    if self._classify(record) != "NEW":
                        raise HubCutoverError(
                            "Hub cutover acceptance requires exact NEW selector"
                        )
                    raw = _terminal_bytes(record_raw, record, "ACCEPTED")
                    _atomic_create(self._terminal_path(record["transaction_id"]), raw)
                    _fault(self.fault_hook, "accept.after_terminal_create")
                    terminal = _parse_terminal(raw, record_raw, record)
                    self._settle_terminal(record_raw, record, terminal)

                if self.mutation_gate is not None:
                    return {
                        "status": "INHIBITED_IDLE",
                        "transaction_id": record["transaction_id"],
                    }
                return {"status": "IDLE"}

            if self.mutation_gate is None:
                return finalize_under_gate()
            with self.mutation_gate.locked():
                return finalize_under_gate()

    def rollback(self) -> dict[str, Any]:
        with self.locked():
            record_raw, record = self._load_active()
            terminal = self._load_terminal(record_raw, record)
            if terminal is not None:
                if terminal["outcome"] != "ROLLED_BACK":
                    raise HubCutoverError("Hub cutover was already terminally accepted")
                if self._classify(record) != "OLD":
                    raise HubCutoverError(
                        "rolled-back Hub cutover terminal does not match exact OLD selector"
                    )
                self._release_rollback_inhibit(
                    record_raw,
                    record,
                    allow_absent=True,
                )
                self._settle_terminal(record_raw, record, terminal)
                return {"status": "IDLE"}
            observed = self._classify(record)
            if observed == "NEW":
                _atomic_replace_selector(
                    self.selector_path,
                    record["new_hub_root_id"],
                    record["old_hub_root_id"],
                )
                _fault(self.fault_hook, "rollback.after_selector_replace")
            elif observed != "OLD":
                raise HubCutoverError("Hub selector is neither exact OLD nor exact NEW identity")
            raw = _terminal_bytes(record_raw, record, "ROLLED_BACK")
            _atomic_create(self._terminal_path(record["transaction_id"]), raw)
            _fault(self.fault_hook, "rollback.after_terminal_create")
            terminal = _parse_terminal(raw, record_raw, record)
            self._release_rollback_inhibit(
                record_raw,
                record,
                allow_absent=False,
            )
            _fault(self.fault_hook, "rollback.after_mutation_inhibit_release")
            self._settle_terminal(record_raw, record, terminal)
            return {"status": "IDLE"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-hub-cutover")
    parser.add_argument("--selector-path", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--mutation-gate-root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("new_hub_root_id")
    sub.add_parser("status")
    sub.add_parser("apply")
    sub.add_parser("rollback")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        switch = HubSelectorCutover(
            args.selector_path,
            args.state_root,
            args.source_commit,
            mutation_gate_root=args.mutation_gate_root,
            executing_tool=Path(__file__),
        )
        if args.command == "prepare":
            result = switch.prepare(args.new_hub_root_id)
        elif args.command == "status":
            result = switch.status()
        elif args.command == "apply":
            result = switch.apply()
        else:
            result = switch.rollback()
    except (HubCutoverError, DriveMutationGateError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
