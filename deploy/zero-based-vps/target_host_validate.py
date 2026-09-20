from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

CORE_ROOT = Path(__file__).resolve().parents[2] / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from keelaryn_core.drive_mutation_gate import (  # noqa: E402
    DriveMutationGateAdmin,
    DriveMutationGateError,
)

from hub_cutover import HubCutoverError, _read_selector, _selector_parent
from materialize_payload import PayloadMaterializeError, verify_release_directory

SCHEMA = "keelaryn.zero-vps-target-host-validation.v3"
TRANSACTION_RECORD_RE = re.compile(r"[0-9a-f]{32}\.json")
UNIT_NAMES = (
    "keelaryn-drive.service",
    "keelaryn-drive-bootstrap.service",
)
CLI_SURFACES = (
    "drive_poller",
    "workspace_cli",
    "pilot_cli",
    "release_switch",
    "hub_cutover",
    "hub_cutover_rehearsal",
    "deployment_state_normalize",
    "operation_runtime",
)


class TargetHostValidationError(RuntimeError):
    pass


def _owned_directory(path: Path, label: str, *, exact_mode: int | None = None) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_dir():
        raise TargetHostValidationError(f"{label} must be a real directory")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid():
        raise TargetHostValidationError(f"{label} must be owned by the current effective user")
    mode = stat.S_IMODE(info.st_mode)
    if exact_mode is not None:
        if mode != exact_mode:
            raise TargetHostValidationError(f"{label} must have mode {exact_mode:04o}")
    elif mode & 0o022:
        raise TargetHostValidationError(f"{label} must not be group/world-writable")
    return path


def _private_regular(path: Path, label: str) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise TargetHostValidationError(f"{label} must be a regular file")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise TargetHostValidationError(f"{label} must be owner-controlled mode 0600")
    return path


def validate_active_release(release: Path, install_root: Path, expected_source_commit: str) -> None:
    release = release.absolute()
    install_root = _owned_directory(install_root, "install root")
    releases = _owned_directory(install_root / "releases", "install releases directory")
    expected_release = _owned_directory(
        releases / expected_source_commit,
        "active qualified release",
        exact_mode=0o555,
    )
    current = install_root / "current"
    if not current.is_symlink():
        raise TargetHostValidationError("current must be one canonical relative symlink")
    if current.lstat().st_uid != os.geteuid():
        raise TargetHostValidationError("current symlink must be owned by the current effective user")
    try:
        target = os.readlink(current)
    except OSError as exc:
        raise TargetHostValidationError("cannot read current symlink") from exc
    if target != f"releases/{expected_source_commit}":
        raise TargetHostValidationError("current symlink does not select the exact qualified release")
    try:
        same_release = os.path.samefile(release, expected_release)
    except OSError as exc:
        raise TargetHostValidationError("cannot bind validated release to active current") from exc
    if not same_release:
        raise TargetHostValidationError("validated release is not the exact active current release")


def validate_deployment_state(state_root: Path) -> None:
    state_root = _owned_directory(state_root, "deployment state root", exact_mode=0o700)
    terminal = _owned_directory(state_root / "terminal", "deployment terminal directory", exact_mode=0o700)
    history = _owned_directory(state_root / "history", "deployment history directory", exact_mode=0o700)
    lock = _private_regular(state_root / "LOCK", "deployment lock")
    flags = os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock, flags)
    except OSError as exc:
        raise TargetHostValidationError("cannot open deployment lock without following symlinks") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise TargetHostValidationError("deployment lock must remain owner-controlled regular mode 0600")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TargetHostValidationError(
                "deployment state is busy; target-host qualification requires an idle transaction root"
            ) from exc
        try:
            active = state_root / "ACTIVE_TRANSACTION.json"
            if active.exists() or active.is_symlink():
                raise TargetHostValidationError("deployment state is not IDLE; active transaction authority exists")
            allowed = {"LOCK", "terminal", "history"}
            if {item.name for item in state_root.iterdir()} != allowed:
                raise TargetHostValidationError("deployment state root contains unexpected or incomplete objects")
            for directory, label in ((terminal, "terminal"), (history, "history")):
                for item in sorted(directory.iterdir(), key=lambda value: value.name):
                    if not TRANSACTION_RECORD_RE.fullmatch(item.name):
                        raise TargetHostValidationError(
                            f"deployment {label} contains an invalid transaction record name"
                        )
                    _private_regular(item, f"deployment {label} transaction record")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def validate_mutation_gate(root: Path) -> None:
    try:
        admin = DriveMutationGateAdmin(root)
        with admin.locked():
            if admin.read() is not None:
                raise TargetHostValidationError(
                    "production Drive mutation gate is inhibited"
                )
            observed = {item.name for item in root.absolute().iterdir()}
            if observed != {"LOCK"}:
                raise TargetHostValidationError(
                    "production Drive mutation gate contains unexpected objects"
                )
    except DriveMutationGateError as exc:
        raise TargetHostValidationError(
            f"production Drive mutation gate validation failed: {exc}"
        ) from exc


