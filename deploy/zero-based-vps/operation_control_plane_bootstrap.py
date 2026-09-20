from __future__ import annotations

import argparse
import getpass
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from materialize_payload import PayloadMaterializeError, verify_release_directory


SCHEMA = "keelaryn.operation-control-bootstrap.v1"
UNIT_NAMES = (
    "keelaryn-operation-transport.service",
    "keelaryn-operation-agent.service",
)
_TOKEN = re.compile(r"^[A-Za-z0-9_]{20,255}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ACTOR = re.compile(r"^[A-Za-z0-9-]{1,39}$")
_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ControlPlaneBootstrapError(RuntimeError):
    pass


def _require_root() -> None:
    if os.geteuid() != 0:
        raise ControlPlaneBootstrapError("control-plane bootstrap requires root")


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


def _private_parent(path: Path) -> Path:
    path = path.absolute()
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ControlPlaneBootstrapError("private parent cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise ControlPlaneBootstrapError("private parent must be one real directory")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ControlPlaneBootstrapError(
            "private parent must be current-user owned mode 0700"
        )
    return path


def _private_parent_state(path: Path) -> str:
    path = path.absolute()
    if not path.exists() and not path.is_symlink():
        return "ABSENT"
    _private_parent(path)
    return "PRESENT"


def _create_private_parent(path: Path) -> bool:
    path = path.absolute()
    if _private_parent_state(path) == "PRESENT":
        return False
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ControlPlaneBootstrapError("private parent container is invalid")
    try:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        _private_parent(path)
    except BaseException:
        try:
            path.rmdir()
        except OSError:
            pass
        raise
    return True


def _atomic_file(path: Path, raw: bytes, mode: int) -> None:
    parent = path.parent
    temp = parent / f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        os.replace(temp, path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


def _credential_bytes(
    *,
    token: str,
    repository: str,
    issue: int,
    actors: str,
) -> bytes:
    if _TOKEN.fullmatch(token) is None:
        raise ControlPlaneBootstrapError("GitHub operations token format is invalid")
    if _REPOSITORY.fullmatch(repository) is None:
        raise ControlPlaneBootstrapError("GitHub operations repository is invalid")
    if isinstance(issue, bool) or issue < 1:
        raise ControlPlaneBootstrapError("GitHub operations issue is invalid")
    actor_values = [value.strip() for value in actors.split(",") if value.strip()]
    if not actor_values or any(_ACTOR.fullmatch(value) is None for value in actor_values):
        raise ControlPlaneBootstrapError("GitHub operations actor allowlist is invalid")
    if len(set(actor_values)) != len(actor_values):
        raise ControlPlaneBootstrapError("GitHub operations actor allowlist has duplicates")
    return (
        f"KEELARYN_GITHUB_OPERATIONS_TOKEN={token}\n"
        f"KEELARYN_GITHUB_OPERATIONS_REPOSITORY={repository}\n"
        f"KEELARYN_GITHUB_OPERATIONS_ISSUE={issue}\n"
        f"KEELARYN_GITHUB_OPERATIONS_ACTORS={','.join(actor_values)}\n"
    ).encode("ascii")


def _readlink_exact(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if not path.is_symlink():
        raise ControlPlaneBootstrapError(f"{path.name} must be a symlink or absent")
    try:
        return os.readlink(path)
    except OSError as exc:
        raise ControlPlaneBootstrapError(f"{path.name} cannot be read") from exc


def _regular_exact(path: Path, *, mode: int, raw: bytes | None = None) -> None:
    if path.is_symlink() or not path.is_file():
        raise ControlPlaneBootstrapError(f"{path.name} must be one regular file")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode:
        raise ControlPlaneBootstrapError(
            f"{path.name} must be current-user owned mode {mode:04o}"
        )
    if raw is not None and path.read_bytes() != raw:
        raise ControlPlaneBootstrapError(f"{path.name} bytes differ from expected")


def _systemctl(args: list[str]) -> subprocess.CompletedProcess[str]:
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
        raise ControlPlaneBootstrapError("systemctl invocation failed") from exc


def _must_systemctl(args: list[str]) -> None:
    completed = _systemctl(args)
    if completed.returncode != 0:
        raise ControlPlaneBootstrapError(
            "systemctl operation failed: " + " ".join(args)
        )


def _is_active(unit: str) -> bool:
    completed = _systemctl(["is-active", "--quiet", unit])
    return completed.returncode == 0


def preflight(
    *,
    release: Path,
    expected_source_commit: str,
    expected_payload_sha256: str,
    production_current: Path,
    control_current: Path,
    unit_dir: Path,
    config_dir: Path,
    bootstrap_root: Path,
) -> dict[str, Any]:
    _require_root()
    if _OID.fullmatch(expected_source_commit) is None:
        raise ControlPlaneBootstrapError("expected source commit is invalid")
    if _SHA256.fullmatch(expected_payload_sha256) is None:
        raise ControlPlaneBootstrapError("expected payload SHA-256 is invalid")

    release = release.absolute()
    try:
        identity = verify_release_directory(
            release,
            expected_source_commit=expected_source_commit,
            expected_payload_sha256=expected_payload_sha256,
        )
    except PayloadMaterializeError as exc:
        raise ControlPlaneBootstrapError("qualified control release validation failed") from exc

    if release.name != expected_source_commit:
        raise ControlPlaneBootstrapError("release directory name is not exact source commit")
    if release.parent != production_current.absolute().parent / "releases":
        raise ControlPlaneBootstrapError("release is outside canonical releases root")

    production_target = _readlink_exact(production_current.absolute())
    if production_target is None:
        raise ControlPlaneBootstrapError("production current selector is absent")

    expected_control_target = f"releases/{expected_source_commit}"
    observed_control = _readlink_exact(control_current.absolute())
    if observed_control not in {None, expected_control_target}:
        raise ControlPlaneBootstrapError("control-current selects another release")

    if pwd.getpwnam("keelaryn").pw_uid < 1:
        raise ControlPlaneBootstrapError("keelaryn service account is invalid")

    unit_dir = unit_dir.absolute()
    if unit_dir.is_symlink() or not unit_dir.is_dir():
        raise ControlPlaneBootstrapError("systemd unit directory is invalid")
    qualified_units = release / "deploy" / "zero-based-vps"
    unit_states: dict[str, str] = {}
    for name in UNIT_NAMES:
        source = qualified_units / name
        if source.is_symlink() or not source.is_file():
            raise ControlPlaneBootstrapError(f"qualified unit missing: {name}")
        target = unit_dir / name
        if not target.exists() and not target.is_symlink():
            unit_states[name] = "ABSENT"
        else:
            _regular_exact(target, mode=0o644, raw=source.read_bytes())
            unit_states[name] = "EXACT"

    config_dir = config_dir.absolute()
    config_dir_state = _private_parent_state(config_dir)
    credential = config_dir / "github-operations.env"
    credential_state = "ABSENT"
    if credential.exists() or credential.is_symlink():
        if config_dir_state != "PRESENT":
            raise ControlPlaneBootstrapError(
                "credential exists without a valid private config directory"
            )
        _regular_exact(credential, mode=0o600)
        credential_state = "PRESENT"

    bootstrap_root = bootstrap_root.absolute()
    bootstrap_root_state = _private_parent_state(bootstrap_root)
    receipt = bootstrap_root / "bootstrap-receipt.json"
    receipt_state = "ABSENT"
    if receipt.exists() or receipt.is_symlink():
        if bootstrap_root_state != "PRESENT":
            raise ControlPlaneBootstrapError(
                "receipt exists without a valid private bootstrap root"
            )
        _regular_exact(receipt, mode=0o600)
        receipt_state = "PRESENT"

    return {
        "schema": SCHEMA,
        "source_commit": identity["source_commit"],
        "payload_sha256": identity["payload_sha256"],
        "production_current_target": production_target,
        "control_current_state": (
            "EXACT" if observed_control == expected_control_target else "ABSENT"
        ),
        "units": unit_states,
        "config_dir_state": config_dir_state,
        "credential_state": credential_state,
        "bootstrap_root_state": bootstrap_root_state,
        "receipt_state": receipt_state,
    }


def install(
    *,
    release: Path,
    expected_source_commit: str,
    expected_payload_sha256: str,
    repository: str,
    issue: int,
    actors: str,
    token: str,
    production_current: Path,
    control_current: Path,
    unit_dir: Path,
    config_dir: Path,
    bootstrap_root: Path,
    systemctl: Callable[[list[str]], None] = _must_systemctl,
    active_probe: Callable[[str], bool] = _is_active,
) -> dict[str, Any]:
    before = preflight(
        release=release,
        expected_source_commit=expected_source_commit,
        expected_payload_sha256=expected_payload_sha256,
        production_current=production_current,
        control_current=control_current,
        unit_dir=unit_dir,
        config_dir=config_dir,
        bootstrap_root=bootstrap_root,
    )
    if before["receipt_state"] == "PRESENT":
        raise ControlPlaneBootstrapError("bootstrap receipt already exists")
    if before["credential_state"] != "ABSENT":
        raise ControlPlaneBootstrapError(
            "bootstrap refuses to replace an existing GitHub operations credential"
        )
    if before["control_current_state"] != "ABSENT":
        raise ControlPlaneBootstrapError(
            "bootstrap refuses to replace an existing control-current selector"
        )
    if any(value != "ABSENT" for value in before["units"].values()):
        raise ControlPlaneBootstrapError(
            "bootstrap refuses to replace existing operation-control units"
        )
    for unit in UNIT_NAMES:
        if active_probe(unit):
            raise ControlPlaneBootstrapError(
                "bootstrap refuses while an operation-control unit is active"
            )

    credential_raw = _credential_bytes(
        token=token,
        repository=repository,
        issue=issue,
        actors=actors,
    )
    production_before = before["production_current_target"]
    release = release.absolute()
    unit_dir = unit_dir.absolute()
    config_dir = config_dir.absolute()
    bootstrap_root = bootstrap_root.absolute()
    control_current = control_current.absolute()
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    attempted_units: list[str] = []

    try:
        if before["config_dir_state"] == "ABSENT":
            if _create_private_parent(config_dir):
                created_dirs.append(config_dir)
        else:
            _private_parent(config_dir)

        if before["bootstrap_root_state"] == "ABSENT":
            if _create_private_parent(bootstrap_root):
                created_dirs.append(bootstrap_root)
        else:
            _private_parent(bootstrap_root)

        credential = config_dir / "github-operations.env"
        created_files.append(credential)
        _atomic_file(credential, credential_raw, 0o600)

        for name in UNIT_NAMES:
            source = release / "deploy" / "zero-based-vps" / name
            target = unit_dir / name
            created_files.append(target)
            _atomic_file(target, source.read_bytes(), 0o644)

        created_files.append(control_current)
        os.symlink(f"releases/{expected_source_commit}", control_current)

        systemctl(["daemon-reload"])
        for unit in UNIT_NAMES:
            attempted_units.append(unit)
            systemctl(["enable", "--now", unit])

        for unit in UNIT_NAMES:
            if not active_probe(unit):
                raise ControlPlaneBootstrapError(
                    f"operation-control unit did not become active: {unit}"
                )

        if _readlink_exact(production_current.absolute()) != production_before:
            raise ControlPlaneBootstrapError(
                "production current selector changed during control-plane bootstrap"
            )
        if _readlink_exact(control_current) != f"releases/{expected_source_commit}":
            raise ControlPlaneBootstrapError("control-current selector verification failed")
        _regular_exact(credential, mode=0o600, raw=credential_raw)
        for name in UNIT_NAMES:
            source = release / "deploy" / "zero-based-vps" / name
            _regular_exact(unit_dir / name, mode=0o644, raw=source.read_bytes())

        receipt = {
            "schema": "keelaryn.operation-control-bootstrap-receipt.v1",
            "source_commit": expected_source_commit,
            "payload_sha256": expected_payload_sha256,
            "repository": repository,
            "issue": issue,
            "actors": actors,
            "production_current_unchanged": True,
            "control_current_exact": True,
            "transport_active": True,
            "agent_active": True,
        }
        receipt_path = bootstrap_root / "bootstrap-receipt.json"
        created_files.append(receipt_path)
        _atomic_file(receipt_path, _canonical_json(receipt), 0o600)
        return receipt
    except BaseException as original:
        rollback_errors: list[str] = []

        for unit in reversed(attempted_units):
            try:
                systemctl(["disable", "--now", unit])
            except BaseException:
                rollback_errors.append(f"failed to disable attempted unit {unit}")

        for unit in UNIT_NAMES:
            try:
                if active_probe(unit):
                    rollback_errors.append(f"unit still active after rollback: {unit}")
            except BaseException:
                rollback_errors.append(
                    f"cannot verify unit inactive after rollback: {unit}"
                )

        for path in reversed(created_files):
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
            except OSError:
                rollback_errors.append(f"failed to remove created path {path}")

        try:
            systemctl(["daemon-reload"])
        except BaseException:
            rollback_errors.append("daemon-reload failed during rollback")

        for path in reversed(created_dirs):
            try:
                path.rmdir()
            except OSError:
                rollback_errors.append(f"failed to remove created directory {path}")

        try:
            if _readlink_exact(production_current.absolute()) != production_before:
                rollback_errors.append("production current changed unexpectedly")
        except BaseException:
            rollback_errors.append("cannot verify production current after rollback")

        if control_current.exists() or control_current.is_symlink():
            rollback_errors.append("control-current still exists after rollback")

        if rollback_errors:
            raise ControlPlaneBootstrapError(
                "bootstrap rollback incomplete: " + "; ".join(rollback_errors)
            ) from original
        raise
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-control-bootstrap")
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-payload-sha256", required=True)
    parser.add_argument("--production-current", type=Path, default=Path("/opt/keelaryn/current"))
    parser.add_argument("--control-current", type=Path, default=Path("/opt/keelaryn/control-current"))
    parser.add_argument("--unit-dir", type=Path, default=Path("/etc/systemd/system"))
    parser.add_argument("--config-dir", type=Path, default=Path("/etc/keelaryn"))
    parser.add_argument(
        "--bootstrap-root",
        type=Path,
        default=Path("/var/lib/keelaryn/operation-bootstrap"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")

    apply_parser = sub.add_parser("install")
    apply_parser.add_argument("--repository", required=True)
    apply_parser.add_argument("--issue", required=True, type=int)
    apply_parser.add_argument("--actors", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check":
            result = preflight(
                release=args.release,
                expected_source_commit=args.expected_source_commit,
                expected_payload_sha256=args.expected_payload_sha256,
                production_current=args.production_current,
                control_current=args.control_current,
                unit_dir=args.unit_dir,
                config_dir=args.config_dir,
                bootstrap_root=args.bootstrap_root,
            )
        else:
            token = getpass.getpass("GitHub operations token: ")
            result = install(
                release=args.release,
                expected_source_commit=args.expected_source_commit,
                expected_payload_sha256=args.expected_payload_sha256,
                repository=args.repository,
                issue=args.issue,
                actors=args.actors,
                token=token,
                production_current=args.production_current,
                control_current=args.control_current,
                unit_dir=args.unit_dir,
                config_dir=args.config_dir,
                bootstrap_root=args.bootstrap_root,
            )
    except (ControlPlaneBootstrapError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
