from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


GATE_REVISION = "operation-control-gate-r0006"
CANDIDATE = "operation-control-r0004-20260920-01"
REPOSITORY = "https://github.com/efremov-aleksei-96/keelaryn.git"
SOURCE_COMMIT = "819dcbd11b531180763ddcf55d2273a8b6da1c5e"
SOURCE_TREE = "7e00fadba2aff9b40a941f68175af7275f208413"
PAYLOAD_SHA256 = "d814b27f4fe7fa9ceb5271002fa17044f427cda1a58f4e554e5168f1a8b5aa89"
PAYLOAD_SIZE = 361869
PAYLOAD_FILE_COUNT = 190
PRODUCTION_SOURCE = "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
CONTROL_ISSUE = 65
PREDECESSOR_CANDIDATE = "operation-control-r0001-20260920-01"
PREDECESSOR_SOURCE_COMMIT = "98e76ffdcdbac09610f8b9a2b542f7e61e7dba61"
PREDECESSOR_PAYLOAD_SHA256 = "b9f4022ddca38435e377ed08662d6cc7930655c828b861cdca980ba87f948c4b"

INSTALL_ROOT = Path("/opt/keelaryn")
RELEASES_ROOT = INSTALL_ROOT / "releases"
PRODUCTION_CURRENT = INSTALL_ROOT / "current"
CONTROL_CURRENT = INSTALL_ROOT / "control-current"
SELECTOR = Path("/etc/keelaryn/hub.env")
STATE_ROOT = Path("/var/lib/keelaryn/deployment")
MUTATION_GATE_ROOT = Path("/var/lib/keelaryn/mutation-gate")
CONFIG_DIR = Path("/etc/keelaryn/operation-control")
BOOTSTRAP_ROOT = Path("/var/lib/keelaryn/operation-bootstrap")
STATUS_ACTOR = "efremov-aleksei-96"
REJECTED_R0002_CANDIDATE = "operation-control-r0002-20260920-01"
REJECTED_R0002_SOURCE_COMMIT = "a368cc85e799842a00c5c1c496614437aa7064f2"
REJECTED_R0003_CANDIDATE = "operation-control-r0003-20260920-01"
REJECTED_R0003_SOURCE_COMMIT = "18885db5baa479fde080568b116ff32c0fead07a"
REJECTED_R0003_PAYLOAD_SHA256 = "80050c8adda76080b91b5d71dd3ce75a6463ef189850e74dd144ff882035fee8"
RECOVERY_ROOT = Path("/var/lib/keelaryn/operation-recovery")
TRANSPORT_ROOT = Path("/var/lib/keelaryn-operation-transport")
OPERATION_ROOT = Path("/var/lib/keelaryn/operations")
OPERATION_CONTROL_ROOT = Path("/var/lib/keelaryn/operation-control")
_TRANSACTION_DIR = re.compile(r"^transaction-c[01]-b[01]-[0-9a-f]{64}$")
UNIT_DIR = Path("/etc/systemd/system")
UNIT_NAMES = (
    "keelaryn-operation-transport.service",
    "keelaryn-operation-agent.service",
)


class GateError(RuntimeError):
    pass


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=None if cwd is None else str(cwd),
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"command failed to execute: {args[0]}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise GateError(f"command returned nonzero: {args[0]}{suffix}")
    return result