def validate_selector_file(path: Path) -> None:
    path = path.absolute()
    try:
        _selector_parent(path)
        _read_selector(path)
    except HubCutoverError as exc:
        raise TargetHostValidationError(f"Hub selector validation failed: {exc}") from exc


def validate_installed_units(release: Path, unit_dir: Path) -> None:
    release = release.absolute()
    unit_dir = unit_dir.absolute()
    if unit_dir.is_symlink() or not unit_dir.is_dir():
        raise TargetHostValidationError("installed unit directory must be a real directory")
    info = unit_dir.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise TargetHostValidationError(
            "installed unit directory must be owned by the current user and not group/world-writable"
        )

    qualified_root = release / "deploy" / "zero-based-vps"
    for name in UNIT_NAMES:
        qualified = qualified_root / name
        installed = unit_dir / name
        if qualified.is_symlink() or not qualified.is_file():
            raise TargetHostValidationError(f"qualified unit is missing/not regular: {name}")
        if installed.is_symlink() or not installed.is_file():
            raise TargetHostValidationError(f"installed unit is missing/not regular: {name}")
        installed_info = installed.stat(follow_symlinks=False)
        if installed_info.st_uid != os.geteuid() or stat.S_IMODE(installed_info.st_mode) != 0o644:
            raise TargetHostValidationError(f"installed unit must be owner-controlled mode 0644: {name}")
        if installed.read_bytes() != qualified.read_bytes():
            raise TargetHostValidationError(f"installed unit differs from qualified release: {name}")


def _compile_python_sources(release: Path) -> int:
    count = 0
    for path in sorted(release.rglob("*.py")):
        if path.is_symlink() or not path.is_file():
            raise TargetHostValidationError(
                f"Python validation encountered non-regular path: {path.relative_to(release).as_posix()}"
            )
        try:
            compile(path.read_bytes(), str(path), "exec")
        except (OSError, SyntaxError) as exc:
            raise TargetHostValidationError(
                f"Python source validation failed: {path.relative_to(release).as_posix()}"
            ) from exc
        count += 1
    if count == 0:
        raise TargetHostValidationError("release contains no Python sources")
    return count


def _cli_commands(release: Path) -> dict[str, list[str]]:
    deploy = release / "deploy" / "zero-based-vps"
    return {
        "drive_poller": [sys.executable, "-B", "-m", "keelaryn_core.drive_poller", "--help"],
        "workspace_cli": [sys.executable, "-B", "-m", "keelaryn_core.workspace_cli", "--help"],
        "pilot_cli": [sys.executable, "-B", "-m", "keelaryn_core.pilot_cli", "--help"],
        "release_switch": [sys.executable, "-B", str(deploy / "release_switch.py"), "--help"],
        "hub_cutover": [sys.executable, "-B", str(deploy / "hub_cutover.py"), "--help"],
        "hub_cutover_rehearsal": [
            sys.executable,
            "-B",
            str(deploy / "hub_cutover_rehearsal.py"),
            "--help",
        ],
        "deployment_state_normalize": [
            sys.executable,
            "-B",
            str(deploy / "deployment_state_normalize.py"),
            "--help",
        ],
        "operation_runtime": [
            sys.executable,
            "-B",
            "-m",
            "keelaryn_core.operation_cli",
            "--help",
        ],
    }


