from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from materialize_payload import PayloadMaterializeError, verify_release_directory


SCHEMA = "keelaryn.operation-control-recovery.v1"
PREPARED_SCHEMA = "keelaryn.operation-control-recovery-prepared.v1"
COMPLETED_SCHEMA = "keelaryn.operation-control-recovery-completed.v1"
BOOTSTRAP_TRANSACTION_SCHEMA = "keelaryn.operation-control-bootstrap-transaction.v1"
BOOTSTRAP_RECEIPT_SCHEMA = "keelaryn.operation-control-bootstrap-receipt.v1"
FAILED_BOOTSTRAP_SCHEMA = "keelaryn.operation-control-failed-bootstrap-recovery.v1"
FAILED_BOOTSTRAP_PREPARED_SCHEMA = "keelaryn.operation-control-failed-bootstrap-recovery-prepared.v1"
FAILED_BOOTSTRAP_COMPLETED_SCHEMA = "keelaryn.operation-control-failed-bootstrap-recovery-completed.v1"
FAILED_BOOTSTRAP_RUNTIME_LAYOUT = "R0004_FAILED_BOOTSTRAP_EXACT_V1"

UNIT_NAMES = (
    "keelaryn-operation-transport.service",
    "keelaryn-operation-agent.service",
)
_TOKEN = re.compile(r"^[A-Za-z0-9_]{20,255}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ACTOR = re.compile(r"^[A-Za-z0-9-]{1,39}$")
_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MARKER = re.compile(r"^transaction-c([01])-b([01])-([0-9a-f]{64})$")


class OperationControlRecoveryError(RuntimeError):
    pass


def _require_root() -> None:
    if os.geteuid() != 0:
        raise OperationControlRecoveryError("operation-control recovery requires root")


@dataclass(frozen=True)
class RecoverySpec:
    rejected_source_commit: str
    rejected_payload_sha256: str
    production_source_commit: str
    repository: str
    issue: int
    actors: str
    status_actor: str


@dataclass(frozen=True)
class RecoveryLayout:
    install_root: Path
    unit_dir: Path
    config_dir: Path
    bootstrap_root: Path
    recovery_root: Path
    transport_root: Path
    operation_root: Path
    operation_control_root: Path
    selector: Path
    deployment_state_root: Path
    mutation_gate_root: Path

    @property
    def rejected_release(self) -> Path:
        raise AssertionError("rejected_release requires a RecoverySpec")

    @property
    def current(self) -> Path:
        return self.install_root / "current"

    @property
    def control_current(self) -> Path:
        return self.install_root / "control-current"

    @property
    def credential(self) -> Path:
        return self.config_dir / "github-operations.env"

    @property
    def receipt(self) -> Path:
        return self.bootstrap_root / "bootstrap-receipt.json"


Systemctl = Callable[[list[str]], subprocess.CompletedProcess[str]]
BoundaryProbe = Callable[[], dict[str, str]]
ReleaseProbe = Callable[[Path, str, str], dict[str, Any]]


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _normalize_actors(value: str) -> str:
    actors = [item.strip() for item in value.split(",") if item.strip()]
    if not actors or any(_ACTOR.fullmatch(item) is None for item in actors):
        raise OperationControlRecoveryError("operation actor allowlist is invalid")
    if len(set(actors)) != len(actors):
        raise OperationControlRecoveryError("operation actor allowlist has duplicates")
    return ",".join(actors)


def _validate_spec(spec: RecoverySpec) -> RecoverySpec:
    if _OID.fullmatch(spec.rejected_source_commit) is None:
        raise OperationControlRecoveryError("rejected source commit is invalid")
    if _SHA256.fullmatch(spec.rejected_payload_sha256) is None:
        raise OperationControlRecoveryError("rejected payload SHA-256 is invalid")
    if _OID.fullmatch(spec.production_source_commit) is None:
        raise OperationControlRecoveryError("production source commit is invalid")
    if _REPOSITORY.fullmatch(spec.repository) is None:
        raise OperationControlRecoveryError("repository is invalid")
    if isinstance(spec.issue, bool) or spec.issue < 1:
        raise OperationControlRecoveryError("issue number is invalid")
    _normalize_actors(spec.actors)
    if _ACTOR.fullmatch(spec.status_actor) is None:
        raise OperationControlRecoveryError("status actor is invalid")
    return spec


def _service_identity() -> tuple[int, int]:
    try:
        account = pwd.getpwnam("keelaryn")
    except KeyError as exc:
        raise OperationControlRecoveryError(
            "keelaryn service account is missing"
        ) from exc
    try:
        group = grp.getgrnam("keelaryn")
    except KeyError as exc:
        raise OperationControlRecoveryError(
            "keelaryn service group is missing"
        ) from exc
    return account.pw_uid, group.gr_gid


def _directory_identity(
    path: Path,
    label: str,
    *,
    expected_uid: int,
    expected_gid: int,
    expected_mode: int = 0o700,
) -> list[Path] | None:
    path = path.absolute()
    if not path.exists() and not path.is_symlink():
        return None
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationControlRecoveryError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise OperationControlRecoveryError(f"{label} must be one real directory")
    if (
        info.st_uid != expected_uid
        or info.st_gid != expected_gid
        or stat.S_IMODE(info.st_mode) != expected_mode
    ):
        raise OperationControlRecoveryError(
            f"{label} owner/group/mode is not exact"
        )
    try:
        return list(path.iterdir())
    except OSError as exc:
        raise OperationControlRecoveryError(f"{label} cannot be enumerated") from exc


def _runtime_state(layout: RecoveryLayout) -> dict[str, str]:
    root_uid = os.geteuid()
    root_gid = os.getegid()
    service_uid, service_gid = _service_identity()

    transport_entries = _directory_identity(
        layout.transport_root,
        "operation transport runtime root",
        expected_uid=service_uid,
        expected_gid=service_gid,
    )
    if transport_entries is None:
        transport_state = "ABSENT"
    elif transport_entries:
        raise OperationControlRecoveryError(
            "operation transport runtime root contains unexpected material"
        )
    else:
        transport_state = "EXACT"

    operation_entries = _directory_identity(
        layout.operation_root,
        "operation runtime root",
        expected_uid=root_uid,
        expected_gid=root_gid,
    )
    if operation_entries is None:
        operation_state = "ABSENT"
    elif operation_entries:
        raise OperationControlRecoveryError(
            "operation runtime root contains unexpected material"
        )
    else:
        operation_state = "EXACT"

    control_entries = _directory_identity(
        layout.operation_control_root,
        "operation agent control root",
        expected_uid=root_uid,
        expected_gid=root_gid,
    )
    if control_entries is None:
        control_state = "ABSENT"
    else:
        allowed = {"processed", "rejected"}
        names = {entry.name for entry in control_entries}
        if not names.issubset(allowed):
            raise OperationControlRecoveryError(
                "operation agent control root contains unexpected material"
            )
        for name in sorted(names):
            child = layout.operation_control_root / name
            child_entries = _directory_identity(
                child,
                f"operation agent control {name} directory",
                expected_uid=root_uid,
                expected_gid=root_gid,
            )
            if child_entries is None:
                raise OperationControlRecoveryError(
                    f"operation agent control {name} directory disappeared"
                )
            if child_entries:
                raise OperationControlRecoveryError(
                    f"operation agent control {name} directory is not empty"
                )
        control_state = "EXACT" if names == allowed else "PARTIAL_EXACT"

    return {
        "transport_root": transport_state,
        "operation_root": operation_state,
        "operation_control_root": control_state,
    }


def _remove_runtime_state(layout: RecoveryLayout) -> None:
    state = _runtime_state(layout)

    if state["operation_control_root"] != "ABSENT":
        for name in ("processed", "rejected"):
            child = layout.operation_control_root / name
            if child.exists() or child.is_symlink():
                _unlink_pinned(child, directory=True)
        if (
            layout.operation_control_root.exists()
            or layout.operation_control_root.is_symlink()
        ):
            _unlink_pinned(layout.operation_control_root, directory=True)

    if state["operation_root"] != "ABSENT":
        _unlink_pinned(layout.operation_root, directory=True)

    if state["transport_root"] != "ABSENT":
        _unlink_pinned(layout.transport_root, directory=True)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_directory(path: Path, label: str) -> Path:
    path = path.absolute()
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationControlRecoveryError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise OperationControlRecoveryError(f"{label} must be one real directory")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise OperationControlRecoveryError(f"{label} must be current-user owned mode 0700")
    return path


def _regular(path: Path, label: str, mode: int) -> bytes:
    path = path.absolute()
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationControlRecoveryError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise OperationControlRecoveryError(f"{label} must be one regular file")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode:
        raise OperationControlRecoveryError(
            f"{label} must be current-user owned mode {mode:04o}"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise OperationControlRecoveryError(f"{label} cannot be read") from exc


def _pin(path: Path) -> tuple[int, tuple[int, int, int]]:
    o_path = getattr(os, "O_PATH", 0)
    o_nofollow = getattr(os, "O_NOFOLLOW", 0)
    o_cloexec = getattr(os, "O_CLOEXEC", 0)
    if not o_path or not o_nofollow:
        raise OperationControlRecoveryError(
            "Linux O_PATH/O_NOFOLLOW support is required for recovery ownership pins"
        )
    try:
        fd = os.open(path, o_path | o_nofollow | o_cloexec)
    except OSError as exc:
        raise OperationControlRecoveryError(f"cannot pin recovery path: {path}") from exc
    info = os.fstat(fd)
    identity = (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
    try:
        current = path.stat(follow_symlinks=False)
    except OSError:
        os.close(fd)
        raise
    observed = (current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode))
    if observed != identity:
        os.close(fd)
        raise OperationControlRecoveryError(f"recovery path changed while pinning: {path}")
    return fd, identity


def _unlink_pinned(path: Path, *, directory: bool = False) -> None:
    fd, identity = _pin(path)
    try:
        current = path.stat(follow_symlinks=False)
        observed = (current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode))
        if observed != identity:
            raise OperationControlRecoveryError(
                f"recovery path identity changed before removal: {path}"
            )
        if directory:
            path.rmdir()
        else:
            path.unlink()
        _fsync_directory(path.parent)
    finally:
        os.close(fd)


def _write_exclusive_private(path: Path, value: dict[str, Any]) -> None:
    raw = _canonical_json(value)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        existing = _regular(path, path.name, 0o600)
        if existing != raw:
            raise OperationControlRecoveryError(
                f"existing recovery authority conflicts: {path.name}"
            )
        return
    except OSError as exc:
        raise OperationControlRecoveryError(
            f"cannot create recovery authority: {path.name}"
        ) from exc
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    _fsync_directory(path.parent)


def _read_canonical_record(path: Path, schema: str) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    raw = _regular(path, path.name, 0o600)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationControlRecoveryError(
            f"{path.name} is not canonical recovery JSON"
        ) from exc
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise OperationControlRecoveryError(f"{path.name} recovery schema mismatch")
    if raw != _canonical_json(value):
        raise OperationControlRecoveryError(f"{path.name} is not canonical JSON")
    return value


def _credential_bytes(
    *,
    token: str,
    repository: str,
    issue: int,
    actors: str,
    status_actor: str,
) -> bytes:
    if _TOKEN.fullmatch(token) is None:
        raise OperationControlRecoveryError("credential token format is invalid")
    actors = _normalize_actors(actors)
    if _REPOSITORY.fullmatch(repository) is None:
        raise OperationControlRecoveryError("credential repository is invalid")
    if isinstance(issue, bool) or issue < 1:
        raise OperationControlRecoveryError("credential issue is invalid")
    if _ACTOR.fullmatch(status_actor) is None:
        raise OperationControlRecoveryError("credential status actor is invalid")
    return (
        f"KEELARYN_GITHUB_OPERATIONS_TOKEN={token}\n"
        f"KEELARYN_GITHUB_OPERATIONS_REPOSITORY={repository}\n"
        f"KEELARYN_GITHUB_OPERATIONS_ISSUE={issue}\n"
        f"KEELARYN_GITHUB_OPERATIONS_ACTORS={actors}\n"
        f"KEELARYN_GITHUB_OPERATIONS_STATUS_ACTOR={status_actor}\n"
    ).encode("ascii")


def _credential_identity(raw: bytes, spec: RecoverySpec) -> str:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise OperationControlRecoveryError("credential is not ASCII") from exc
    lines = text.splitlines()
    prefixes = (
        "KEELARYN_GITHUB_OPERATIONS_TOKEN=",
        "KEELARYN_GITHUB_OPERATIONS_REPOSITORY=",
        "KEELARYN_GITHUB_OPERATIONS_ISSUE=",
        "KEELARYN_GITHUB_OPERATIONS_ACTORS=",
        "KEELARYN_GITHUB_OPERATIONS_STATUS_ACTOR=",
    )
    if len(lines) != len(prefixes) or any(
        not line.startswith(prefix) for line, prefix in zip(lines, prefixes)
    ):
        raise OperationControlRecoveryError("credential layout is not exact")
    token = lines[0][len(prefixes[0]):]
    expected = _credential_bytes(
        token=token,
        repository=spec.repository,
        issue=spec.issue,
        actors=spec.actors,
        status_actor=spec.status_actor,
    )
    if raw != expected:
        raise OperationControlRecoveryError(
            "credential metadata differs from rejected transaction authority"
        )
    return sha256(raw).hexdigest()


def _expected_receipt(spec: RecoverySpec) -> bytes:
    return _canonical_json(
        {
            "schema": BOOTSTRAP_RECEIPT_SCHEMA,
            "source_commit": spec.rejected_source_commit,
            "payload_sha256": spec.rejected_payload_sha256,
            "repository": spec.repository,
            "issue": spec.issue,
            "actors": _normalize_actors(spec.actors),
            "status_actor": spec.status_actor,
            "production_current_unchanged": True,
            "control_current_exact": True,
            "transport_active": True,
            "agent_active": True,
        }
    )


def _expected_marker(spec: RecoverySpec, credential_sha256: str) -> str:
    digest = sha256(
        _canonical_json(
            {
                "schema": BOOTSTRAP_TRANSACTION_SCHEMA,
                "source_commit": spec.rejected_source_commit,
                "payload_sha256": spec.rejected_payload_sha256,
                "repository": spec.repository,
                "issue": spec.issue,
                "actors": _normalize_actors(spec.actors),
                "status_actor": spec.status_actor,
                "credential_sha256": credential_sha256,
            }
        )
    ).hexdigest()
    return f"transaction-c0-b0-{digest}"


def _default_systemctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["systemctl", *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperationControlRecoveryError("systemctl invocation failed") from exc


def _service_state(unit: str, systemctl: Systemctl) -> dict[str, str]:
    active = systemctl(["is-active", unit])
    active_text = (active.stdout or "").strip()
    if active.returncode == 0 and active_text == "active":
        active_state = "active"
    elif active.returncode in {3, 4} and active_text in {"inactive", "failed", "unknown"}:
        active_state = active_text
    else:
        raise OperationControlRecoveryError(
            f"cannot classify active state for {unit}"
        )

    enabled = systemctl(["is-enabled", unit])
    enabled_text = (enabled.stdout or "").strip()
    if enabled.returncode == 0 and enabled_text == "enabled":
        enabled_state = "enabled"
    elif enabled.returncode != 0 and enabled_text in {
        "disabled",
        "not-found",
        "static",
        "masked",
        "indirect",
    }:
        enabled_state = enabled_text
    else:
        raise OperationControlRecoveryError(
            f"cannot classify enablement state for {unit}"
        )
    return {"active": active_state, "enabled": enabled_state}


def _json_command(args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperationControlRecoveryError("production boundary command failed") from exc
    if result.returncode != 0:
        raise OperationControlRecoveryError("production boundary command returned nonzero")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OperationControlRecoveryError("production boundary command returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise OperationControlRecoveryError("production boundary command returned non-object JSON")
    return value


def _production_boundary(spec: RecoverySpec, layout: RecoveryLayout) -> dict[str, str]:
    expected = f"releases/{spec.production_source_commit}"
    if not layout.current.is_symlink() or os.readlink(layout.current) != expected:
        raise OperationControlRecoveryError(
            "production current is not exact expected authority"
        )

    writer = _default_systemctl(["is-active", "keelaryn-drive.service"])
    if (
        writer.returncode != 3
        or (writer.stdout or "").strip() != "inactive"
    ):
        raise OperationControlRecoveryError(
            "production writer is not exact INACTIVE"
        )

    tool = (
        layout.install_root
        / "releases"
        / spec.production_source_commit
        / "deploy"
        / "zero-based-vps"
        / "hub_cutover.py"
    )
    status = _json_command(
        [
            sys.executable,
            "-B",
            str(tool),
            "--selector-path",
            str(layout.selector),
            "--state-root",
            str(layout.deployment_state_root),
            "--mutation-gate-root",
            str(layout.mutation_gate_root),
            "--source-commit",
            spec.production_source_commit,
            "status",
        ]
    )
    if status.get("status") != "PREPARED":
        raise OperationControlRecoveryError(
            "production Hub cutover is not exact PREPARED"
        )
    return {
        "current_source": spec.production_source_commit,
        "writer": "INACTIVE",
        "hub_cutover": "PREPARED",
    }


def _release_identity(path: Path, source: str, payload: str) -> dict[str, Any]:
    try:
        return verify_release_directory(
            path,
            expected_source_commit=source,
            expected_payload_sha256=payload,
        )
    except PayloadMaterializeError as exc:
        raise OperationControlRecoveryError(
            "rejected release identity validation failed"
        ) from exc


def _recovery_paths(layout: RecoveryLayout, spec: RecoverySpec) -> tuple[Path, Path]:
    stem = f"rejected-{spec.rejected_source_commit}"
    return (
        layout.recovery_root / f"{stem}.prepared.json",
        layout.recovery_root / f"{stem}.completed.json",
    )


def _ensure_recovery_root(layout: RecoveryLayout) -> None:
    root = layout.recovery_root.absolute()
    if not root.exists() and not root.is_symlink():
        root.mkdir(parents=True, mode=0o700)
        os.chmod(root, 0o700)
        _fsync_directory(root.parent)
    _private_directory(root, "operation recovery root")


def _unit_expected(release: Path, unit: str) -> bytes:
    path = release / "deploy" / "zero-based-vps" / unit
    if path.is_symlink() or not path.is_file():
        raise OperationControlRecoveryError(f"rejected release unit is invalid: {unit}")
    return path.read_bytes()


def _layout_authority(layout: RecoveryLayout) -> dict[str, str]:
    paths = {
        "install_root": layout.install_root,
        "unit_dir": layout.unit_dir,
        "config_dir": layout.config_dir,
        "bootstrap_root": layout.bootstrap_root,
        "recovery_root": layout.recovery_root,
        "transport_root": layout.transport_root,
        "operation_root": layout.operation_root,
        "operation_control_root": layout.operation_control_root,
        "selector": layout.selector,
        "deployment_state_root": layout.deployment_state_root,
        "mutation_gate_root": layout.mutation_gate_root,
    }
    authority: dict[str, str] = {}
    for name, path in paths.items():
        raw = str(path)
        absolute = str(path.absolute())
        if raw != absolute:
            raise OperationControlRecoveryError(
                f"recovery layout path must be absolute: {name}"
            )
        authority[name] = absolute
    return authority


def _prepared_static(
    spec: RecoverySpec,
    *,
    marker: str,
    credential_sha256: str,
    receipt_sha256: str,
    unit_sha256: dict[str, str],
    layout: RecoveryLayout,
) -> dict[str, Any]:
    return {
        "schema": PREPARED_SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "production_source_commit": spec.production_source_commit,
        "repository": spec.repository,
        "issue": spec.issue,
        "actors": _normalize_actors(spec.actors),
        "status_actor": spec.status_actor,
        "bootstrap_transaction_marker": marker,
        "credential_sha256": credential_sha256,
        "receipt_sha256": receipt_sha256,
        "unit_sha256": unit_sha256,
        "control_current_target": f"releases/{spec.rejected_source_commit}",
        "config_preexisting": False,
        "bootstrap_root_preexisting": False,
        "runtime_state_layout": "R0003_EMPTY_EXACT",
        "filesystem_layout": _layout_authority(layout),
    }


def _validate_prepared(
    prepared: dict[str, Any],
    spec: RecoverySpec,
    unit_sha256: dict[str, str],
    receipt_sha256: str,
    layout: RecoveryLayout,
) -> None:
    required = {
        "schema": PREPARED_SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "production_source_commit": spec.production_source_commit,
        "repository": spec.repository,
        "issue": spec.issue,
        "actors": _normalize_actors(spec.actors),
        "status_actor": spec.status_actor,
        "receipt_sha256": receipt_sha256,
        "unit_sha256": unit_sha256,
        "control_current_target": f"releases/{spec.rejected_source_commit}",
        "config_preexisting": False,
        "bootstrap_root_preexisting": False,
        "runtime_state_layout": "R0003_EMPTY_EXACT",
        "filesystem_layout": _layout_authority(layout),
    }
    exact_keys = set(required) | {
        "credential_sha256",
        "bootstrap_transaction_marker",
    }
    if set(prepared) != exact_keys:
        raise OperationControlRecoveryError(
            "prepared recovery authority keys are not exact"
        )
    for key, expected in required.items():
        if prepared.get(key) != expected:
            raise OperationControlRecoveryError(
                f"prepared recovery authority mismatch: {key}"
            )
    credential_sha = prepared.get("credential_sha256")
    marker = prepared.get("bootstrap_transaction_marker")
    if not isinstance(credential_sha, str) or _SHA256.fullmatch(credential_sha) is None:
        raise OperationControlRecoveryError("prepared credential identity is invalid")
    if marker != _expected_marker(spec, credential_sha):
        raise OperationControlRecoveryError("prepared bootstrap marker identity is invalid")


def _expected_production_boundary(spec: RecoverySpec) -> dict[str, str]:
    return {
        "current_source": spec.production_source_commit,
        "writer": "INACTIVE",
        "hub_cutover": "PREPARED",
    }


def _validate_completed(
    completed: dict[str, Any],
    spec: RecoverySpec,
    prepared: dict[str, Any],
) -> None:
    expected_boundary = _expected_production_boundary(spec)
    expected = {
        "schema": COMPLETED_SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "production_source_commit": spec.production_source_commit,
        "prepared_sha256": sha256(_canonical_json(prepared)).hexdigest(),
        "production_boundary_before": expected_boundary,
        "production_boundary_after": expected_boundary,
        "release_retained_exact": True,
        "sidecar_clean": True,
        "runtime_state_clean": True,
        "runtime_state_directories_touched": True,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
    }
    if set(completed) != set(expected):
        raise OperationControlRecoveryError(
            "completed recovery authority keys are not exact"
        )
    for key, value in expected.items():
        if completed.get(key) != value:
            raise OperationControlRecoveryError(
                f"completed recovery authority mismatch: {key}"
            )


def _observe(
    spec: RecoverySpec,
    layout: RecoveryLayout,
    *,
    systemctl: Systemctl,
    release_probe: ReleaseProbe,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    release = layout.install_root / "releases" / spec.rejected_source_commit
    identity = release_probe(
        release,
        spec.rejected_source_commit,
        spec.rejected_payload_sha256,
    )
    if (
        identity.get("source_commit") != spec.rejected_source_commit
        or identity.get("payload_sha256") != spec.rejected_payload_sha256
    ):
        raise OperationControlRecoveryError("rejected release probe returned wrong identity")

    expected_units = {
        unit: _unit_expected(release, unit)
        for unit in UNIT_NAMES
    }
    unit_sha256 = {
        unit: sha256(raw).hexdigest()
        for unit, raw in expected_units.items()
    }
    expected_receipt = _expected_receipt(spec)
    receipt_sha256 = sha256(expected_receipt).hexdigest()

    prepared_path, completed_path = _recovery_paths(layout, spec)
    prepared = None
    completed = None
    if layout.recovery_root.exists() or layout.recovery_root.is_symlink():
        _private_directory(layout.recovery_root, "operation recovery root")
        prepared = _read_canonical_record(prepared_path, PREPARED_SCHEMA)
        completed = _read_canonical_record(completed_path, COMPLETED_SCHEMA)
    if prepared is not None:
        _validate_prepared(
            prepared,
            spec,
            unit_sha256,
            receipt_sha256,
            layout,
        )
    if completed is not None:
        if prepared is None:
            raise OperationControlRecoveryError(
                "completed recovery authority requires exact prepared authority"
            )
        _validate_completed(completed, spec, prepared)

    config_state = "ABSENT"
    credential_state = "ABSENT"
    credential_sha = None
    if layout.config_dir.exists() or layout.config_dir.is_symlink():
        _private_directory(layout.config_dir, "operation config directory")
        config_state = "PRESENT"
        names = {entry.name for entry in layout.config_dir.iterdir()}
        if names - {"github-operations.env"}:
            raise OperationControlRecoveryError(
                "operation config directory contains foreign material"
            )
        if layout.credential.exists() or layout.credential.is_symlink():
            raw = _regular(layout.credential, "operation credential", 0o600)
            credential_sha = _credential_identity(raw, spec)
            credential_state = "PRESENT"
            if prepared is not None and credential_sha != prepared["credential_sha256"]:
                raise OperationControlRecoveryError(
                    "operation credential differs from prepared recovery authority"
                )

    marker_state = "ABSENT"
    marker_name = None
    receipt_state = "ABSENT"
    bootstrap_state = "ABSENT"
    if layout.bootstrap_root.exists() or layout.bootstrap_root.is_symlink():
        _private_directory(layout.bootstrap_root, "operation bootstrap root")
        bootstrap_state = "PRESENT"
        entries = list(layout.bootstrap_root.iterdir())
        markers = [entry for entry in entries if _MARKER.fullmatch(entry.name)]
        foreign = [
            entry.name
            for entry in entries
            if entry.name != "bootstrap-receipt.json"
            and _MARKER.fullmatch(entry.name) is None
        ]
        if foreign or len(markers) > 1:
            raise OperationControlRecoveryError(
                "operation bootstrap root contains foreign or ambiguous material"
            )
        if markers:
            marker = markers[0]
            _private_directory(marker, "bootstrap transaction marker")
            if any(marker.iterdir()):
                raise OperationControlRecoveryError("bootstrap transaction marker is not empty")
            marker_name = marker.name
            marker_state = "PRESENT"
        if layout.receipt.exists() or layout.receipt.is_symlink():
            raw = _regular(layout.receipt, "bootstrap receipt", 0o600)
            if raw != expected_receipt:
                raise OperationControlRecoveryError(
                    "bootstrap receipt differs from rejected transaction authority"
                )
            receipt_state = "PRESENT"

    if prepared is None:
        if credential_sha is None:
            expected_marker = None
        else:
            expected_marker = _expected_marker(spec, credential_sha)
    else:
        expected_marker = prepared["bootstrap_transaction_marker"]

    if marker_state == "PRESENT" and marker_name != expected_marker:
        raise OperationControlRecoveryError(
            "bootstrap transaction marker differs from rejected transaction authority"
        )

    target = f"releases/{spec.rejected_source_commit}"
    if not layout.control_current.exists() and not layout.control_current.is_symlink():
        control_state = "ABSENT"
    else:
        if not layout.control_current.is_symlink():
            raise OperationControlRecoveryError("control-current must be symlink or absent")
        if os.readlink(layout.control_current) != target:
            raise OperationControlRecoveryError(
                "control-current selects a different release"
            )
        control_state = "EXACT"

    runtime_state = _runtime_state(layout)

    units: dict[str, str] = {}
    services: dict[str, dict[str, str]] = {}
    for unit in UNIT_NAMES:
        target_path = layout.unit_dir / unit
        if not target_path.exists() and not target_path.is_symlink():
            units[unit] = "ABSENT"
        else:
            raw = _regular(target_path, unit, 0o644)
            if raw != expected_units[unit]:
                raise OperationControlRecoveryError(
                    f"installed unit differs from rejected release: {unit}"
                )
            units[unit] = "EXACT"
        services[unit] = _service_state(unit, systemctl)
        if services[unit]["active"] == "active":
            raise OperationControlRecoveryError(
                f"rejected operation unit is unexpectedly active: {unit}"
            )

    full = (
        control_state == "EXACT"
        and config_state == "PRESENT"
        and credential_state == "PRESENT"
        and bootstrap_state == "PRESENT"
        and marker_state == "PRESENT"
        and receipt_state == "PRESENT"
        and all(value == "EXACT" for value in units.values())
        and runtime_state == {
            "transport_root": "EXACT",
            "operation_root": "EXACT",
            "operation_control_root": "EXACT",
        }
    )
    clean = (
        control_state == "ABSENT"
        and config_state == "ABSENT"
        and credential_state == "ABSENT"
        and bootstrap_state == "ABSENT"
        and marker_state == "ABSENT"
        and receipt_state == "ABSENT"
        and all(value == "ABSENT" for value in units.values())
        and all(value == "ABSENT" for value in runtime_state.values())
    )

    if completed is not None:
        if not clean:
            raise OperationControlRecoveryError(
                "completed recovery authority conflicts with remaining sidecar material"
            )
        state = "COMPLETED"
    elif prepared is None:
        if not full:
            raise OperationControlRecoveryError(
                "rejected sidecar is neither exact initial recovery state nor durably prepared"
            )
        state = "READY"
    elif clean:
        state = "CLEAN_PENDING_COMPLETION"
    else:
        state = "PREPARED_OR_PARTIAL"

    observation = {
        "schema": SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "release": "EXACT",
        "recovery_state": state,
        "recovery_prepared": prepared is not None,
        "recovery_completed": completed is not None,
        "control_current": control_state,
        "config_dir": config_state,
        "credential": credential_state,
        "bootstrap_root": bootstrap_state,
        "bootstrap_transaction": marker_state,
        "bootstrap_receipt": receipt_state,
        "units": units,
        "services": services,
        "runtime_state": runtime_state,
        "runtime_state_directories_touched": False,
    }
    if prepared is None:
        observation["_prepare_material"] = {
            "marker": marker_name,
            "credential_sha256": credential_sha,
            "receipt_sha256": receipt_sha256,
            "unit_sha256": unit_sha256,
        }
    return observation, prepared, completed


def inspect_rejected_install(
    spec: RecoverySpec,
    layout: RecoveryLayout,
    *,
    systemctl: Systemctl = _default_systemctl,
    boundary_probe: BoundaryProbe | None = None,
    release_probe: ReleaseProbe = _release_identity,
) -> dict[str, Any]:
    _validate_spec(spec)
    _require_root()
    boundary_probe = boundary_probe or (lambda: _production_boundary(spec, layout))
    before = boundary_probe()
    observation, _, _ = _observe(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    after = boundary_probe()
    if before != after:
        raise OperationControlRecoveryError(
            "production boundary changed during recovery inspection"
        )
    observation["production_boundary_before"] = before
    observation["production_boundary_after"] = after
    observation["persistent_mutations_performed"] = False
    observation.pop("_prepare_material", None)
    return observation


def _must_systemctl(systemctl: Systemctl, args: list[str]) -> None:
    result = systemctl(args)
    if result.returncode != 0:
        raise OperationControlRecoveryError(
            "systemctl operation failed: " + " ".join(args)
        )


def cleanup_rejected_install(
    spec: RecoverySpec,
    layout: RecoveryLayout,
    *,
    systemctl: Systemctl = _default_systemctl,
    boundary_probe: BoundaryProbe | None = None,
    release_probe: ReleaseProbe = _release_identity,
) -> dict[str, Any]:
    _validate_spec(spec)
    _require_root()
    boundary_probe = boundary_probe or (lambda: _production_boundary(spec, layout))

    before = boundary_probe()
    observation, prepared, completed = _observe(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    if completed is not None:
        after = boundary_probe()
        if after != before:
            raise OperationControlRecoveryError(
                "production boundary changed during completed recovery replay"
            )
        return {
            "schema": COMPLETED_SCHEMA,
            "replayed": True,
            "rejected_source_commit": spec.rejected_source_commit,
            "production_boundary_before": before,
            "production_boundary_after": after,
            "sidecar_clean": True,
            "runtime_state_clean": True,
            "runtime_state_directories_touched": True,
            "production_current_mutated": False,
            "hub_cutover_mutated": False,
            "drive_mutated": False,
        }

    prepared_path, completed_path = _recovery_paths(layout, spec)
    if prepared is None:
        material = observation.get("_prepare_material")
        if not isinstance(material, dict):
            raise OperationControlRecoveryError(
                "initial recovery observation lacks transaction identity"
            )
        marker = material.get("marker")
        credential_sha = material.get("credential_sha256")
        if not isinstance(marker, str) or not isinstance(credential_sha, str):
            raise OperationControlRecoveryError(
                "initial recovery transaction identity is incomplete"
            )
        prepared = _prepared_static(
            spec,
            marker=marker,
            credential_sha256=credential_sha,
            receipt_sha256=material["receipt_sha256"],
            unit_sha256=material["unit_sha256"],
            layout=layout,
        )
        _ensure_recovery_root(layout)
        _write_exclusive_private(prepared_path, prepared)

    observation, prepared, completed = _observe(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    if completed is not None:
        raise OperationControlRecoveryError(
            "completed recovery appeared unexpectedly during cleanup"
        )

    # Disable exact rejected services before removing any unit or credential bytes.
    for unit in UNIT_NAMES:
        service = observation["services"][unit]
        if service["active"] == "active":
            raise OperationControlRecoveryError(
                f"rejected operation unit became active: {unit}"
            )
        if observation["units"][unit] == "EXACT" or service["enabled"] == "enabled":
            _must_systemctl(systemctl, ["disable", "--now", unit])
            state = _service_state(unit, systemctl)
            if state["active"] == "active" or state["enabled"] == "enabled":
                raise OperationControlRecoveryError(
                    f"rejected operation unit did not disable cleanly: {unit}"
                )
            reset = systemctl(["reset-failed", unit])
            if reset.returncode != 0:
                raise OperationControlRecoveryError(
                    f"cannot reset rejected operation unit failure: {unit}"
                )

    commit_boundary = boundary_probe()
    if commit_boundary != before:
        raise OperationControlRecoveryError(
            "production boundary changed before rejected sidecar removal"
        )

    release = layout.install_root / "releases" / spec.rejected_source_commit
    for unit in UNIT_NAMES:
        path = layout.unit_dir / unit
        if path.exists() or path.is_symlink():
            expected = _unit_expected(release, unit)
            if _regular(path, unit, 0o644) != expected:
                raise OperationControlRecoveryError(
                    f"rejected unit changed at removal boundary: {unit}"
                )
            _unlink_pinned(path)

    _must_systemctl(systemctl, ["daemon-reload"])

    if layout.control_current.exists() or layout.control_current.is_symlink():
        if (
            not layout.control_current.is_symlink()
            or os.readlink(layout.control_current)
            != f"releases/{spec.rejected_source_commit}"
        ):
            raise OperationControlRecoveryError(
                "control-current changed at removal boundary"
            )
        _unlink_pinned(layout.control_current)

    if layout.receipt.exists() or layout.receipt.is_symlink():
        if _regular(layout.receipt, "bootstrap receipt", 0o600) != _expected_receipt(spec):
            raise OperationControlRecoveryError(
                "bootstrap receipt changed at removal boundary"
            )
        _unlink_pinned(layout.receipt)

    if layout.credential.exists() or layout.credential.is_symlink():
        raw = _regular(layout.credential, "operation credential", 0o600)
        if sha256(raw).hexdigest() != prepared["credential_sha256"]:
            raise OperationControlRecoveryError(
                "operation credential changed at removal boundary"
            )
        _credential_identity(raw, spec)
        _unlink_pinned(layout.credential)

    marker_path = layout.bootstrap_root / prepared["bootstrap_transaction_marker"]
    if marker_path.exists() or marker_path.is_symlink():
        _private_directory(marker_path, "bootstrap transaction marker")
        if any(marker_path.iterdir()):
            raise OperationControlRecoveryError(
                "bootstrap transaction marker gained unexpected material"
            )
        _unlink_pinned(marker_path, directory=True)

    if layout.config_dir.exists() or layout.config_dir.is_symlink():
        _private_directory(layout.config_dir, "operation config directory")
        if any(layout.config_dir.iterdir()):
            raise OperationControlRecoveryError(
                "operation config directory is not empty after cleanup"
            )
        _unlink_pinned(layout.config_dir, directory=True)

    if layout.bootstrap_root.exists() or layout.bootstrap_root.is_symlink():
        _private_directory(layout.bootstrap_root, "operation bootstrap root")
        if any(layout.bootstrap_root.iterdir()):
            raise OperationControlRecoveryError(
                "operation bootstrap root is not empty after cleanup"
            )
        _unlink_pinned(layout.bootstrap_root, directory=True)

    _remove_runtime_state(layout)

    post, _, _ = _observe(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    if post["recovery_state"] != "CLEAN_PENDING_COMPLETION":
        raise OperationControlRecoveryError(
            "rejected sidecar cleanup did not reach exact clean state"
        )

    final_boundary = boundary_probe()
    if final_boundary != before:
        raise OperationControlRecoveryError(
            "production boundary changed during rejected sidecar cleanup"
        )

    completed_value = {
        "schema": COMPLETED_SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "production_source_commit": spec.production_source_commit,
        "prepared_sha256": sha256(_canonical_json(prepared)).hexdigest(),
        "production_boundary_before": before,
        "production_boundary_after": final_boundary,
        "release_retained_exact": True,
        "sidecar_clean": True,
        "runtime_state_clean": True,
        "runtime_state_directories_touched": True,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
    }
    _write_exclusive_private(completed_path, completed_value)

    verified = inspect_rejected_install(
        spec,
        layout,
        systemctl=systemctl,
        boundary_probe=boundary_probe,
        release_probe=release_probe,
    )
    if verified["recovery_state"] != "COMPLETED":
        raise OperationControlRecoveryError(
            "completed recovery authority did not verify"
        )
    return completed_value



def _failed_bootstrap_paths(
    layout: RecoveryLayout,
    spec: RecoverySpec,
) -> tuple[Path, Path]:
    stem = f"failed-bootstrap-{spec.rejected_source_commit}"
    return (
        layout.recovery_root / f"{stem}.prepared.json",
        layout.recovery_root / f"{stem}.completed.json",
    )


def _exact_regular_identity(
    path: Path,
    label: str,
    *,
    expected_uid: int,
    expected_gid: int,
    expected_mode: int,
    expected_size: int,
) -> None:
    path = path.absolute()
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise OperationControlRecoveryError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise OperationControlRecoveryError(f"{label} must be one regular file")
    if (
        info.st_uid != expected_uid
        or info.st_gid != expected_gid
        or stat.S_IMODE(info.st_mode) != expected_mode
        or info.st_size != expected_size
    ):
        raise OperationControlRecoveryError(
            f"{label} owner/group/mode/size is not exact"
        )


def _failed_bootstrap_runtime_state(
    layout: RecoveryLayout,
    *,
    allow_partial: bool,
) -> dict[str, str]:
    root_uid = os.geteuid()
    root_gid = os.getegid()
    service_uid, service_gid = _service_identity()

    transport_entries = _directory_identity(
        layout.transport_root,
        "failed-bootstrap transport runtime root",
        expected_uid=service_uid,
        expected_gid=service_gid,
        expected_mode=0o700,
    )
    if transport_entries is None:
        transport_state = "ABSENT"
    else:
        expected = {"inbox", "outbox", "state"}
        names = {entry.name for entry in transport_entries}
        if not names.issubset(expected):
            raise OperationControlRecoveryError(
                "failed-bootstrap transport runtime root contains unexpected material"
            )
        for name in sorted(names):
            entries = _directory_identity(
                layout.transport_root / name,
                f"failed-bootstrap transport {name} directory",
                expected_uid=service_uid,
                expected_gid=service_gid,
                expected_mode=0o700,
            )
            if entries is None:
                raise OperationControlRecoveryError(
                    f"failed-bootstrap transport {name} directory disappeared"
                )
            if entries:
                raise OperationControlRecoveryError(
                    f"failed-bootstrap transport {name} directory is not empty"
                )
        if not allow_partial and names != expected:
            raise OperationControlRecoveryError(
                "failed-bootstrap transport runtime layout is not exact"
            )
        transport_state = "EXACT" if names == expected else "PARTIAL_EXACT"

    operation_entries = _directory_identity(
        layout.operation_root,
        "failed-bootstrap operation runtime root",
        expected_uid=root_uid,
        expected_gid=root_gid,
        expected_mode=0o700,
    )
    if operation_entries is None:
        operation_state = "ABSENT"
    elif operation_entries:
        raise OperationControlRecoveryError(
            "failed-bootstrap operation runtime root contains unexpected material"
        )
    else:
        operation_state = "EXACT"

    control_entries = _directory_identity(
        layout.operation_control_root,
        "failed-bootstrap operation control root",
        expected_uid=root_uid,
        expected_gid=root_gid,
        expected_mode=0o700,
    )
    if control_entries is None:
        control_state = "ABSENT"
    else:
        expected = {"processed", "rejected", "LOCK"}
        names = {entry.name for entry in control_entries}
        if not names.issubset(expected):
            raise OperationControlRecoveryError(
                "failed-bootstrap operation control root contains unexpected material"
            )
        for name in ("processed", "rejected"):
            if name not in names:
                continue
            entries = _directory_identity(
                layout.operation_control_root / name,
                f"failed-bootstrap operation control {name} directory",
                expected_uid=root_uid,
                expected_gid=root_gid,
                expected_mode=0o700,
            )
            if entries is None:
                raise OperationControlRecoveryError(
                    f"failed-bootstrap operation control {name} disappeared"
                )
            if entries:
                raise OperationControlRecoveryError(
                    f"failed-bootstrap operation control {name} is not empty"
                )
        if "LOCK" in names:
            _exact_regular_identity(
                layout.operation_control_root / "LOCK",
                "failed-bootstrap operation control lock",
                expected_uid=root_uid,
                expected_gid=root_gid,
                expected_mode=0o600,
                expected_size=0,
            )
        if not allow_partial and names != expected:
            raise OperationControlRecoveryError(
                "failed-bootstrap operation control layout is not exact"
            )
        control_state = "EXACT" if names == expected else "PARTIAL_EXACT"

    states = {
        "transport_root": transport_state,
        "operation_root": operation_state,
        "operation_control_root": control_state,
    }
    if not allow_partial and states != {
        "transport_root": "EXACT",
        "operation_root": "EXACT",
        "operation_control_root": "EXACT",
    }:
        raise OperationControlRecoveryError(
            "failed-bootstrap runtime residue is not exact"
        )
    return states


def _failed_bootstrap_prepared(
    spec: RecoverySpec,
    layout: RecoveryLayout,
) -> dict[str, Any]:
    return {
        "schema": FAILED_BOOTSTRAP_PREPARED_SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "production_source_commit": spec.production_source_commit,
        "repository": spec.repository,
        "issue": spec.issue,
        "actors": _normalize_actors(spec.actors),
        "status_actor": spec.status_actor,
        "runtime_state_layout": FAILED_BOOTSTRAP_RUNTIME_LAYOUT,
        "filesystem_layout": _layout_authority(layout),
        "sidecar_transaction_paths_clean": True,
    }


def _validate_failed_bootstrap_prepared(
    value: dict[str, Any],
    spec: RecoverySpec,
    layout: RecoveryLayout,
) -> None:
    expected = _failed_bootstrap_prepared(spec, layout)
    if set(value) != set(expected):
        raise OperationControlRecoveryError(
            "failed-bootstrap PREPARED authority keys are not exact"
        )
    for key, item in expected.items():
        if value.get(key) != item:
            raise OperationControlRecoveryError(
                f"failed-bootstrap PREPARED authority mismatch: {key}"
            )


def _validate_failed_bootstrap_completed(
    value: dict[str, Any],
    spec: RecoverySpec,
    prepared: dict[str, Any],
) -> None:
    boundary = _expected_production_boundary(spec)
    expected = {
        "schema": FAILED_BOOTSTRAP_COMPLETED_SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "production_source_commit": spec.production_source_commit,
        "prepared_sha256": sha256(_canonical_json(prepared)).hexdigest(),
        "production_boundary_before": boundary,
        "production_boundary_after": boundary,
        "release_retained_exact": True,
        "sidecar_transaction_paths_clean": True,
        "runtime_state_clean": True,
        "runtime_state_directories_touched": True,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
    }
    if set(value) != set(expected):
        raise OperationControlRecoveryError(
            "failed-bootstrap COMPLETED authority keys are not exact"
        )
    for key, item in expected.items():
        if value.get(key) != item:
            raise OperationControlRecoveryError(
                f"failed-bootstrap COMPLETED authority mismatch: {key}"
            )


def _observe_failed_bootstrap_runtime(
    spec: RecoverySpec,
    layout: RecoveryLayout,
    *,
    systemctl: Systemctl,
    release_probe: ReleaseProbe,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    release = layout.install_root / "releases" / spec.rejected_source_commit
    identity = release_probe(
        release,
        spec.rejected_source_commit,
        spec.rejected_payload_sha256,
    )
    if (
        identity.get("source_commit") != spec.rejected_source_commit
        or identity.get("payload_sha256") != spec.rejected_payload_sha256
    ):
        raise OperationControlRecoveryError(
            "failed-bootstrap rejected release probe returned wrong identity"
        )

    if layout.control_current.exists() or layout.control_current.is_symlink():
        raise OperationControlRecoveryError(
            "failed-bootstrap recovery requires control-current ABSENT"
        )
    if layout.config_dir.exists() or layout.config_dir.is_symlink():
        raise OperationControlRecoveryError(
            "failed-bootstrap recovery requires config directory ABSENT"
        )
    if layout.bootstrap_root.exists() or layout.bootstrap_root.is_symlink():
        raise OperationControlRecoveryError(
            "failed-bootstrap recovery requires bootstrap root ABSENT"
        )

    services: dict[str, dict[str, str]] = {}
    for unit in UNIT_NAMES:
        target = layout.unit_dir / unit
        if target.exists() or target.is_symlink():
            raise OperationControlRecoveryError(
                f"failed-bootstrap recovery requires unit ABSENT: {unit}"
            )
        services[unit] = _service_state(unit, systemctl)
        if (
            services[unit]["active"] == "active"
            or services[unit]["enabled"] == "enabled"
        ):
            raise OperationControlRecoveryError(
                f"failed-bootstrap recovery requires inactive/disabled service: {unit}"
            )

    prepared_path, completed_path = _failed_bootstrap_paths(layout, spec)
    prepared = None
    completed = None
    if layout.recovery_root.exists() or layout.recovery_root.is_symlink():
        _private_directory(layout.recovery_root, "operation recovery root")
        prepared = _read_canonical_record(
            prepared_path,
            FAILED_BOOTSTRAP_PREPARED_SCHEMA,
        )
        completed = _read_canonical_record(
            completed_path,
            FAILED_BOOTSTRAP_COMPLETED_SCHEMA,
        )
    if prepared is not None:
        _validate_failed_bootstrap_prepared(prepared, spec, layout)
    if completed is not None:
        if prepared is None:
            raise OperationControlRecoveryError(
                "failed-bootstrap COMPLETED authority requires PREPARED authority"
            )
        _validate_failed_bootstrap_completed(completed, spec, prepared)

    runtime = _failed_bootstrap_runtime_state(
        layout,
        allow_partial=prepared is not None,
    )
    clean = all(value == "ABSENT" for value in runtime.values())
    exact = all(value == "EXACT" for value in runtime.values())

    if completed is not None:
        if not clean:
            raise OperationControlRecoveryError(
                "failed-bootstrap COMPLETED authority conflicts with runtime residue"
            )
        state = "COMPLETED"
    elif prepared is None:
        if not exact:
            raise OperationControlRecoveryError(
                "failed-bootstrap runtime residue is not exact initial state"
            )
        state = "READY"
    elif clean:
        state = "CLEAN_PENDING_COMPLETION"
    else:
        state = "PREPARED_OR_PARTIAL"

    return (
        {
            "schema": FAILED_BOOTSTRAP_SCHEMA,
            "rejected_source_commit": spec.rejected_source_commit,
            "rejected_payload_sha256": spec.rejected_payload_sha256,
            "release": "EXACT",
            "recovery_state": state,
            "recovery_prepared": prepared is not None,
            "recovery_completed": completed is not None,
            "sidecar_transaction_paths_clean": True,
            "services": services,
            "runtime_state": runtime,
            "persistent_mutations_performed": False,
        },
        prepared,
        completed,
    )


def inspect_failed_bootstrap_runtime(
    spec: RecoverySpec,
    layout: RecoveryLayout,
    *,
    systemctl: Systemctl = _default_systemctl,
    boundary_probe: BoundaryProbe | None = None,
    release_probe: ReleaseProbe = _release_identity,
) -> dict[str, Any]:
    _validate_spec(spec)
    _require_root()
    boundary_probe = boundary_probe or (lambda: _production_boundary(spec, layout))
    before = boundary_probe()
    observation, _, _ = _observe_failed_bootstrap_runtime(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    after = boundary_probe()
    if before != after:
        raise OperationControlRecoveryError(
            "production boundary changed during failed-bootstrap inspection"
        )
    observation["production_boundary_before"] = before
    observation["production_boundary_after"] = after
    return observation


def _remove_failed_bootstrap_runtime(layout: RecoveryLayout) -> None:
    _failed_bootstrap_runtime_state(layout, allow_partial=True)

    if layout.operation_control_root.exists() or layout.operation_control_root.is_symlink():
        lock = layout.operation_control_root / "LOCK"
        if lock.exists() or lock.is_symlink():
            _unlink_pinned(lock)
        for name in ("processed", "rejected"):
            child = layout.operation_control_root / name
            if child.exists() or child.is_symlink():
                _unlink_pinned(child, directory=True)
        _unlink_pinned(layout.operation_control_root, directory=True)

    if layout.operation_root.exists() or layout.operation_root.is_symlink():
        _unlink_pinned(layout.operation_root, directory=True)

    if layout.transport_root.exists() or layout.transport_root.is_symlink():
        for name in ("state", "outbox", "inbox"):
            child = layout.transport_root / name
            if child.exists() or child.is_symlink():
                _unlink_pinned(child, directory=True)
        _unlink_pinned(layout.transport_root, directory=True)


def cleanup_failed_bootstrap_runtime(
    spec: RecoverySpec,
    layout: RecoveryLayout,
    *,
    systemctl: Systemctl = _default_systemctl,
    boundary_probe: BoundaryProbe | None = None,
    release_probe: ReleaseProbe = _release_identity,
) -> dict[str, Any]:
    _validate_spec(spec)
    _require_root()
    boundary_probe = boundary_probe or (lambda: _production_boundary(spec, layout))

    before = boundary_probe()
    observation, prepared, completed = _observe_failed_bootstrap_runtime(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    if completed is not None:
        after = boundary_probe()
        if after != before:
            raise OperationControlRecoveryError(
                "production boundary changed during failed-bootstrap replay"
            )
        return {
            "schema": FAILED_BOOTSTRAP_COMPLETED_SCHEMA,
            "replayed": True,
            "rejected_source_commit": spec.rejected_source_commit,
            "production_boundary_before": before,
            "production_boundary_after": after,
            "runtime_state_clean": True,
            "runtime_state_directories_touched": True,
            "production_current_mutated": False,
            "hub_cutover_mutated": False,
            "drive_mutated": False,
        }

    prepared_path, completed_path = _failed_bootstrap_paths(layout, spec)
    if prepared is None:
        if observation["recovery_state"] != "READY":
            raise OperationControlRecoveryError(
                "failed-bootstrap recovery is not at exact READY boundary"
            )
        prepared = _failed_bootstrap_prepared(spec, layout)
        _ensure_recovery_root(layout)
        _write_exclusive_private(prepared_path, prepared)

    observation, prepared, completed = _observe_failed_bootstrap_runtime(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    if completed is not None:
        raise OperationControlRecoveryError(
            "failed-bootstrap COMPLETED authority appeared unexpectedly"
        )

    commit_boundary = boundary_probe()
    if commit_boundary != before:
        raise OperationControlRecoveryError(
            "production boundary changed before failed-bootstrap cleanup"
        )

    _remove_failed_bootstrap_runtime(layout)

    post, _, _ = _observe_failed_bootstrap_runtime(
        spec,
        layout,
        systemctl=systemctl,
        release_probe=release_probe,
    )
    if post["recovery_state"] != "CLEAN_PENDING_COMPLETION":
        raise OperationControlRecoveryError(
            "failed-bootstrap cleanup did not reach exact clean state"
        )

    final_boundary = boundary_probe()
    if final_boundary != before:
        raise OperationControlRecoveryError(
            "production boundary changed during failed-bootstrap cleanup"
        )

    completed_value = {
        "schema": FAILED_BOOTSTRAP_COMPLETED_SCHEMA,
        "rejected_source_commit": spec.rejected_source_commit,
        "rejected_payload_sha256": spec.rejected_payload_sha256,
        "production_source_commit": spec.production_source_commit,
        "prepared_sha256": sha256(_canonical_json(prepared)).hexdigest(),
        "production_boundary_before": before,
        "production_boundary_after": final_boundary,
        "release_retained_exact": True,
        "sidecar_transaction_paths_clean": True,
        "runtime_state_clean": True,
        "runtime_state_directories_touched": True,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
    }
    _write_exclusive_private(completed_path, completed_value)

    verified = inspect_failed_bootstrap_runtime(
        spec,
        layout,
        systemctl=systemctl,
        boundary_probe=boundary_probe,
        release_probe=release_probe,
    )
    if verified["recovery_state"] != "COMPLETED":
        raise OperationControlRecoveryError(
            "failed-bootstrap COMPLETED authority did not verify"
        )
    return completed_value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-control-recovery")
    parser.add_argument("--rejected-source-commit", required=True)
    parser.add_argument("--rejected-payload-sha256", required=True)
    parser.add_argument("--production-source-commit", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--actors", required=True)
    parser.add_argument("--status-actor", required=True)
    parser.add_argument("--install-root", type=Path, default=Path("/opt/keelaryn"))
    parser.add_argument("--unit-dir", type=Path, default=Path("/etc/systemd/system"))
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("/etc/keelaryn/operation-control"),
    )
    parser.add_argument(
        "--bootstrap-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operation-bootstrap"),
    )
    parser.add_argument(
        "--recovery-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operation-recovery"),
    )
    parser.add_argument(
        "--transport-root",
        type=Path,
        default=Path("/var/lib/keelaryn-operation-transport"),
    )
    parser.add_argument(
        "--operation-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operations"),
    )
    parser.add_argument(
        "--operation-control-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operation-control"),
    )
    parser.add_argument("--selector", type=Path, default=Path("/etc/keelaryn/hub.env"))
    parser.add_argument(
        "--deployment-state-root",
        type=Path,
        default=Path("/var/lib/keelaryn/deployment"),
    )
    parser.add_argument(
        "--mutation-gate-root",
        type=Path,
        default=Path("/var/lib/keelaryn/mutation-gate"),
    )
    parser.add_argument(
        "command",
        choices=(
            "inspect",
            "cleanup",
            "inspect-failed-bootstrap-runtime",
            "cleanup-failed-bootstrap-runtime",
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    spec = RecoverySpec(
        rejected_source_commit=args.rejected_source_commit,
        rejected_payload_sha256=args.rejected_payload_sha256,
        production_source_commit=args.production_source_commit,
        repository=args.repository,
        issue=args.issue,
        actors=args.actors,
        status_actor=args.status_actor,
    )
    layout = RecoveryLayout(
        install_root=args.install_root,
        unit_dir=args.unit_dir,
        config_dir=args.config_dir,
        bootstrap_root=args.bootstrap_root,
        recovery_root=args.recovery_root,
        transport_root=args.transport_root,
        operation_root=args.operation_root,
        operation_control_root=args.operation_control_root,
        selector=args.selector,
        deployment_state_root=args.deployment_state_root,
        mutation_gate_root=args.mutation_gate_root,
    )
    try:
        if args.command == "inspect":
            value = inspect_rejected_install(spec, layout)
        elif args.command == "cleanup":
            value = cleanup_rejected_install(spec, layout)
        elif args.command == "inspect-failed-bootstrap-runtime":
            value = inspect_failed_bootstrap_runtime(spec, layout)
        else:
            value = cleanup_failed_bootstrap_runtime(spec, layout)
    except (
        OperationControlRecoveryError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