def _json_command(args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    result = _run(args, cwd=cwd)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(f"command returned invalid JSON: {args[0]}") from exc
    if not isinstance(value, dict):
        raise GateError(f"command returned non-object JSON: {args[0]}")
    return value


def _require_root() -> None:
    if os.geteuid() != 0:
        raise GateError("VPS qualification/bootstrap must run as root")


def _readlink_exact(path: Path) -> str:
    if not path.is_symlink():
        raise GateError(f"required selector is not a symlink: {path}")
    return os.readlink(path)


def _production_boundary() -> dict[str, Any]:
    expected = f"releases/{PRODUCTION_SOURCE}"
    current = _readlink_exact(PRODUCTION_CURRENT)
    if current != expected:
        raise GateError("production current is not exact expected e63f authority")

    try:
        active = subprocess.run(
            ["systemctl", "is-active", "keelaryn-drive.service"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("cannot inspect production writer state") from exc
    writer_state = active.stdout.strip()
    if active.returncode not in {0, 3} or writer_state != "inactive":
        raise GateError(
            "production writer is not exact INACTIVE at prepared boundary"
        )

    tool = INSTALL_ROOT / "releases" / PRODUCTION_SOURCE / "deploy" / "zero-based-vps" / "hub_cutover.py"
    status = _json_command(
        [
            sys.executable,
            "-B",
            str(tool),
            "--selector-path",
            str(SELECTOR),
            "--state-root",
            str(STATE_ROOT),
            "--mutation-gate-root",
            str(MUTATION_GATE_ROOT),
            "--source-commit",
            PRODUCTION_SOURCE,
            "status",
        ]
    )
    if status.get("status") != "PREPARED":
        raise GateError("production Hub cutover is no longer exact PREPARED")
    return {
        "current_source": PRODUCTION_SOURCE,
        "writer": "INACTIVE",
        "hub_cutover": "PREPARED",
    }


def _checkout_source(work: Path) -> Path:
    repo = work / "source"
    _run(["git", "init", "-q", str(repo)])
    _run(["git", "-C", str(repo), "remote", "add", "origin", REPOSITORY])
    _run(["git", "-C", str(repo), "fetch", "-q", "--depth", "1", "origin", SOURCE_COMMIT])
    _run(["git", "-C", str(repo), "checkout", "-q", "--detach", "FETCH_HEAD"])
    head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
    tree = _run(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"]).stdout.strip()
    dirty = _run(["git", "-C", str(repo), "status", "--porcelain"]).stdout
    if head != SOURCE_COMMIT or tree != SOURCE_TREE or dirty:
        raise GateError("fetched candidate source identity is not exact")
    return repo


def _build_payload(repo: Path, work: Path) -> Path:
    first = work / "first.tar.gz"
    second = work / "second.tar.gz"
    builder = repo / "deploy" / "zero-based-vps" / "build_payload.py"

    first_meta = _json_command(
        [
            sys.executable,
            "-B",
            str(builder),
            "--repo-root",
            str(repo),
            "--source-commit",
            SOURCE_COMMIT,
            "--output",
            str(first),
        ]
    )
    second_meta = _json_command(
        [
            sys.executable,
            "-B",
            str(builder),
            "--repo-root",
            str(repo),
            "--source-commit",
            SOURCE_COMMIT,
            "--output",
            str(second),
        ]
    )
    first_raw = first.read_bytes()
    second_raw = second.read_bytes()
    if first_raw != second_raw:
        raise GateError("candidate payload rebuild is not deterministic")
    digest = hashlib.sha256(first_raw).hexdigest()
    expected = {
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }
    observed = {
        "source_commit": first_meta.get("source_commit"),
        "payload_sha256": digest,
        "payload_size": len(first_raw),
        "file_count": first_meta.get("file_count"),
    }
    if observed != expected:
        raise GateError(f"candidate payload identity mismatch: {observed}")
    for key in ("source_commit", "payload_sha256", "payload_size", "file_count"):
        if second_meta.get(key) != first_meta.get(key):
            raise GateError("second payload metadata differs from first rebuild")
    return first


def _validate_release(release: Path) -> dict[str, Any]:
    if not release.exists() or release.is_symlink() or not release.is_dir():
        raise GateError("exact frozen candidate release is not materialized")
    validator = release / "deploy" / "zero-based-vps" / "target_host_validate.py"
    value = _json_command(
        [
            sys.executable,
            "-B",
            str(validator),
            "--release",
            str(release),
            "--expected-source-commit",
            SOURCE_COMMIT,
            "--expected-payload-sha256",
            PAYLOAD_SHA256,
        ]
    )
    if (
        value.get("source_commit") != SOURCE_COMMIT
        or value.get("payload_sha256") != PAYLOAD_SHA256
        or value.get("release_remained_exact") is not True
        or value.get("host_config_verified") is not False
    ):
        raise GateError("release-only target-host qualification did not prove exact candidate")
    return value


def _validate_rejected_predecessor_release() -> dict[str, Any]:
    release = RELEASES_ROOT / PREDECESSOR_SOURCE_COMMIT
    if not release.exists() or release.is_symlink() or not release.is_dir():
        raise GateError("rejected r0001 predecessor release is not exact present directory")
    validator = release / "deploy" / "zero-based-vps" / "target_host_validate.py"
    value = _json_command(
        [
            sys.executable,
            "-B",
            str(validator),
            "--release",
            str(release),
            "--expected-source-commit",
            PREDECESSOR_SOURCE_COMMIT,
            "--expected-payload-sha256",
            PREDECESSOR_PAYLOAD_SHA256,
        ]
    )
    if (
        value.get("source_commit") != PREDECESSOR_SOURCE_COMMIT
        or value.get("payload_sha256") != PREDECESSOR_PAYLOAD_SHA256
        or value.get("release_remained_exact") is not True
        or value.get("host_config_verified") is not False
    ):
        raise GateError("rejected r0001 predecessor release is not exact historical provenance")
    return {
        "candidate": PREDECESSOR_CANDIDATE,
        "source_commit": PREDECESSOR_SOURCE_COMMIT,
        "payload_sha256": PREDECESSOR_PAYLOAD_SHA256,
        "release": "EXACT",
        "bootstrap_authorized": False,
    }



def _validate_rejected_r0003_release() -> dict[str, Any]:
    release = RELEASES_ROOT / REJECTED_R0003_SOURCE_COMMIT
    if not release.exists() or release.is_symlink() or not release.is_dir():
        raise GateError("rejected r0003 release is not exact present directory")
    validator = release / "deploy" / "zero-based-vps" / "target_host_validate.py"
    value = _json_command(
        [
            sys.executable,
            "-B",
            str(validator),
            "--release",
            str(release),
            "--expected-source-commit",
            REJECTED_R0003_SOURCE_COMMIT,
            "--expected-payload-sha256",
            REJECTED_R0003_PAYLOAD_SHA256,
        ]
    )
    if (
        value.get("source_commit") != REJECTED_R0003_SOURCE_COMMIT
        or value.get("payload_sha256") != REJECTED_R0003_PAYLOAD_SHA256
        or value.get("release_remained_exact") is not True
        or value.get("host_config_verified") is not False
    ):
        raise GateError("rejected r0003 release is not exact immutable provenance")
    return {
        "candidate": REJECTED_R0003_CANDIDATE,
        "source_commit": REJECTED_R0003_SOURCE_COMMIT,
        "payload_sha256": REJECTED_R0003_PAYLOAD_SHA256,
        "release": "EXACT",
        "bootstrap_authorized": False,
        "recovery_required": True,
    }


def _service_state(unit: str) -> dict[str, Any]:
    def call(action: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["systemctl", action, unit],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GateError(f"cannot inspect systemd state: {unit}") from exc

    active = call("is-active")
    enabled = call("is-enabled")
    return {
        "active": active.stdout.strip() or "UNKNOWN",
        "active_rc": active.returncode,
        "enabled": enabled.stdout.strip() or "UNKNOWN",
        "enabled_rc": enabled.returncode,
    }


def _load_recovery_module(root: Path):
    path = root / "deploy" / "zero-based-vps" / "operation_control_plane_recovery.py"
    if not path.is_file() or path.is_symlink():
        raise GateError("exact recovery module is missing")
    deploy = str(path.parent)
    if deploy not in sys.path:
        sys.path.insert(0, deploy)
    name = "keelaryn_control_recovery_r0004_exact"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateError("cannot load exact recovery module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _recovery_context(module):
    spec = module.RecoverySpec(
        rejected_source_commit=REJECTED_R0003_SOURCE_COMMIT,
        rejected_payload_sha256=REJECTED_R0003_PAYLOAD_SHA256,
        production_source_commit=PRODUCTION_SOURCE,
        repository="efremov-aleksei-96/keelaryn",
        issue=CONTROL_ISSUE,
        actors="efremov-aleksei-96",
        status_actor=STATUS_ACTOR,
    )
    layout = module.RecoveryLayout(
        install_root=INSTALL_ROOT,
        unit_dir=UNIT_DIR,
        config_dir=CONFIG_DIR,
        bootstrap_root=BOOTSTRAP_ROOT,
        recovery_root=RECOVERY_ROOT,
        transport_root=TRANSPORT_ROOT,
        operation_root=OPERATION_ROOT,
        operation_control_root=OPERATION_CONTROL_ROOT,
        selector=SELECTOR,
        deployment_state_root=STATE_ROOT,
        mutation_gate_root=MUTATION_GATE_ROOT,
    )
    return spec, layout


def _recovery_authority_state(module) -> dict[str, Any]:
    spec, layout = _recovery_context(module)
    if not RECOVERY_ROOT.exists() and not RECOVERY_ROOT.is_symlink():
        return {"state": "ABSENT"}

    try:
        module._private_directory(RECOVERY_ROOT, "operation recovery root")
        prepared_path, completed_path = module._recovery_paths(layout, spec)
        allowed = {prepared_path.name, completed_path.name}
        names = {entry.name for entry in RECOVERY_ROOT.iterdir()}
        if not names.issubset(allowed):
            raise GateError("operation recovery root contains foreign material")
        prepared = module._read_canonical_record(
            prepared_path,
            module.PREPARED_SCHEMA,
        )
        completed = module._read_canonical_record(
            completed_path,
            module.COMPLETED_SCHEMA,
        )
        if prepared is None:
            raise GateError("operation recovery root lacks PREPARED authority")

        rejected_release = RELEASES_ROOT / REJECTED_R0003_SOURCE_COMMIT
        unit_sha256 = {
            unit: hashlib.sha256(
                module._unit_expected(rejected_release, unit)
            ).hexdigest()
            for unit in module.UNIT_NAMES
        }
        receipt_sha256 = hashlib.sha256(
            module._expected_receipt(spec)
        ).hexdigest()
        module._validate_prepared(
            prepared,
            spec,
            unit_sha256,
            receipt_sha256,
            layout,
        )
        prepared_sha = hashlib.sha256(
            module._canonical_json(prepared)
        ).hexdigest()
        if completed is None:
            return {
                "state": "PREPARED",
                "prepared_sha256": prepared_sha,
            }
        module._validate_completed(completed, spec, prepared)
        return {
            "state": "COMPLETED",
            "prepared_sha256": prepared_sha,
            "completed_sha256": hashlib.sha256(
                module._canonical_json(completed)
            ).hexdigest(),
        }
    except GateError:
        raise
    except module.OperationControlRecoveryError as exc:
        raise GateError(f"recovery authority validation failed: {exc}") from exc


def _recovery_live_inspect(module) -> dict[str, Any]:
    spec, layout = _recovery_context(module)
    try:
        value = module.inspect_rejected_install(spec, layout)
    except module.OperationControlRecoveryError as exc:
        raise GateError(f"rejected r0003 live recovery inspection failed: {exc}") from exc
    if (
        value.get("production_boundary_before") != value.get("production_boundary_after")
        or value.get("persistent_mutations_performed") is not False
    ):
        raise GateError("rejected r0003 recovery inspection was not exact read-only")
    return value


def _with_recovery_module(callback):
    release = RELEASES_ROOT / SOURCE_COMMIT
    if release.exists() or release.is_symlink():
        _validate_release(release)
        return callback(_load_recovery_module(release))

    with tempfile.TemporaryDirectory(prefix="keelaryn-control-r0004-recovery-") as td:
        repo = _checkout_source(Path(td))
        return callback(_load_recovery_module(repo))


def _regular_state(path: Path, *, expected_mode: int | None = None) -> str:
    if not path.exists() and not path.is_symlink():
        return "ABSENT"
    if path.is_symlink() or not path.is_file():
        return "INVALID"
    if expected_mode is not None and (path.stat(follow_symlinks=False).st_mode & 0o777) != expected_mode:
        return "INVALID"
    return "PRESENT"


def _directory_state(path: Path, *, expected_mode: int | None = None) -> str:
    if not path.exists() and not path.is_symlink():
        return "ABSENT"
    if path.is_symlink() or not path.is_dir():
        return "INVALID"
    if expected_mode is not None and (path.stat(follow_symlinks=False).st_mode & 0o777) != expected_mode:
        return "INVALID"
    return "PRESENT"


def _bootstrap_transaction_state() -> str:
    if not BOOTSTRAP_ROOT.exists() and not BOOTSTRAP_ROOT.is_symlink():
        return "ABSENT"
    if BOOTSTRAP_ROOT.is_symlink() or not BOOTSTRAP_ROOT.is_dir():
        return "INVALID"
    if (BOOTSTRAP_ROOT.stat(follow_symlinks=False).st_mode & 0o777) != 0o700:
        return "INVALID"
    markers = []
    for entry in BOOTSTRAP_ROOT.iterdir():
        if _TRANSACTION_DIR.fullmatch(entry.name):
            if (
                entry.is_symlink()
                or not entry.is_dir()
                or (entry.stat(follow_symlinks=False).st_mode & 0o777) != 0o700
            ):
                return "INVALID"
            markers.append(entry)
        elif entry.name != "bootstrap-receipt.json":
            return "INVALID"
    if not markers:
        return "ABSENT"
    return "PRESENT_SINGLE" if len(markers) == 1 else "INVALID"


def _rejected_r0002_release_state() -> str:
    release = RELEASES_ROOT / REJECTED_R0002_SOURCE_COMMIT
    if not release.exists() and not release.is_symlink():
        return "ABSENT"
    return "UNEXPECTED_PRESENT"



def _sidecar_observation(*, validate_release: bool) -> dict[str, Any]:
    release = RELEASES_ROOT / SOURCE_COMMIT
    if not release.exists() and not release.is_symlink():
        release_state = "ABSENT"
    else:
        if release.is_symlink() or not release.is_dir():
            release_state = "INVALID"
        elif validate_release:
            _validate_release(release)
            release_state = "EXACT"
        else:
            release_state = "PRESENT_UNVERIFIED"

    rejected_r0003 = _validate_rejected_r0003_release()
    rejected_release = RELEASES_ROOT / REJECTED_R0003_SOURCE_COMMIT

    if not CONTROL_CURRENT.exists() and not CONTROL_CURRENT.is_symlink():
        control_current = "ABSENT"
    elif CONTROL_CURRENT.is_symlink():
        target = os.readlink(CONTROL_CURRENT)
        if target == f"releases/{SOURCE_COMMIT}":
            control_current = "EXACT"
        elif target == f"releases/{REJECTED_R0003_SOURCE_COMMIT}":
            control_current = "REJECTED_R0003"
        else:
            control_current = "OTHER"
    else:
        control_current = "INVALID"

    units: dict[str, str] = {}
    for name in UNIT_NAMES:
        installed = UNIT_DIR / name
        if not installed.exists() and not installed.is_symlink():
            units[name] = "ABSENT"
            continue
        if (
            installed.is_symlink()
            or not installed.is_file()
            or (installed.stat(follow_symlinks=False).st_mode & 0o777) != 0o644
        ):
            units[name] = "INVALID"
            continue
        raw = installed.read_bytes()
        candidate_unit = release / "deploy" / "zero-based-vps" / name
        rejected_unit = rejected_release / "deploy" / "zero-based-vps" / name
        if (
            release.exists()
            and release.is_dir()
            and candidate_unit.is_file()
            and not candidate_unit.is_symlink()
            and raw == candidate_unit.read_bytes()
        ):
            units[name] = "EXACT"
        elif raw == rejected_unit.read_bytes():
            units[name] = "REJECTED_R0003"
        else:
            units[name] = "OTHER"

    predecessor = _validate_rejected_predecessor_release()

    return {
        "release": release_state,
        "predecessor": predecessor,
        "rejected_r0002": {
            "candidate": REJECTED_R0002_CANDIDATE,
            "source_commit": REJECTED_R0002_SOURCE_COMMIT,
            "release": _rejected_r0002_release_state(),
            "bootstrap_authorized": False,
        },
        "rejected_r0003": rejected_r0003,
        "control_current": control_current,
        "config_dir": _directory_state(CONFIG_DIR, expected_mode=0o700),
        "credential": _regular_state(
            CONFIG_DIR / "github-operations.env",
            expected_mode=0o600,
        ),
        "bootstrap_root": _directory_state(
            BOOTSTRAP_ROOT,
            expected_mode=0o700,
        ),
        "bootstrap_transaction": _bootstrap_transaction_state(),
        "bootstrap_receipt": _regular_state(
            BOOTSTRAP_ROOT / "bootstrap-receipt.json",
            expected_mode=0o600,
        )
        if BOOTSTRAP_ROOT.exists() and BOOTSTRAP_ROOT.is_dir()
        else "ABSENT",
        "units": units,
        "services": {name: _service_state(name) for name in UNIT_NAMES},
    }


def _sidecar_clean_for_successor(sidecar: dict[str, Any]) -> bool:
    services_clean = all(
        value.get("active") != "active"
        and value.get("enabled") != "enabled"
        for value in sidecar["services"].values()
    )
    return (
        sidecar["control_current"] == "ABSENT"
        and sidecar["config_dir"] == "ABSENT"
        and sidecar["credential"] == "ABSENT"
        and sidecar["bootstrap_root"] == "ABSENT"
        and sidecar["bootstrap_transaction"] == "ABSENT"
        and sidecar["bootstrap_receipt"] == "ABSENT"
        and all(value == "ABSENT" for value in sidecar["units"].values())
        and services_clean
    )



def reconcile() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    sidecar = _sidecar_observation(validate_release=True)

    def recovery_snapshot(module):
        authority = _recovery_authority_state(module)
        if authority["state"] == "COMPLETED" and not _sidecar_clean_for_successor(sidecar):
            live = {
                "schema": "keelaryn.operation-control-rejected-recovery-authority.v1",
                "recovery_state": "COMPLETED_AUTHORITY",
                "live_inspection_skipped": True,
                "reason": "successor sidecar state is present",
            }
        else:
            live = _recovery_live_inspect(module)
        return {"authority": authority, "live": live}

    recovery = _with_recovery_module(recovery_snapshot)
    after = _production_boundary()
    if before != after:
        raise GateError("production boundary changed during read-only reconcile")
    return {
        "schema": "keelaryn.operation-control-production-reconcile.v2",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "sidecar": sidecar,
        "rejected_r0003_recovery": recovery,
        "persistent_mutations_performed": False,
        "drive_mutated": False,
    }


def recover_r0003() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    pre = _sidecar_observation(validate_release=True)
    if pre["release"] != "ABSENT":
        raise GateError("r0004 release must remain ABSENT during rejected-r0003 recovery")
    if pre["rejected_r0002"]["release"] != "ABSENT":
        raise GateError("rejected r0002 release unexpectedly exists")

    def perform(module):
        authority_before = _recovery_authority_state(module)
        if authority_before["state"] == "COMPLETED":
            raise GateError("rejected r0003 recovery is already completed; do not repeat")
        live_before = _recovery_live_inspect(module)
        if live_before.get("recovery_state") not in {
            "READY",
            "PREPARED_OR_PARTIAL",
            "CLEAN_PENDING_COMPLETION",
        }:
            raise GateError(
                "rejected r0003 state is not one recoverable transaction"
            )
        spec, layout = _recovery_context(module)
        try:
            result = module.cleanup_rejected_install(spec, layout)
        except module.OperationControlRecoveryError as exc:
            raise GateError(f"rejected r0003 cleanup failed: {exc}") from exc
        live_after = _recovery_live_inspect(module)
        authority_after = _recovery_authority_state(module)
        if (
            live_after.get("recovery_state") != "COMPLETED"
            or authority_after.get("state") != "COMPLETED"
        ):
            raise GateError("rejected r0003 cleanup did not reach exact COMPLETED")
        return {
            "authority_before": authority_before,
            "live_before": live_before,
            "cleanup_result": result,
            "live_after": live_after,
            "authority_after": authority_after,
        }

    recovery = _with_recovery_module(perform)
    post = _sidecar_observation(validate_release=True)
    if post["release"] != "ABSENT" or not _sidecar_clean_for_successor(post):
        raise GateError("rejected r0003 cleanup did not leave exact clean successor prestate")

    after = _production_boundary()
    if before != after:
        raise GateError("production boundary changed during rejected r0003 cleanup")
    return {
        "schema": "keelaryn.operation-control-production-recovery.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "rejected_candidate": REJECTED_R0003_CANDIDATE,
        "rejected_source_commit": REJECTED_R0003_SOURCE_COMMIT,
        "recovery": recovery,
        "sidecar_after": post,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "rejected_release_retained": True,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
        "next_action": "MATERIALIZE",
    }



def materialize() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    pre = _sidecar_observation(validate_release=True)
    if pre["release"] == "EXACT":
        raise GateError("candidate release is already materialized; do not repeat materialize")
    if pre["release"] != "ABSENT":
        raise GateError("candidate release prestate is not exact ABSENT")
    if pre["rejected_r0002"]["release"] != "ABSENT":
        raise GateError("rejected r0002 release unexpectedly exists")
    if not _sidecar_clean_for_successor(pre):
        raise GateError("candidate materialization requires exact clean successor sidecar")

    def require_recovered(module):
        authority = _recovery_authority_state(module)
        live = _recovery_live_inspect(module)
        if authority.get("state") != "COMPLETED" or live.get("recovery_state") != "COMPLETED":
            raise GateError("rejected r0003 recovery is not exact COMPLETED")
        return {"authority": authority, "live": live}

    recovery = _with_recovery_module(require_recovered)

    with tempfile.TemporaryDirectory(prefix="keelaryn-control-r0004-") as td:
        work = Path(td)
        repo = _checkout_source(work)
        payload = _build_payload(repo, work)
        materializer = repo / "deploy" / "zero-based-vps" / "materialize_payload.py"
        _json_command(
            [
                sys.executable,
                "-B",
                str(materializer),
                "--payload",
                str(payload),
                "--releases-root",
                str(RELEASES_ROOT),
                "--expected-source-commit",
                SOURCE_COMMIT,
                "--expected-payload-sha256",
                PAYLOAD_SHA256,
            ]
        )

    release = RELEASES_ROOT / SOURCE_COMMIT
    validation = _validate_release(release)
    after = _production_boundary()
    if before != after:
        raise GateError("production boundary changed during sidecar materialization")
    return {
        "schema": "keelaryn.operation-control-production-materialization.v2",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "release_materialized": True,
        "release_validation": validation,
        "rejected_r0003_recovery": recovery,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
        "next_action": "QUALIFY",
    }


def qualify() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    release = RELEASES_ROOT / SOURCE_COMMIT
    validation = _validate_release(release)
    sidecar = _sidecar_observation(validate_release=False)
    if sidecar["release"] != "PRESENT_UNVERIFIED":
        raise GateError("qualified release observation changed unexpectedly")
    sidecar["release"] = "EXACT"
    if sidecar["rejected_r0002"]["release"] != "ABSENT":
        raise GateError("rejected r0002 release unexpectedly exists")
    if not _sidecar_clean_for_successor(sidecar):
        raise GateError("initial r0004 bootstrap prestate is not exact clean")

    def require_recovered(module):
        authority = _recovery_authority_state(module)
        live = _recovery_live_inspect(module)
        if authority.get("state") != "COMPLETED" or live.get("recovery_state") != "COMPLETED":
            raise GateError("rejected r0003 recovery is not exact COMPLETED")
        return {"authority": authority, "live": live}

    recovery = _with_recovery_module(require_recovered)

    after = _production_boundary()
    if before != after:
        raise GateError("production boundary changed during read-only qualification")
    return {
        "schema": "keelaryn.operation-control-production-qualification.v3",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "release_materialized": True,
        "release_only_validation": validation,
        "sidecar_prestate": sidecar,
        "rejected_r0003_recovery": recovery,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "persistent_mutations_performed": False,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
    }

def _load_bootstrap_module(release: Path):
    path = release / "deploy" / "zero-based-vps" / "operation_control_plane_bootstrap.py"
    deploy = str(path.parent)
    if deploy not in sys.path:
        sys.path.insert(0, deploy)
    spec = importlib.util.spec_from_file_location("keelaryn_control_bootstrap_exact", path)
    if spec is None or spec.loader is None:
        raise GateError("cannot load exact bootstrap module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def bootstrap() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    release = RELEASES_ROOT / SOURCE_COMMIT
    validation = _validate_release(release)
    sidecar = _sidecar_observation(validate_release=False)
    if sidecar["release"] != "PRESENT_UNVERIFIED":
        raise GateError("bootstrap release observation changed unexpectedly")
    sidecar["release"] = "EXACT"
    if sidecar["rejected_r0002"]["release"] != "ABSENT":
        raise GateError("rejected r0002 release unexpectedly exists")

    def require_authority(module):
        authority = _recovery_authority_state(module)
        if authority.get("state") != "COMPLETED":
            raise GateError("rejected r0003 recovery authority is not exact COMPLETED")
        return authority

    recovery_authority = _with_recovery_module(require_authority)

    initial = _sidecar_clean_for_successor(sidecar)
    resumable = (
        sidecar["bootstrap_root"] == "PRESENT"
        and sidecar["bootstrap_transaction"] == "PRESENT_SINGLE"
        and sidecar["credential"] in {"ABSENT", "PRESENT"}
        and sidecar["control_current"] in {"ABSENT", "EXACT"}
        and sidecar["bootstrap_receipt"] in {"ABSENT", "PRESENT"}
        and all(value in {"ABSENT", "EXACT", "OTHER"} for value in sidecar["units"].values())
    )
    if not initial and not resumable:
        raise GateError(
            "r0004 bootstrap prestate is neither exact initial clean nor one resumable transaction"
        )

    if initial:
        qualification = qualify()
        boundary_anchor = qualification["production_boundary_after"]
        mode = "INITIAL"
    else:
        boundary_anchor = before
        mode = "RESUME"

    token = getpass.getpass("GitHub fine-grained operations token: ")
    module = _load_bootstrap_module(release)
    receipt = module.install(
        release=release,
        expected_source_commit=SOURCE_COMMIT,
        expected_payload_sha256=PAYLOAD_SHA256,
        repository="efremov-aleksei-96/keelaryn",
        issue=CONTROL_ISSUE,
        actors="efremov-aleksei-96",
        status_actor=STATUS_ACTOR,
        token=token,
        production_current=PRODUCTION_CURRENT,
        control_current=CONTROL_CURRENT,
        unit_dir=UNIT_DIR,
        config_dir=CONFIG_DIR,
        bootstrap_root=BOOTSTRAP_ROOT,
    )
    token = ""

    post = _sidecar_observation(validate_release=True)
    post_exact = (
        post["release"] == "EXACT"
        and post["control_current"] == "EXACT"
        and post["config_dir"] == "PRESENT"
        and post["credential"] == "PRESENT"
        and post["bootstrap_root"] == "PRESENT"
        and post["bootstrap_transaction"] == "PRESENT_SINGLE"
        and post["bootstrap_receipt"] == "PRESENT"
        and all(value == "EXACT" for value in post["units"].values())
        and all(
            value.get("active") == "active"
            and value.get("enabled") == "enabled"
            for value in post["services"].values()
        )
    )
    if not post_exact:
        raise GateError("r0004 bootstrap returned without exact active sidecar state")

    recovery_after = _with_recovery_module(require_authority)
    after = _production_boundary()
    if after != boundary_anchor:
        raise GateError("production boundary changed during sidecar bootstrap")
    return {
        "schema": "keelaryn.operation-control-production-bootstrap.v3",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "bootstrap_mode": mode,
        "bootstrap_receipt": receipt,
        "release_validation": validation,
        "rejected_r0003_recovery_authority": recovery_after,
        "sidecar_after": post,
        "production_boundary_after": after,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
        "next_action": "GITHUB_RUNTIME_SELFTEST",
    }


def selftest() -> dict[str, Any]:
    expected = {
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "production_source": PRODUCTION_SOURCE,
        "control_issue": CONTROL_ISSUE,
        "status_actor": STATUS_ACTOR,
        "config_dir": str(CONFIG_DIR),
        "recovery_root": str(RECOVERY_ROOT),
        "transport_root": str(TRANSPORT_ROOT),
        "operation_root": str(OPERATION_ROOT),
        "operation_control_root": str(OPERATION_CONTROL_ROOT),
        "historical_r0001_candidate": PREDECESSOR_CANDIDATE,
        "rejected_r0002_candidate": REJECTED_R0002_CANDIDATE,
        "rejected_r0003_candidate": REJECTED_R0003_CANDIDATE,
        "rejected_r0003_source_commit": REJECTED_R0003_SOURCE_COMMIT,
        "rejected_r0003_payload_sha256": REJECTED_R0003_PAYLOAD_SHA256,
    }
    if len(SOURCE_COMMIT) != 40 or len(SOURCE_TREE) != 40 or len(PAYLOAD_SHA256) != 64:
        raise GateError("frozen identities have invalid lengths")
    if len(REJECTED_R0003_SOURCE_COMMIT) != 40 or len(REJECTED_R0003_PAYLOAD_SHA256) != 64:
        raise GateError("rejected r0003 identities have invalid lengths")
    simulated_inactive = subprocess.CompletedProcess(
        ["systemctl", "is-active", "keelaryn-drive.service"],
        3,
        stdout="inactive\n",
        stderr="",
    )
    if simulated_inactive.returncode not in {0, 3} or simulated_inactive.stdout.strip() != "inactive":
        raise GateError("inactive systemd classification selftest failed")
    return {
        "schema": "keelaryn.operation-control-gate-selftest.v2",
        "gate_revision": GATE_REVISION,
        **expected,
        "separate_rejected_r0003_recovery_surface": True,
        "recovery_authority_persists_across_successor_bootstrap": True,
        "fresh_token_required_after_rejected_credential_cleanup": True,
        "systemd_inactive_exit3_accepted": True,
        "pass": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-control-r0004-gate")
    parser.add_argument(
        "command",
        choices=(
            "selftest",
            "reconcile",
            "recover-r0003",
            "materialize",
            "qualify",
            "bootstrap",
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "selftest":
            value = selftest()
        elif args.command == "reconcile":
            value = reconcile()
        elif args.command == "recover-r0003":
            value = recover_r0003()
        elif args.command == "materialize":
            value = materialize()
        elif args.command == "qualify":
            value = qualify()
        else:
            value = bootstrap()
    except (GateError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
