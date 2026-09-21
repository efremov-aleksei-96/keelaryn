from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable


REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from keelaryn_core.operation_hub_pre_apply_profile import (  # noqa: E402
    PROFILE_NAME,
    HubPreApplyProfileError,
    read_hub_pre_apply_profile,
)
from materialize_payload import (  # noqa: E402
    PayloadMaterializeError,
    verify_release_directory,
)


SCHEMA = "keelaryn.operation-control-update.v1"
PREPARED_SCHEMA = "keelaryn.operation-control-update-prepared.v1"
COMPLETED_SCHEMA = "keelaryn.operation-control-update-completed.v1"
ROLLED_BACK_SCHEMA = "keelaryn.operation-control-update-rolled-back.v1"

PERSISTENT_UNITS = (
    "keelaryn-operation-transport.service",
    "keelaryn-operation-agent.service",
)
WORKER_UNIT = "keelaryn-hub-preapply.service"
SERVICE_STABILITY_SECONDS = 12.0

_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TXDIR = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_EXECUTION = {"SUCCEEDED", "FAILED", "RECOVERY_REQUIRED"}


class ControlPlaneUpdateError(RuntimeError):
    pass


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _require_root() -> None:
    if os.name == "posix" and os.geteuid() != 0:
        raise ControlPlaneUpdateError("control-plane update requires root")


def _owned_dir(
    path: Path,
    label: str,
    *,
    exact_mode: int | None = None,
    create: bool = False,
) -> Path:
    path = path.absolute()
    if create and not path.exists() and not path.is_symlink():
        path.mkdir(parents=True, mode=0o700)
        if os.name == "posix":
            os.chmod(path, 0o700)
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ControlPlaneUpdateError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise ControlPlaneUpdateError(f"{label} must be one real directory")
    if os.name == "posix" and info.st_uid != os.geteuid():
        raise ControlPlaneUpdateError(f"{label} owner mismatch")
    mode = stat.S_IMODE(info.st_mode)
    if exact_mode is not None and mode != exact_mode:
        raise ControlPlaneUpdateError(
            f"{label} mode is not exact {exact_mode:04o}"
        )
    if exact_mode is None and mode & 0o022:
        raise ControlPlaneUpdateError(
            f"{label} must not be group/world writable"
        )
    return path


def _regular(
    path: Path,
    label: str,
    *,
    mode: int,
    expected: bytes | None = None,
) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ControlPlaneUpdateError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ControlPlaneUpdateError(f"{label} must be one regular file")
    if os.name == "posix" and info.st_uid != os.geteuid():
        raise ControlPlaneUpdateError(f"{label} owner mismatch")
    if stat.S_IMODE(info.st_mode) != mode:
        raise ControlPlaneUpdateError(
            f"{label} mode is not exact {mode:04o}"
        )
    if expected is not None and path.read_bytes() != expected:
        raise ControlPlaneUpdateError(f"{label} bytes mismatch")
    return path


def _readlink(path: Path, label: str) -> str:
    if not path.is_symlink():
        raise ControlPlaneUpdateError(
            f"{label} must be one canonical symlink"
        )
    if os.name == "posix" and path.lstat().st_uid != os.geteuid():
        raise ControlPlaneUpdateError(f"{label} owner mismatch")
    try:
        value = os.readlink(path)
    except OSError as exc:
        raise ControlPlaneUpdateError(f"{label} cannot be read") from exc
    return value


def _atomic_file(path: Path, raw: bytes, mode: int) -> None:
    parent = _owned_dir(path.parent, "atomic file parent")
    temp = parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(temp, flags, mode)
        try:
            if os.name == "posix":
                os.fchmod(fd, mode)
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                if written <= 0:
                    raise ControlPlaneUpdateError(
                        "atomic file write made no progress"
                    )
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, path)
        _fsync_dir(parent)
    finally:
        temp.unlink(missing_ok=True)
    _regular(path, "atomic file", mode=mode, expected=raw)