def _validate_cli_surfaces(release: Path) -> tuple[str, ...]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(release / "core")
    verified: list[str] = []
    for name, command in _cli_commands(release).items():
        try:
            completed = subprocess.run(
                command,
                cwd=release,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TargetHostValidationError(f"CLI validation failed to execute: {name}") from exc
        if completed.returncode != 0:
            raise TargetHostValidationError(
                f"CLI validation returned nonzero for {name}: {completed.returncode}"
            )
        verified.append(name)
    return tuple(verified)


def validate_target_host(
    release: Path,
    *,
    expected_source_commit: str,
    expected_payload_sha256: str,
    selector_path: Path | None = None,
    installed_unit_dir: Path | None = None,
    install_root: Path | None = None,
    deployment_state_root: Path | None = None,
    mutation_gate_root: Path | None = None,
) -> dict[str, Any]:
    release = release.absolute()
    host_arguments = (
        selector_path,
        installed_unit_dir,
        install_root,
        deployment_state_root,
        mutation_gate_root,
    )
    provided = sum(value is not None for value in host_arguments)
    if provided not in {0, len(host_arguments)}:
        raise TargetHostValidationError(
            "selector-path, installed-unit-dir, install-root, deployment-state-root, "
            "and mutation-gate-root must be supplied together for host-config validation"
        )

    identity = verify_release_directory(
        release,
        expected_source_commit=expected_source_commit,
        expected_payload_sha256=expected_payload_sha256,
    )
    compiled = _compile_python_sources(release)
    cli_surfaces = _validate_cli_surfaces(release)

    host_config_verified = provided == len(host_arguments)
    if host_config_verified:
        assert selector_path is not None
        assert installed_unit_dir is not None
        assert install_root is not None
        assert deployment_state_root is not None
        assert mutation_gate_root is not None
        validate_selector_file(selector_path)
        validate_installed_units(release, installed_unit_dir)
        validate_active_release(release, install_root, identity["source_commit"])
        validate_deployment_state(deployment_state_root)
        validate_mutation_gate(mutation_gate_root)

    # Re-read the immutable release after every validation action. Any bytecode,
    # cache material or other accidental target-host mutation fails closed here.
    final_identity = verify_release_directory(
        release,
        expected_source_commit=expected_source_commit,
        expected_payload_sha256=expected_payload_sha256,
    )
    if final_identity != identity:
        raise TargetHostValidationError("release identity changed during target-host validation")

    return {
        "schema": SCHEMA,
        "source_commit": identity["source_commit"],
        "payload_sha256": identity["payload_sha256"],
        "payload_size": identity["payload_size"],
        "file_count": identity["file_count"],
        "python_files_compiled": compiled,
        "cli_surfaces_verified": list(cli_surfaces),
        "host_config_verified": host_config_verified,
        "selector_verified": host_config_verified,
        "installed_units_verified": host_config_verified,
        "active_release_verified": host_config_verified,
        "deployment_state_verified": host_config_verified,
        "deployment_state_idle": host_config_verified,
        "mutation_gate_verified": host_config_verified,
        "mutation_gate_idle": host_config_verified,
        "release_remained_exact": True,
        "development_test_suite_executed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-zero-target-host-validate")
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-payload-sha256", required=True)
    parser.add_argument("--selector-path", type=Path)
    parser.add_argument("--installed-unit-dir", type=Path)
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--deployment-state-root", type=Path)
    parser.add_argument("--mutation-gate-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = validate_target_host(
            args.release,
            expected_source_commit=args.expected_source_commit,
            expected_payload_sha256=args.expected_payload_sha256,
            selector_path=args.selector_path,
            installed_unit_dir=args.installed_unit_dir,
            install_root=args.install_root,
            deployment_state_root=args.deployment_state_root,
            mutation_gate_root=args.mutation_gate_root,
        )
    except (TargetHostValidationError, PayloadMaterializeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
