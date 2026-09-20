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


GATE_REVISION = "operation-control-gate-r0001"
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

    active = _run(["systemctl", "is-active", "keelaryn-drive.service"])
    if active.stdout.strip() != "inactive":
        raise GateError("production writer is not INACTIVE at prepared boundary")

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


def _ensure_release(repo: Path, payload: Path) -> Path:
    release = RELEASES_ROOT / SOURCE_COMMIT
    materializer = repo / "deploy" / "zero-based-vps" / "materialize_payload.py"
    if not release.exists() and not release.is_symlink():
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
    return release


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


def qualify() -> dict[str, Any]:
    _require_root()
    before = _production_boundary()
    with tempfile.TemporaryDirectory(prefix="keelaryn-control-r0001-") as td:
        work = Path(td)
        repo = _checkout_source(work)
        payload = _build_payload(repo, work)
        release = _ensure_release(repo, payload)
        module = _load_bootstrap_module(release)
        preflight = module.preflight(
            release=release,
            expected_source_commit=SOURCE_COMMIT,
            expected_payload_sha256=PAYLOAD_SHA256,
            production_current=PRODUCTION_CURRENT,
            control_current=CONTROL_CURRENT,
            unit_dir=UNIT_DIR,
            config_dir=CONFIG_DIR,
            bootstrap_root=BOOTSTRAP_ROOT,
        )
    after = _production_boundary()
    if before != after:
        raise GateError("production boundary changed during sidecar qualification")
    return {
        "schema": "keelaryn.operation-control-production-qualification.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "release_materialized": True,
        "release_only_validation": "PASS",
        "bootstrap_preflight": preflight,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "production_current_mutated": False,
        "hub_cutover_mutated": False,
        "drive_mutated": False,
    }


def bootstrap() -> dict[str, Any]:
    qualification = qualify()
    preflight = qualification["bootstrap_preflight"]
    if preflight.get("control_current_state") != "ABSENT":
        raise GateError("initial bootstrap requires absent control-current")
    if preflight.get("credential_state") != "ABSENT":
        raise GateError("initial bootstrap requires absent GitHub operations credential")
    if preflight.get("receipt_state") != "ABSENT":
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
    return {
        "schema": "keelaryn.operation-control-gate-selftest.v1",
        "gate_revision": GATE_REVISION,
        **expected,
        "pass": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-control-r0001-gate")
    parser.add_argument("command", choices=("selftest", "qualify", "bootstrap"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "selftest":
            value = selftest()
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
