from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from hub_cutover import HubCutoverError, _read_selector, _selector_parent
from materialize_payload import PayloadMaterializeError, verify_release_directory

SCHEMA = "keelaryn.zero-vps-target-host-validation.v1"
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
)


class TargetHostValidationError(RuntimeError):
    pass


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
) -> dict[str, Any]:
    release = release.absolute()
    if (selector_path is None) != (installed_unit_dir is None):
        raise TargetHostValidationError(
            "selector-path and installed-unit-dir must be supplied together for host-config validation"
        )

    identity = verify_release_directory(
        release,
        expected_source_commit=expected_source_commit,
        expected_payload_sha256=expected_payload_sha256,
    )
    compiled = _compile_python_sources(release)
    cli_surfaces = _validate_cli_surfaces(release)

    host_config_verified = selector_path is not None
    if host_config_verified:
        assert selector_path is not None
        assert installed_unit_dir is not None
        validate_selector_file(selector_path)
        validate_installed_units(release, installed_unit_dir)

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
        )
    except (TargetHostValidationError, PayloadMaterializeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