def _exclusive_file(path: Path, raw: bytes, mode: int) -> None:
    parent = _owned_dir(path.parent, "exclusive file parent")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise ControlPlaneUpdateError(
            f"refuses to replace existing path: {path.name}"
        ) from exc
    try:
        if os.name == "posix":
            os.fchmod(fd, mode)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise ControlPlaneUpdateError(
                    "exclusive file write made no progress"
                )
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(parent)
    _regular(path, "exclusive file", mode=mode, expected=raw)


def _atomic_symlink(path: Path, target: str) -> None:
    parent = _owned_dir(path.parent, "selector parent")
    temp = parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        os.symlink(target, temp)
        os.replace(temp, path)
        _fsync_dir(parent)
    finally:
        temp.unlink(missing_ok=True)
    if _readlink(path, "control-current") != target:
        raise ControlPlaneUpdateError("control-current swap verification failed")


def _remove_exact(path: Path, raw: bytes, mode: int, label: str) -> None:
    if not path.exists() and not path.is_symlink():
        return
    _regular(path, label, mode=mode, expected=raw)
    path.unlink()
    _fsync_dir(path.parent)


def _json_private(path: Path, label: str) -> dict[str, Any]:
    raw = _regular(path, label, mode=0o600).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlPlaneUpdateError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise ControlPlaneUpdateError(f"{label} is not canonical JSON")
    return value


def _write_record(path: Path, value: dict[str, Any]) -> None:
    _exclusive_file(path, _canonical(value), 0o600)


def _systemctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["systemctl", *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControlPlaneUpdateError("systemctl outcome is uncertain") from exc


def _must_systemctl(args: list[str]) -> None:
    completed = _systemctl(args)
    if completed.returncode != 0:
        raise ControlPlaneUpdateError(
            "systemctl operation failed: " + " ".join(args)
        )


def _is_active(unit: str) -> bool:
    completed = _systemctl(["is-active", "--quiet", unit])
    if completed.returncode == 0:
        return True
    if completed.returncode in {3, 4}:
        return False
    raise ControlPlaneUpdateError("systemctl active-state probe failed")


def _enabled_state(unit: str) -> str:
    completed = _systemctl(["is-enabled", unit])
    state = completed.stdout.strip()
    if state in {
        "enabled",
        "enabled-runtime",
        "disabled",
        "static",
        "indirect",
        "generated",
        "masked",
        "masked-runtime",
        "not-found",
    }:
        return state
    raise ControlPlaneUpdateError("systemctl enabled-state probe failed")


def _restart_count(unit: str) -> int:
    completed = _systemctl(
        ["show", unit, "--property=NRestarts", "--value"]
    )
    if completed.returncode != 0 or not completed.stdout.strip().isdigit():
        raise ControlPlaneUpdateError("systemctl restart-count probe failed")
    return int(completed.stdout.strip())


def _validate_oid(value: str, label: str) -> str:
    if _OID.fullmatch(value) is None:
        raise ControlPlaneUpdateError(f"{label} is invalid")
    return value


def _validate_sha(value: str, label: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ControlPlaneUpdateError(f"{label} is invalid")
    return value


def _production_target(path: Path) -> str:
    target = _readlink(path, "production current")
    if re.fullmatch(r"releases/[0-9a-f]{40}", target) is None:
        raise ControlPlaneUpdateError(
            "production current target is not canonical"
        )
    return target


def _operation_runtime_idle(operation_root: Path) -> None:
    root = _owned_dir(
        operation_root,
        "operation runtime root",
        exact_mode=0o700,
    )
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name == "LATEST":
            _regular(entry, "operation runtime LATEST", mode=0o600)
            continue
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or re.fullmatch(r"[0-9a-f]{32}", entry.name) is None
        ):
            raise ControlPlaneUpdateError(
                "operation runtime contains unexpected material"
            )
        if os.name == "posix":
            info = entry.stat(follow_symlinks=False)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ControlPlaneUpdateError(
                    "operation directory ownership/mode mismatch"
                )
        state = _json_private(entry / "state.json", "operation state")
        if state.get("execution_state") not in _TERMINAL_EXECUTION:
            raise ControlPlaneUpdateError(
                "control-plane update refuses while an operation is nonterminal"
            )


def _transport_inbox_idle(transport_root: Path) -> None:
    root = transport_root.absolute()
    inbox = root / "inbox"
    if root.is_symlink() or not root.is_dir():
        raise ControlPlaneUpdateError("transport root is invalid")
    if inbox.is_symlink() or not inbox.is_dir():
        raise ControlPlaneUpdateError("transport inbox is invalid")
    pending = [
        item
        for item in inbox.iterdir()
        if item.name not in {".", ".."}
    ]
    if pending:
        raise ControlPlaneUpdateError(
            "control-plane update refuses with pending transport requests"
        )


def _transaction_digest(
    *,
    old_source: str,
    old_payload: str,
    new_source: str,
    new_payload: str,
    profile_sha: str,
    production_target: str,
) -> str:
    value = {
        "schema": SCHEMA,
        "old_source_commit": old_source,
        "old_payload_sha256": old_payload,
        "new_source_commit": new_source,
        "new_payload_sha256": new_payload,
        "profile_sha256": profile_sha,
        "production_current_target": production_target,
    }
    return _sha(_canonical(value))


def _transaction_paths(
    update_root: Path,
    digest: str,
) -> tuple[Path, Path, Path, Path]:
    tx = update_root / digest
    return (
        tx,
        tx / "PREPARED.json",
        tx / "COMPLETED.json",
        tx / "ROLLED_BACK.json",
    )


def _assert_no_foreign_incomplete(update_root: Path, digest: str) -> None:
    for entry in update_root.iterdir():
        if entry.name == digest:
            continue
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or _TXDIR.fullmatch(entry.name) is None
        ):
            raise ControlPlaneUpdateError(
                "control update root contains foreign material"
            )
        prepared = entry / "PREPARED.json"
        completed = entry / "COMPLETED.json"
        rolled = entry / "ROLLED_BACK.json"
        if prepared.exists() and not (completed.exists() or rolled.exists()):
            raise ControlPlaneUpdateError(
                "another control-plane update is incomplete"
            )


