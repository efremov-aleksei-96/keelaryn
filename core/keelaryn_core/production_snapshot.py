from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .drive_mutation_gate import (
    DriveMutationGateError,
    INHIBIT_NAME,
    read_mutation_inhibit,
)
from .protocol import ProtocolError, strict_json_bytes


SNAPSHOT_SCHEMA = "keelaryn.production-snapshot.v1"
WORKER_SCHEMA = "keelaryn.production-snapshot-worker.v1"
SNAPSHOT_NAME = "production-snapshot.json"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TXID = re.compile(r"^[0-9a-f]{32}$")
_OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")
_HUB_ID = re.compile(r"^[A-Za-z0-9_-]{10,256}$")
_ACTIVE_STATE = re.compile(r"^[a-z][a-z-]{0,31}$")
_TIMESTAMP = re.compile(r"^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$")

_ACTIVE_SCHEMA = "keelaryn.zero-vps-hub-cutover.v2"
_TERMINAL_SCHEMA = "keelaryn.zero-vps-hub-cutover-terminal.v1"
_ACTIVE_KEYS = {
    "schema",
    "transaction_id",
    "tool",
    "finalizers",
    "old_hub_root_id",
    "new_hub_root_id",
}
_TERMINAL_KEYS = {
    "schema",
    "transaction_id",
    "active_transaction_sha256",
    "outcome",
    "tool",
}


class ProductionSnapshotError(RuntimeError):
    """A production boundary cannot be observed safely and without secrets."""


