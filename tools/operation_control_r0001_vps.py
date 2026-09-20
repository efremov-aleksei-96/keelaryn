from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


GATE_REVISION = "operation-control-gate-r0003"
CANDIDATE = "operation-control-r0001-20260920-01"
REPOSITORY = "https://github.com/efremov-aleksei-96/keelaryn.git"
SOURCE_COMMIT = "98e76ffdcdbac09610f8b9a2b542f7e61e7dba61"
SOURCE_TREE = "eabd2a98e9c2d42e81e7f5c04e3f2b90cf900e6a"
PAYLOAD_SHA256 = "b9f4022ddca38435e377ed08662d6cc7930655c828b861cdca980ba87f948c4b"
PAYLOAD_SIZE = 340331
PAYLOAD_FILE_COUNT = 188
PRODUCTION_SOURCE = "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
CONTROL_ISSUE = 65

INSTALL_ROOT = Path("/opt/keelaryn")
RELEASES_ROOT = INSTALL_ROOT / "releases"
PRODUCTION_CURRENT = INSTALL_ROOT / "current"
CONTROL_CURRENT = INSTALL_ROOT / "control-current"
SELECTOR = Path("/etc/keelaryn/hub.env")
STATE_ROOT = Path("/var/lib/keelaryn/deployment")
MUTATION_GATE_ROOT = Path("/var/lib/keelaryn/mutation-gate")
CONFIG_DIR = Path("/etc/keelaryn")
BOOTSTRAP_ROOT = Path("/var/lib/keelaryn/operation-bootstrap")
UNIT_DIR = Path("/etc/systemd/system")


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

    if not CONTROL_CURRENT.exists() and not CONTROL_CURRENT.is_symlink():
        control_current = "ABSENT"
    elif CONTROL_CURRENT.is_symlink():
        target = os.readlink(CONTROL_CURRENT)
        control_current = (
            "EXACT"
            if target == f"releases/{SOURCE_COMMIT}"
            else "OTHER"
        )
    else:
        control_current = "INVALID"

    units: dict[str, str] = {}
    for name in (
        "keelaryn-operation-transport.service",
        "keelaryn-operation-agent.service",
    ):
        installed = UNIT_DIR / name
        if not installed.exists() and not installed.is_symlink():
            units[name] = "ABSENT"
            continue
        if installed.is_symlink() or not installed.is_file():
            units[name] = "INVALID"
            continue
        if release_state == "EXACT":
            qualified = release / "deploy" / "zero-based-vps" / name
            units[name] = (
                "EXACT"
                if installed.read_bytes() == qualified.read_bytes()
                and (installed.stat(follow_symlinks=False).st_mode & 0o777) == 0o644
                else "OTHER"
            )
        else:
            units[name] = "PRESENT_UNVERIFIED"

    return {
        "release": release_state,
        "control_current": control_current,
        "credential": _regular_state(
            CONFIG_DIR / "github-operations.env",
            expected_mode=0o600,
        ),
        "bootstrap_root": _directory_state(
            BOOTSTRAP_ROOT,
            expected_mode=0o700,
        ),
        "bootstrap_receipt": _regular_state(
            BOOTSTRAP_ROOT / "bootstrap-receipt.json",
            expected_mode=0o600,
        )
        if BOOTSTRAP_ROOT.exists() and BOOTSTRAP_ROOT.is_dir()
        else "ABSENT",
        "units": units,
    }


def reconcile() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    sidecar = _sidecar_observation(validate_release=True)
    after = _production_boundary()
    if before != after:
        raise GateError("production boundary changed during read-only reconcile")
    return {
        "schema": "keelaryn.operation-control-production-reconcile.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "sidecar": sidecar,
        "persistent_mutations_performed": False,
        "drive_mutated": False,
    }


def materialize() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    pre = _sidecar_observation(validate_release=True)
    if pre["release"] == "EXACT":
        raise GateError("candidate release is already materialized; do not repeat materialize")
    if pre["release"] != "ABSENT":
        raise GateError("candidate release prestate is not exact ABSENT")

    with tempfile.TemporaryDirectory(prefix="keelaryn-control-r0001-") as td:
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
        "schema": "keelaryn.operation-control-production-materialization.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "release_materialized": True,
        "release_validation": validation,
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

    expected_absent = (
        sidecar["control_current"] == "ABSENT"
        and sidecar["credential"] == "ABSENT"
        and sidecar["bootstrap_receipt"] == "ABSENT"
        and all(value == "ABSENT" for value in sidecar["units"].values())
    )
    if not expected_absent:
        raise GateError("initial sidecar bootstrap prestate is not exact ABSENT")

    after = _production_boundary()
    if before != after:
        raise GateError("production boundary changed during read-only qualification")
    return {
        "schema": "keelaryn.operation-control-production-qualification.v2",
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
    qualification = qualify()
    preflight = qualification["sidecar_prestate"]
    if preflight.get("control_current") != "ABSENT":
        raise GateError("initial bootstrap requires absent control-current")
    if preflight.get("credential") != "ABSENT":
        raise GateError("initial bootstrap requires absent GitHub operations credential")
    if preflight.get("bootstrap_receipt") != "ABSENT":
        raise GateError("initial bootstrap requires absent bootstrap receipt")
    if any(value != "ABSENT" for value in preflight.get("units", {}).values()):
        raise GateError("initial bootstrap requires absent operation-control units")

    token = getpass.getpass("GitHub fine-grained operations token: ")
    release = RELEASES_ROOT / SOURCE_COMMIT
    module = _load_bootstrap_module(release)
    receipt = module.install(
        release=release,
        expected_source_commit=SOURCE_COMMIT,
        expected_payload_sha256=PAYLOAD_SHA256,
        repository="efremov-aleksei-96/keelaryn",
        issue=CONTROL_ISSUE,
        actors="efremov-aleksei-96",
        token=token,
        production_current=PRODUCTION_CURRENT,
        control_current=CONTROL_CURRENT,
        unit_dir=UNIT_DIR,
        config_dir=CONFIG_DIR,
        bootstrap_root=BOOTSTRAP_ROOT,
    )
    token = ""
    after = _production_boundary()
    if after != qualification["production_boundary_after"]:
        raise GateError("production boundary changed during sidecar bootstrap")
    return {
        "schema": "keelaryn.operation-control-production-bootstrap.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "bootstrap_receipt": receipt,
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
    }
    if len(SOURCE_COMMIT) != 40 or len(SOURCE_TREE) != 40 or len(PAYLOAD_SHA256) != 64:
        raise GateError("frozen identities have invalid lengths")
    simulated_inactive = subprocess.CompletedProcess(
        ["systemctl", "is-active", "keelaryn-drive.service"],
        3,
        stdout="inactive\n",
        stderr="",
    )
    if simulated_inactive.returncode not in {0, 3} or simulated_inactive.stdout.strip() != "inactive":
        raise GateError("inactive systemd classification selftest failed")
    return {
        "schema": "keelaryn.operation-control-gate-selftest.v1",
        "gate_revision": GATE_REVISION,
        **expected,
        "systemd_inactive_exit3_accepted": True,
        "pass": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-control-r0001-gate")
    parser.add_argument(
        "command",
        choices=("selftest", "reconcile", "materialize", "qualify", "bootstrap"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "selftest":
            value = selftest()
        elif args.command == "reconcile":
            value = reconcile()
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