def _release_identity(
    release: Path,
    source: str,
    payload: str,
) -> dict[str, Any]:
    try:
        value = verify_release_directory(
            release,
            expected_source_commit=source,
            expected_payload_sha256=payload,
        )
    except PayloadMaterializeError as exc:
        raise ControlPlaneUpdateError(
            "qualified control release validation failed"
        ) from exc
    if release.name != source:
        raise ControlPlaneUpdateError("release directory identity mismatch")
    return value


def _unit_bytes(release: Path, name: str) -> bytes:
    path = release / "deploy" / "zero-based-vps" / name
    if path.is_symlink() or not path.is_file():
        raise ControlPlaneUpdateError(
            f"qualified unit missing/not regular: {name}"
        )
    return path.read_bytes()


def _verify_services(
    *,
    active_probe: Callable[[str], bool],
    enabled_probe: Callable[[str], str],
    restart_probe: Callable[[str], int],
    restart_anchor: dict[str, int] | None = None,
) -> dict[str, int]:
    observed: dict[str, int] = {}
    for unit in PERSISTENT_UNITS:
        if not active_probe(unit):
            raise ControlPlaneUpdateError(
                f"persistent operation-control unit is inactive: {unit}"
            )
        if enabled_probe(unit) not in {"enabled", "enabled-runtime"}:
            raise ControlPlaneUpdateError(
                f"persistent operation-control unit is not enabled: {unit}"
            )
        observed[unit] = restart_probe(unit)
        if (
            restart_anchor is not None
            and observed[unit] != restart_anchor[unit]
        ):
            raise ControlPlaneUpdateError(
                f"operation-control unit restarted unexpectedly: {unit}"
            )
    worker_state = enabled_probe(WORKER_UNIT)
    if worker_state in {"enabled", "enabled-runtime"}:
        raise ControlPlaneUpdateError(
            "Hub pre-apply worker must not be enabled"
        )
    if active_probe(WORKER_UNIT):
        raise ControlPlaneUpdateError(
            "Hub pre-apply worker must be inactive outside an operation"
        )
    return observed