@dataclass(frozen=True)
class ProductionSnapshotLayout:
    install_root: Path = Path("/opt/keelaryn")
    selector_path: Path = Path("/etc/keelaryn/hub.env")
    deployment_state_root: Path = Path("/var/lib/keelaryn/deployment")
    mutation_gate_root: Path = Path("/var/lib/keelaryn/mutation-gate")
    writer_unit: str = "keelaryn-drive.service"
    agent_unit: str = "keelaryn-operation-agent.service"
    transport_unit: str = "keelaryn-operation-transport.service"


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def _compact(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _trusted_owner(uid: int) -> bool:
    if os.name != "posix":
        return True
    return uid in {0, os.geteuid()}


def _regular(path: Path, label: str, mode: int) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProductionSnapshotError(f"{label} cannot be inspected") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProductionSnapshotError(f"{label} must be one regular file")
    if os.name == "posix":
        if not _trusted_owner(info.st_uid) or stat.S_IMODE(info.st_mode) != mode:
            raise ProductionSnapshotError(
                f"{label} must have trusted owner and mode {mode:04o}"
            )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ProductionSnapshotError(f"{label} cannot be read") from exc


def _optional_regular(path: Path, label: str, mode: int) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    return _regular(path, label, mode)


def _release_selector(path: Path, install_root: Path, label: str) -> str:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProductionSnapshotError(f"{label} cannot be inspected") from exc
    if not stat.S_ISLNK(info.st_mode):
        raise ProductionSnapshotError(f"{label} must be one symlink")
    try:
        target = os.readlink(path)
    except OSError as exc:
        raise ProductionSnapshotError(f"{label} cannot be read") from exc
    match = re.fullmatch(r"releases/([0-9a-f]{40})", target)
    if match is None:
        raise ProductionSnapshotError(f"{label} target is not canonical")
    release = install_root / target
    try:
        release_info = release.lstat()
    except OSError as exc:
        raise ProductionSnapshotError(f"{label} release cannot be inspected") from exc
    if stat.S_ISLNK(release_info.st_mode) or not stat.S_ISDIR(release_info.st_mode):
        raise ProductionSnapshotError(f"{label} release must be one real directory")
    return match.group(1)


def _selector_value(path: Path) -> str:
    raw = _regular(path, "Hub selector", 0o600)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProductionSnapshotError("Hub selector is not ASCII") from exc
    prefix = "KEELARYN_HUB_ROOT_ID="
    if (
        not text.startswith(prefix)
        or not text.endswith("\n")
        or text.count("\n") != 1
    ):
        raise ProductionSnapshotError("Hub selector is not canonical")
    value = text[len(prefix):-1]
    if _HUB_ID.fullmatch(value) is None:
        raise ProductionSnapshotError("Hub selector identity is invalid")
    return value


def _strict_compact(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = strict_json_bytes(raw, label=label)
    except ProtocolError as exc:
        raise ProductionSnapshotError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ProductionSnapshotError(f"{label} must be one JSON object")
    if raw != _compact(value):
        raise ProductionSnapshotError(f"{label} is not canonical compact JSON")
    return value


def _sha256_state(raw: bytes | None) -> dict[str, Any]:
    if raw is None:
        return {"state": "ABSENT", "sha256": None}
    return {
        "state": "PRESENT",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _hub_boundary(layout: ProductionSnapshotLayout) -> dict[str, Any]:
    selector = _selector_value(layout.selector_path)
    active_path = layout.deployment_state_root / "ACTIVE_TRANSACTION.json"
    active_raw = _optional_regular(
        active_path,
        "active Hub cutover transaction",
        0o600,
    )
    try:
        inhibit = read_mutation_inhibit(layout.mutation_gate_root)
    except DriveMutationGateError as exc:
        raise ProductionSnapshotError(
            "Drive mutation inhibit cannot be observed safely"
        ) from exc

    inhibit_path = layout.mutation_gate_root / INHIBIT_NAME
    inhibit_raw = (
        None
        if inhibit is None
        else _regular(inhibit_path, "Drive mutation inhibit", 0o640)
    )
    inhibit_sha = (
        None if inhibit_raw is None else hashlib.sha256(inhibit_raw).hexdigest()
    )

    if active_raw is None:
        if inhibit is None:
            return {
                "status": "IDLE",
                "transaction_id": None,
                "selector_role": "NONE",
                "terminal": None,
                "reason": None,
                "active_transaction": _sha256_state(None),
                "mutation_inhibit": {
                    "state": "ABSENT",
                    "sha256": None,
                    "transaction_matches": None,
                    "active_transaction_matches": None,
                },
            }
        return {
            "status": "INHIBITED_IDLE",
            "transaction_id": inhibit["transaction_id"],
            "selector_role": "UNKNOWN",
            "terminal": None,
            "reason": "ACTIVE_TRANSACTION_ABSENT",
            "active_transaction": _sha256_state(None),
            "mutation_inhibit": {
                "state": "PRESENT",
                "sha256": inhibit_sha,
                "transaction_matches": True,
                "active_transaction_matches": None,
            },
        }

    active = _strict_compact(active_raw, "ACTIVE_TRANSACTION")
    if set(active) != _ACTIVE_KEYS or active.get("schema") != _ACTIVE_SCHEMA:
        raise ProductionSnapshotError("ACTIVE_TRANSACTION keys/schema mismatch")
    txid = active.get("transaction_id")
    old_id = active.get("old_hub_root_id")
    new_id = active.get("new_hub_root_id")
    if not isinstance(txid, str) or _TXID.fullmatch(txid) is None:
        raise ProductionSnapshotError("ACTIVE_TRANSACTION transaction_id invalid")
    if not isinstance(old_id, str) or _HUB_ID.fullmatch(old_id) is None:
        raise ProductionSnapshotError("ACTIVE_TRANSACTION old identity invalid")
    if not isinstance(new_id, str) or _HUB_ID.fullmatch(new_id) is None:
        raise ProductionSnapshotError("ACTIVE_TRANSACTION new identity invalid")
    if not isinstance(active.get("tool"), dict) or not isinstance(
        active.get("finalizers"), dict
    ):
        raise ProductionSnapshotError("ACTIVE_TRANSACTION authority shape invalid")

    active_sha = hashlib.sha256(active_raw).hexdigest()
    if selector == old_id:
        selector_role = "OLD"
    elif selector == new_id:
        selector_role = "NEW"
    else:
        selector_role = "UNKNOWN"

    terminal_path = (
        layout.deployment_state_root / "terminal" / f"{txid}.json"
    )
    terminal_raw = _optional_regular(
        terminal_path,
        "Hub cutover terminal marker",
        0o600,
    )
    terminal: str | None = None
    reason: str | None = None
    if terminal_raw is not None:
        terminal_value = _strict_compact(
            terminal_raw,
            "Hub cutover terminal marker",
        )
        if (
            set(terminal_value) != _TERMINAL_KEYS
            or terminal_value.get("schema") != _TERMINAL_SCHEMA
            or terminal_value.get("transaction_id") != txid
            or terminal_value.get("active_transaction_sha256") != active_sha
            or terminal_value.get("tool") != active["tool"]
            or terminal_value.get("outcome") not in {"ACCEPTED", "ROLLED_BACK"}
        ):
            raise ProductionSnapshotError(
                "Hub cutover terminal marker identity mismatch"
            )
        terminal = str(terminal_value["outcome"])
        expected = "NEW" if terminal == "ACCEPTED" else "OLD"
        if selector_role != expected:
            status = "BLOCKED"
            reason = "TERMINAL_SELECTOR_MISMATCH"
        else:
            status = "FINALIZE_PENDING"
    elif selector_role == "OLD":
        status = "PREPARED"
    elif selector_role == "NEW":
        status = "APPLIED"
    else:
        status = "BLOCKED"
        reason = "SELECTOR_IDENTITY_UNKNOWN"

    if inhibit is None:
        inhibit_value = {
            "state": "ABSENT",
            "sha256": None,
            "transaction_matches": None,
            "active_transaction_matches": None,
        }
    else:
        inhibit_value = {
            "state": "PRESENT",
            "sha256": inhibit_sha,
            "transaction_matches": inhibit["transaction_id"] == txid,
            "active_transaction_matches": (
                inhibit["active_transaction_sha256"] == active_sha
            ),
        }

    return {
        "status": status,
        "transaction_id": txid,
        "selector_role": selector_role,
        "terminal": terminal,
        "reason": reason,
        "active_transaction": _sha256_state(active_raw),
        "mutation_inhibit": inhibit_value,
    }


def _default_run(
    args: list[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProductionSnapshotError(
            "production observation command outcome is uncertain"
        ) from exc


def _service_state(
    unit: str,
    run: CommandRunner,
) -> dict[str, Any]:
    result = run(
        [
            "systemctl",
            "show",
            unit,
            "--property=ActiveState",
            "--property=MainPID",
        ],
        30,
    )
    if result.returncode != 0:
        raise ProductionSnapshotError("systemd service observation failed")
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key] = value
    if set(parsed) != {"ActiveState", "MainPID"}:
        raise ProductionSnapshotError("systemd service observation incomplete")
    active = parsed["ActiveState"]
    if _ACTIVE_STATE.fullmatch(active) is None:
        raise ProductionSnapshotError("systemd ActiveState is invalid")
    try:
        pid = int(parsed["MainPID"])
    except ValueError as exc:
        raise ProductionSnapshotError("systemd MainPID is invalid") from exc
    if pid < 0:
        raise ProductionSnapshotError("systemd MainPID is invalid")
    return {"active_state": active.upper(), "main_pid": pid}


def _boundary_once(
    layout: ProductionSnapshotLayout,
    run: CommandRunner,
) -> dict[str, Any]:
    return {
        "production_source_commit": _release_selector(
            layout.install_root / "current",
            layout.install_root,
            "production current",
        ),
        "control_source_commit": _release_selector(
            layout.install_root / "control-current",
            layout.install_root,
            "control current",
        ),
        "services": {
            "writer": _service_state(layout.writer_unit, run),
            "operation_agent": _service_state(layout.agent_unit, run),
            "operation_transport": _service_state(layout.transport_unit, run),
        },
        "legacy_hub": _hub_boundary(layout),
    }


def collect_production_snapshot(
    layout: ProductionSnapshotLayout | None = None,
    *,
    run: CommandRunner = _default_run,
) -> dict[str, Any]:
    layout = ProductionSnapshotLayout() if layout is None else layout
    first = _boundary_once(layout, run)
    second = _boundary_once(layout, run)
    if first != second:
        raise ProductionSnapshotError(
            "production boundary changed during read-only observation"
        )
    value = {
        "schema": SNAPSHOT_SCHEMA,
        "observed_at_utc": _utc_now(),
        **first,
        "production_mutations_performed": False,
        "drive_mutations_performed": False,
    }
    return validate_production_snapshot(value)


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ProductionSnapshotError(f"{label} is invalid")
    return value


def _require_sha256_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProductionSnapshotError(f"{label} is invalid")
    return value


def validate_production_snapshot(value: Any) -> dict[str, Any]:
    expected = {
        "schema",
        "observed_at_utc",
        "production_source_commit",
        "control_source_commit",
        "services",
        "legacy_hub",
        "production_mutations_performed",
        "drive_mutations_performed",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ProductionSnapshotError("production snapshot keys are invalid")
    if value["schema"] != SNAPSHOT_SCHEMA:
        raise ProductionSnapshotError("production snapshot schema mismatch")
    if (
        not isinstance(value["observed_at_utc"], str)
        or _TIMESTAMP.fullmatch(value["observed_at_utc"]) is None
    ):
        raise ProductionSnapshotError("production snapshot timestamp invalid")
    _require_sha(
        value["production_source_commit"],
        "production snapshot production source",
    )
    _require_sha(
        value["control_source_commit"],
        "production snapshot control source",
    )
    if value["production_mutations_performed"] is not False:
        raise ProductionSnapshotError(
            "production snapshot cannot claim production mutation"
        )
    if value["drive_mutations_performed"] is not False:
        raise ProductionSnapshotError(
            "production snapshot cannot claim Drive mutation"
        )

    services = value["services"]
    if not isinstance(services, dict) or set(services) != {
        "writer",
        "operation_agent",
        "operation_transport",
    }:
        raise ProductionSnapshotError("production snapshot services invalid")
    for name, service in services.items():
        if not isinstance(service, dict) or set(service) != {
            "active_state",
            "main_pid",
        }:
            raise ProductionSnapshotError(
                f"production snapshot service invalid: {name}"
            )
        active = service["active_state"]
        if (
            not isinstance(active, str)
            or not active
            or len(active) > 32
            or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ-" for ch in active)
        ):
            raise ProductionSnapshotError(
                f"production snapshot service state invalid: {name}"
            )
        pid = service["main_pid"]
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 0:
            raise ProductionSnapshotError(
                f"production snapshot service pid invalid: {name}"
            )

    hub = value["legacy_hub"]
    hub_keys = {
        "status",
        "transaction_id",
        "selector_role",
        "terminal",
        "reason",
        "active_transaction",
        "mutation_inhibit",
    }
    if not isinstance(hub, dict) or set(hub) != hub_keys:
        raise ProductionSnapshotError("production snapshot legacy Hub invalid")
    if hub["status"] not in {
        "IDLE",
        "INHIBITED_IDLE",
        "PREPARED",
        "APPLIED",
        "FINALIZE_PENDING",
        "BLOCKED",
    }:
        raise ProductionSnapshotError("production snapshot Hub status invalid")
    txid = hub["transaction_id"]
    if txid is not None and (
        not isinstance(txid, str) or _TXID.fullmatch(txid) is None
    ):
        raise ProductionSnapshotError("production snapshot transaction invalid")
    if hub["selector_role"] not in {"NONE", "OLD", "NEW", "UNKNOWN"}:
        raise ProductionSnapshotError("production snapshot selector role invalid")
    if hub["terminal"] not in {None, "ACCEPTED", "ROLLED_BACK"}:
        raise ProductionSnapshotError("production snapshot terminal invalid")
    if hub["reason"] not in {
        None,
        "ACTIVE_TRANSACTION_ABSENT",
        "TERMINAL_SELECTOR_MISMATCH",
        "SELECTOR_IDENTITY_UNKNOWN",
    }:
        raise ProductionSnapshotError("production snapshot reason invalid")

    active_tx = hub["active_transaction"]
    if not isinstance(active_tx, dict) or set(active_tx) != {"state", "sha256"}:
        raise ProductionSnapshotError(
            "production snapshot active transaction invalid"
        )
    if active_tx["state"] not in {"ABSENT", "PRESENT"}:
        raise ProductionSnapshotError(
            "production snapshot active transaction state invalid"
        )
    active_sha = _require_sha256_or_none(
        active_tx["sha256"],
        "production snapshot active transaction sha256",
    )
    if (active_tx["state"] == "ABSENT") != (active_sha is None):
        raise ProductionSnapshotError(
            "production snapshot active transaction state/hash mismatch"
        )

    inhibit = hub["mutation_inhibit"]
    if not isinstance(inhibit, dict) or set(inhibit) != {
        "state",
        "sha256",
        "transaction_matches",
        "active_transaction_matches",
    }:
        raise ProductionSnapshotError(
            "production snapshot mutation inhibit invalid"
        )
    if inhibit["state"] not in {"ABSENT", "PRESENT"}:
        raise ProductionSnapshotError(
            "production snapshot mutation inhibit state invalid"
        )
    inhibit_sha = _require_sha256_or_none(
        inhibit["sha256"],
        "production snapshot mutation inhibit sha256",
    )
    if (inhibit["state"] == "ABSENT") != (inhibit_sha is None):
        raise ProductionSnapshotError(
            "production snapshot mutation inhibit state/hash mismatch"
        )
    for key in ("transaction_matches", "active_transaction_matches"):
        if inhibit[key] is not None and not isinstance(inhibit[key], bool):
            raise ProductionSnapshotError(
                f"production snapshot mutation inhibit {key} invalid"
            )
        if inhibit["state"] == "ABSENT" and inhibit[key] is not None:
            raise ProductionSnapshotError(
                "absent mutation inhibit cannot claim identity match"
            )
    return value


def production_snapshot_bytes(value: Any) -> bytes:
    validated = validate_production_snapshot(value)
    return _compact(validated)


def read_production_snapshot(path: str | Path) -> dict[str, Any]:
    path = Path(path).absolute()
    raw = _regular(path, "production snapshot result", 0o600)
    if len(raw) > 32768:
        raise ProductionSnapshotError("production snapshot result is too large")
    value = _strict_compact(raw, "production snapshot result")
    validate_production_snapshot(value)
    return value


def write_production_snapshot(
    path: str | Path,
    value: Any,
) -> dict[str, Any]:
    path = Path(path).absolute()
    if path.name != SNAPSHOT_NAME:
        raise ProductionSnapshotError("production snapshot filename is invalid")
    parent = path.parent
    try:
        parent_info = parent.lstat()
    except OSError as exc:
        raise ProductionSnapshotError(
            "production snapshot parent cannot be inspected"
        ) from exc
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise ProductionSnapshotError(
            "production snapshot parent must be one real directory"
        )
    if os.name == "posix":
        if (
            not _trusted_owner(parent_info.st_uid)
            or stat.S_IMODE(parent_info.st_mode) != 0o700
        ):
            raise ProductionSnapshotError(
                "production snapshot parent must have trusted owner and mode 0700"
            )
    if path.exists() or path.is_symlink():
        raise ProductionSnapshotError("production snapshot result already exists")

    raw = production_snapshot_bytes(value)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ProductionSnapshotError(
            "production snapshot result cannot be created"
        ) from exc
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise ProductionSnapshotError(
                    "production snapshot write made no forward progress"
                )
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name == "posix":
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    observed = read_production_snapshot(path)
    if observed != value:
        raise ProductionSnapshotError(
            "production snapshot durable result identity mismatch"
        )
    return observed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-production-snapshot")
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if _OPERATION_ID.fullmatch(args.operation_id) is None:
            raise ProductionSnapshotError("operation identity is invalid")
        output = args.output.absolute()
        if (
            output.name != SNAPSHOT_NAME
            or output.parent.name != args.operation_id
        ):
            raise ProductionSnapshotError(
                "production snapshot output is not bound to operation identity"
            )
        value = collect_production_snapshot()
        write_production_snapshot(output, value)
    except (ProductionSnapshotError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"schema": WORKER_SCHEMA, "status": "PASS"},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