def _live_boundary(
    *,
    old_release: Path,
    new_release: Path,
    old_source: str,
    new_source: str,
    control_current: Path,
    unit_dir: Path,
    control_root: Path,
    profile_raw: bytes,
) -> str:
    target = _readlink(control_current, "control-current")
    persistent_old = all(
        (unit_dir / name).is_file()
        and not (unit_dir / name).is_symlink()
        and (unit_dir / name).read_bytes() == _unit_bytes(old_release, name)
        for name in PERSISTENT_UNITS
    )
    persistent_new = all(
        (unit_dir / name).is_file()
        and not (unit_dir / name).is_symlink()
        and (unit_dir / name).read_bytes() == _unit_bytes(new_release, name)
        for name in PERSISTENT_UNITS
    )
    worker = unit_dir / WORKER_UNIT
    profile = control_root / PROFILE_NAME
    worker_absent = not worker.exists() and not worker.is_symlink()
    profile_absent = not profile.exists() and not profile.is_symlink()
    worker_new = (
        worker.is_file()
        and not worker.is_symlink()
        and worker.read_bytes() == _unit_bytes(new_release, WORKER_UNIT)
    )
    profile_new = (
        profile.is_file()
        and not profile.is_symlink()
        and profile.read_bytes() == profile_raw
    )

    if (
        target == f"releases/{old_source}"
        and persistent_old
        and worker_absent
        and profile_absent
    ):
        return "OLD_EXACT"
    if (
        target == f"releases/{new_source}"
        and persistent_new
        and worker_new
        and profile_new
    ):
        return "NEW_EXACT"
    return "PARTIAL"


def _verify_predecessor_commit_boundary(
    *,
    old_release: Path,
    old_source: str,
    control_current: Path,
    production_current: Path,
    production_before: str,
    unit_dir: Path,
    credential_path: Path,
    credential_sha: str,
    operation_control_root: Path,
    operation_root: Path,
    transport_root: Path,
) -> None:
    # This check runs only after transport/agent are stopped, immediately
    # before the first successor byte is published.
    _operation_runtime_idle(operation_root)
    _transport_inbox_idle(transport_root)

    if _production_target(production_current) != production_before:
        raise ControlPlaneUpdateError(
            "production current changed at control update commit boundary"
        )
    if _readlink(control_current, "control-current") != f"releases/{old_source}":
        raise ControlPlaneUpdateError(
            "control-current changed at control update commit boundary"
        )
    if _sha(
        _regular(
            credential_path,
            "GitHub operations credential",
            mode=0o600,
        ).read_bytes()
    ) != credential_sha:
        raise ControlPlaneUpdateError(
            "GitHub operations credential changed at commit boundary"
        )

    for name in PERSISTENT_UNITS:
        _regular(
            unit_dir / name,
            f"predecessor unit {name}",
            mode=0o644,
            expected=_unit_bytes(old_release, name),
        )

    worker = unit_dir / WORKER_UNIT
    if worker.exists() or worker.is_symlink():
        raise ControlPlaneUpdateError(
            "Hub pre-apply worker appeared before commit boundary"
        )

    profile = operation_control_root / PROFILE_NAME
    if profile.exists() or profile.is_symlink():
        raise ControlPlaneUpdateError(
            "preauthorization profile appeared before commit boundary"
        )


def update_control_plane(
    *,
    install_root: Path,
    unit_dir: Path,
    credential_path: Path,
    operation_control_root: Path,
    operation_root: Path,
    transport_root: Path,
    update_root: Path,
    profile_source: Path,
    expected_old_source_commit: str,
    expected_old_payload_sha256: str,
    expected_new_source_commit: str,
    expected_new_payload_sha256: str,
    systemctl: Callable[[list[str]], None] = _must_systemctl,
    active_probe: Callable[[str], bool] = _is_active,
    enabled_probe: Callable[[str], str] = _enabled_state,
    restart_probe: Callable[[str], int] = _restart_count,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    _require_root()
    old_source = _validate_oid(
        expected_old_source_commit,
        "expected old source commit",
    )
    new_source = _validate_oid(
        expected_new_source_commit,
        "expected new source commit",
    )
    old_payload = _validate_sha(
        expected_old_payload_sha256,
        "expected old payload SHA-256",
    )
    new_payload = _validate_sha(
        expected_new_payload_sha256,
        "expected new payload SHA-256",
    )
    if old_source == new_source:
        raise ControlPlaneUpdateError(
            "control-plane update requires a distinct successor source"
        )

    install_root = _owned_dir(
        install_root,
        "install root",
    )
    releases = _owned_dir(
        install_root / "releases",
        "release root",
    )
    old_release = releases / old_source
    new_release = releases / new_source
    _release_identity(old_release, old_source, old_payload)
    _release_identity(new_release, new_source, new_payload)

    production_current = install_root / "current"
    control_current = install_root / "control-current"
    production_before = _production_target(production_current)
    if _readlink(control_current, "control-current") != f"releases/{old_source}":
        raise ControlPlaneUpdateError(
            "control-current is not exact expected predecessor"
        )

    unit_dir = _owned_dir(unit_dir, "systemd unit directory")
    operation_control_root = _owned_dir(
        operation_control_root,
        "operation control root",
        exact_mode=0o700,
    )
    _operation_runtime_idle(operation_root)
    _transport_inbox_idle(transport_root)

    credential_raw = _regular(
        credential_path,
        "GitHub operations credential",
        mode=0o600,
    ).read_bytes()
    credential_sha = _sha(credential_raw)

    for name in PERSISTENT_UNITS:
        _regular(
            unit_dir / name,
            f"installed predecessor unit {name}",
            mode=0o644,
            expected=_unit_bytes(old_release, name),
        )
    worker_path = unit_dir / WORKER_UNIT
    if worker_path.exists() or worker_path.is_symlink():
        raise ControlPlaneUpdateError(
            "Hub pre-apply worker unit must be absent before successor update"
        )

    try:
        profile = read_hub_pre_apply_profile(profile_source)
    except HubPreApplyProfileError as exc:
        raise ControlPlaneUpdateError(
            "Hub pre-apply preauthorization profile is invalid"
        ) from exc
    profile_raw = profile_source.read_bytes()
    if profile["control_source_commit"] != new_source:
        raise ControlPlaneUpdateError(
            "preauthorization profile is not bound to successor control source"
        )
    profile_destination = operation_control_root / PROFILE_NAME
    if profile_destination.exists() or profile_destination.is_symlink():
        raise ControlPlaneUpdateError(
            "preauthorization destination must be absent before update"
        )

    if not all(active_probe(unit) for unit in PERSISTENT_UNITS):
        raise ControlPlaneUpdateError(
            "predecessor operation-control services must be active"
        )
    if any(
        enabled_probe(unit) not in {"enabled", "enabled-runtime"}
        for unit in PERSISTENT_UNITS
    ):
        raise ControlPlaneUpdateError(
            "predecessor operation-control services must be enabled"
        )

    update_root = _owned_dir(
        update_root,
        "control update root",
        exact_mode=0o700,
        create=True,
    )
    digest = _transaction_digest(
        old_source=old_source,
        old_payload=old_payload,
        new_source=new_source,
        new_payload=new_payload,
        profile_sha=_sha(profile_raw),
        production_target=production_before,
    )
    _assert_no_foreign_incomplete(update_root, digest)
    tx, prepared_path, completed_path, rolled_path = _transaction_paths(
        update_root,
        digest,
    )
    if not tx.exists() and not tx.is_symlink():
        tx.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(tx, 0o700)
        _fsync_dir(update_root)
    tx = _owned_dir(tx, "control update transaction", exact_mode=0o700)

    old_unit_sha = {
        name: _sha(_unit_bytes(old_release, name))
        for name in PERSISTENT_UNITS
    }
    new_unit_sha = {
        name: _sha(_unit_bytes(new_release, name))
        for name in PERSISTENT_UNITS
    }
    worker_raw = _unit_bytes(new_release, WORKER_UNIT)
    worker_sha = _sha(worker_raw)
    prepared = {
        "schema": PREPARED_SCHEMA,
        "transaction_id": digest,
        "old_source_commit": old_source,
        "old_payload_sha256": old_payload,
        "new_source_commit": new_source,
        "new_payload_sha256": new_payload,
        "production_current_target": production_before,
        "credential_sha256": credential_sha,
        "profile_sha256": _sha(profile_raw),
        "old_unit_sha256": old_unit_sha,
        "new_unit_sha256": new_unit_sha,
        "worker_unit_sha256": worker_sha,
    }
    prepared_raw = _canonical(prepared)

    if completed_path.exists() or completed_path.is_symlink():
        completed = _json_private(
            completed_path,
            "completed control update authority",
        )
        if (
            completed.get("schema") != COMPLETED_SCHEMA
            or completed.get("transaction_id") != digest
        ):
            raise ControlPlaneUpdateError(
                "completed control update authority mismatch"
            )
        if _canonical(_json_private(
            prepared_path,
            "prepared control update authority",
        )) != prepared_raw:
            raise ControlPlaneUpdateError(
                "completed control update PREPARED authority mismatch"
            )
        if _live_boundary(
            old_release=old_release,
            new_release=new_release,
            old_source=old_source,
            new_source=new_source,
            control_current=control_current,
            unit_dir=unit_dir,
            control_root=operation_control_root,
            profile_raw=profile_raw,
        ) != "NEW_EXACT":
            raise ControlPlaneUpdateError(
                "completed control update conflicts with live state"
            )
        _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
        )
        if _production_target(production_current) != production_before:
            raise ControlPlaneUpdateError(
                "production current changed after completed control update"
            )
        if _sha(_regular(
            credential_path,
            "GitHub operations credential",
            mode=0o600,
        ).read_bytes()) != credential_sha:
            raise ControlPlaneUpdateError(
                "GitHub operations credential changed after update"
            )
        return completed

    if rolled_path.exists() or rolled_path.is_symlink():
        raise ControlPlaneUpdateError(
            "same control-plane update previously rolled back; reconcile before retry"
        )

    if prepared_path.exists() or prepared_path.is_symlink():
        existing = _json_private(
            prepared_path,
            "prepared control update authority",
        )
        if _canonical(existing) != prepared_raw:
            raise ControlPlaneUpdateError(
                "prepared control update authority mismatch"
            )
        live = _live_boundary(
            old_release=old_release,
            new_release=new_release,
            old_source=old_source,
            new_source=new_source,
            control_current=control_current,
            unit_dir=unit_dir,
            control_root=operation_control_root,
            profile_raw=profile_raw,
        )
        if live == "NEW_EXACT":
            anchors = _verify_services(
                active_probe=active_probe,
                enabled_probe=enabled_probe,
                restart_probe=restart_probe,
            )
            sleeper(SERVICE_STABILITY_SECONDS)
            _verify_services(
                active_probe=active_probe,
                enabled_probe=enabled_probe,
                restart_probe=restart_probe,
                restart_anchor=anchors,
            )
            completed = {
                "schema": COMPLETED_SCHEMA,
                "transaction_id": digest,
                "production_current_unchanged": True,
                "control_current": "SUCCESSOR",
                "persistent_services": "ACTIVE_STABLE",
                "worker_unit": "STATIC_INACTIVE",
                "preauthorization": "EXACT",
                "credential_unchanged": True,
            }
            _write_record(completed_path, completed)
            return completed
        if live != "OLD_EXACT":
            raise ControlPlaneUpdateError(
                "incomplete control update is partial; read-only reconciliation required"
            )
    else:
        _write_record(prepared_path, prepared)

    rollback_needed = False
    try:
        rollback_needed = True

        # Freeze request intake/execution before changing qualified control bytes.
        for unit in reversed(PERSISTENT_UNITS):
            systemctl(["stop", unit])
        if any(active_probe(unit) for unit in PERSISTENT_UNITS):
            raise ControlPlaneUpdateError(
                "predecessor operation-control services did not stop"
            )

        _verify_predecessor_commit_boundary(
            old_release=old_release,
            old_source=old_source,
            control_current=control_current,
            production_current=production_current,
            production_before=production_before,
            unit_dir=unit_dir,
            credential_path=credential_path,
            credential_sha=credential_sha,
            operation_control_root=operation_control_root,
            operation_root=operation_root,
            transport_root=transport_root,
        )

        # Publish non-service authorities/worker first, then exact persistent units,
        # then swap the independent control selector.
        _exclusive_file(profile_destination, profile_raw, 0o600)
        _exclusive_file(worker_path, worker_raw, 0o644)
        for name in PERSISTENT_UNITS:
            _atomic_file(
                unit_dir / name,
                _unit_bytes(new_release, name),
                0o644,
            )
        _atomic_symlink(
            control_current,
            f"releases/{new_source}",
        )

        systemctl(["daemon-reload"])
        for unit in PERSISTENT_UNITS:
            systemctl(["start", unit])

        anchors = _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
        )
        sleeper(SERVICE_STABILITY_SECONDS)
        _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
            restart_anchor=anchors,
        )

        if _live_boundary(
            old_release=old_release,
            new_release=new_release,
            old_source=old_source,
            new_source=new_source,
            control_current=control_current,
            unit_dir=unit_dir,
            control_root=operation_control_root,
            profile_raw=profile_raw,
        ) != "NEW_EXACT":
            raise ControlPlaneUpdateError(
                "successor control-plane live boundary is not exact"
            )
        if _production_target(production_current) != production_before:
            raise ControlPlaneUpdateError(
                "production current changed during control-plane update"
            )
        if _sha(_regular(
            credential_path,
            "GitHub operations credential",
            mode=0o600,
        ).read_bytes()) != credential_sha:
            raise ControlPlaneUpdateError(
                "GitHub operations credential changed during update"
            )

        completed = {
            "schema": COMPLETED_SCHEMA,
            "transaction_id": digest,
            "production_current_unchanged": True,
            "control_current": "SUCCESSOR",
            "persistent_services": "ACTIVE_STABLE",
            "worker_unit": "STATIC_INACTIVE",
            "preauthorization": "EXACT",
            "credential_unchanged": True,
        }
        _write_record(completed_path, completed)
        rollback_needed = False
        return completed

    except BaseException as original:
        if not rollback_needed:
            raise
        rollback_error: BaseException | None = None
        try:
            for unit in reversed(PERSISTENT_UNITS):
                try:
                    systemctl(["stop", unit])
                except BaseException:
                    pass
            if any(active_probe(unit) for unit in PERSISTENT_UNITS):
                raise ControlPlaneUpdateError(
                    "cannot prove successor services stopped before rollback"
                )

            _atomic_symlink(
                control_current,
                f"releases/{old_source}",
            )
            for name in PERSISTENT_UNITS:
                _atomic_file(
                    unit_dir / name,
                    _unit_bytes(old_release, name),
                    0o644,
                )
            _remove_exact(
                worker_path,
                worker_raw,
                0o644,
                "Hub pre-apply worker unit",
            )
            _remove_exact(
                profile_destination,
                profile_raw,
                0o600,
                "Hub pre-apply preauthorization profile",
            )

            systemctl(["daemon-reload"])
            for unit in PERSISTENT_UNITS:
                systemctl(["start", unit])

            anchors = _verify_services(
                active_probe=active_probe,
                enabled_probe=enabled_probe,
                restart_probe=restart_probe,
            )
            sleeper(SERVICE_STABILITY_SECONDS)
            _verify_services(
                active_probe=active_probe,
                enabled_probe=enabled_probe,
                restart_probe=restart_probe,
                restart_anchor=anchors,
            )
            if _live_boundary(
                old_release=old_release,
                new_release=new_release,
                old_source=old_source,
                new_source=new_source,
                control_current=control_current,
                unit_dir=unit_dir,
                control_root=operation_control_root,
                profile_raw=profile_raw,
            ) != "OLD_EXACT":
                raise ControlPlaneUpdateError(
                    "rollback did not restore exact predecessor boundary"
                )
            if _production_target(production_current) != production_before:
                raise ControlPlaneUpdateError(
                    "production current changed during rollback"
                )
            if _sha(_regular(
                credential_path,
                "GitHub operations credential",
                mode=0o600,
            ).read_bytes()) != credential_sha:
                raise ControlPlaneUpdateError(
                    "credential changed during rollback"
                )

            rolled = {
                "schema": ROLLED_BACK_SCHEMA,
                "transaction_id": digest,
                "production_current_unchanged": True,
                "control_current": "PREDECESSOR",
                "persistent_services": "ACTIVE_STABLE",
                "worker_unit": "ABSENT",
                "preauthorization": "ABSENT",
                "credential_unchanged": True,
                "failure_class": type(original).__name__,
            }
            _write_record(rolled_path, rolled)
        except BaseException as exc:
            rollback_error = exc

        if rollback_error is not None:
            raise ControlPlaneUpdateError(
                "control-plane update rollback is incomplete; read-only reconciliation required"
            ) from original
        raise ControlPlaneUpdateError(
            "control-plane update failed and rolled back exactly"
        ) from original


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-update"
    )
    parser.add_argument("--install-root", type=Path, default=Path("/opt/keelaryn"))
    parser.add_argument("--unit-dir", type=Path, default=Path("/etc/systemd/system"))
    parser.add_argument(
        "--credential-path",
        type=Path,
        default=Path(
            "/etc/keelaryn/operation-control/github-operations.env"
        ),
    )
    parser.add_argument(
        "--operation-control-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operation-control"),
    )
    parser.add_argument(
        "--operation-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operations"),
    )
    parser.add_argument(
        "--transport-root",
        type=Path,
        default=Path("/var/lib/keelaryn-operation-transport"),
    )
    parser.add_argument(
        "--update-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operation-control-updates"),
    )
    parser.add_argument("--profile-source", required=True, type=Path)
    parser.add_argument("--expected-old-source-commit", required=True)
    parser.add_argument("--expected-old-payload-sha256", required=True)
    parser.add_argument("--expected-new-source-commit", required=True)
    parser.add_argument("--expected-new-payload-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = update_control_plane(
            install_root=args.install_root,
            unit_dir=args.unit_dir,
            credential_path=args.credential_path,
            operation_control_root=args.operation_control_root,
            operation_root=args.operation_root,
            transport_root=args.transport_root,
            update_root=args.update_root,
            profile_source=args.profile_source,
            expected_old_source_commit=args.expected_old_source_commit,
            expected_old_payload_sha256=args.expected_old_payload_sha256,
            expected_new_source_commit=args.expected_new_source_commit,
            expected_new_payload_sha256=args.expected_new_payload_sha256,
        )
    except (ControlPlaneUpdateError, OSError) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-update-failure.v1",
                    "error_class": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
