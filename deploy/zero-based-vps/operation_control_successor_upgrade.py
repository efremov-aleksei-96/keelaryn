from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE = REPO_ROOT / "core"
DEPLOY = REPO_ROOT / "deploy" / "zero-based-vps"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))

from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider  # noqa: E402
from keelaryn_core.drive_rest import GoogleDriveBackend  # noqa: E402
from keelaryn_core.migration_common import MIGRATION_SOURCE_NAME, small_file  # noqa: E402
from keelaryn_core.migration_drive_source import verify_migration_source_against_drive  # noqa: E402
from keelaryn_core.migration_freeze import verify_migration_candidate_freeze_identity  # noqa: E402
from keelaryn_core.migration_pack import verify_migration_pack  # noqa: E402
from keelaryn_core.migration_production_qualification import (  # noqa: E402
    TARGET_AUTHORITY_SCHEMA,
    TARGET_EVIDENCE_SCHEMA,
)
from keelaryn_core.protocol import (  # noqa: E402
    ProtocolError,
    canonical_json_bytes,
    strict_json_bytes,
)
from keelaryn_core.operation_hub_pre_apply_activation import (  # noqa: E402
    ACTIVATION_NAME,
)
from keelaryn_core.operation_hub_pre_apply_profile import (  # noqa: E402
    AUTHORIZATION,
    OPERATION,
    PROFILE_NAME,
    PROFILE_SCHEMA,
    REQUEST_PROFILE,
    parse_hub_pre_apply_profile,
)
from materialize_payload import (  # noqa: E402
    PayloadMaterializeError,
    materialize_payload,
    verify_release_directory,
)


RESULT_SCHEMA = "keelaryn.operation-control-successor-upgrade.v1"
PROFILE_STAGING_NAME = "operation-control-hub-pre-apply-profile.v1.json"
LEGACY_SOURCE_PATH = ("My Laptop", "0__Core", "keelaryn", "hub")
REPOSITORY = "https://github.com/efremov-aleksei-96/keelaryn.git"
WRITER_UNIT = "keelaryn-drive.service"
PERSISTENT_CONTROL_UNITS = (
    "keelaryn-operation-transport.service",
    "keelaryn-operation-agent.service",
)
SUCCESSOR_WORKER_UNIT = "keelaryn-hub-preapply.service"

_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE = re.compile(r"^migration-r[0-9]{4}-[0-9]{8}-[0-9]{2}$")


class SuccessorUpgradeError(RuntimeError):
    pass


@dataclass(frozen=True)
class SuccessorSpec:
    old_source_commit: str
    old_payload_sha256: str
    new_source_commit: str
    new_source_tree: str
    new_payload_sha256: str
    new_payload_size: int
    new_payload_file_count: int
    migration_candidate_id: str
    migration_source_identity_sha256: str


@dataclass(frozen=True)
class UpgradeLayout:
    install_root: Path = Path("/opt/keelaryn")
    selector: Path = Path("/etc/keelaryn/hub.env")
    deployment_state_root: Path = Path("/var/lib/keelaryn/deployment")
    mutation_gate_root: Path = Path("/var/lib/keelaryn/mutation-gate")
    migration_root: Path = Path("/var/lib/keelaryn/migration")
    unit_dir: Path = Path("/etc/systemd/system")
    credential_path: Path = Path(
        "/etc/keelaryn/operation-control/github-operations.env"
    )
    operation_control_root: Path = Path("/var/lib/keelaryn/operation-control")
    operation_root: Path = Path("/var/lib/keelaryn/operations")
    transport_root: Path = Path("/var/lib/keelaryn-operation-transport")
    update_root: Path = Path("/var/lib/keelaryn/operation-control-updates")


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


def _validate_spec(spec: SuccessorSpec) -> None:
    for value, label in (
        (spec.old_source_commit, "old source commit"),
        (spec.new_source_commit, "new source commit"),
        (spec.new_source_tree, "new source tree"),
    ):
        if _OID.fullmatch(value) is None:
            raise SuccessorUpgradeError(f"{label} is invalid")
    for value, label in (
        (spec.old_payload_sha256, "old payload SHA-256"),
        (spec.new_payload_sha256, "new payload SHA-256"),
        (
            spec.migration_source_identity_sha256,
            "migration source identity SHA-256",
        ),
    ):
        if _SHA256.fullmatch(value) is None:
            raise SuccessorUpgradeError(f"{label} is invalid")
    if spec.old_source_commit == spec.new_source_commit:
        raise SuccessorUpgradeError("successor source must differ from predecessor")
    if not isinstance(spec.new_payload_size, int) or spec.new_payload_size <= 0:
        raise SuccessorUpgradeError("new payload size is invalid")
    if (
        not isinstance(spec.new_payload_file_count, int)
        or spec.new_payload_file_count <= 0
    ):
        raise SuccessorUpgradeError("new payload file count is invalid")
    if _CANDIDATE.fullmatch(spec.migration_candidate_id) is None:
        raise SuccessorUpgradeError("migration candidate ID is invalid")


def _require_root() -> None:
    if os.name == "posix" and os.geteuid() != 0:
        raise SuccessorUpgradeError("successor upgrade requires root")


def _private_file(path: Path, label: str, *, mode: int = 0o600) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise SuccessorUpgradeError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise SuccessorUpgradeError(f"{label} must be one regular file")
    if os.name == "posix" and (
        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode
    ):
        raise SuccessorUpgradeError(
            f"{label} must be current-user owned mode {mode:04o}"
        )
    return path


def _private_dir(path: Path, label: str, *, mode: int = 0o700) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise SuccessorUpgradeError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise SuccessorUpgradeError(f"{label} must be one real directory")
    if os.name == "posix" and (
        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode
    ):
        raise SuccessorUpgradeError(
            f"{label} must be current-user owned mode {mode:04o}"
        )
    return path


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_private_new(path: Path, raw: bytes, label: str) -> Path:
    parent = _private_dir(path.parent, f"{label} parent")
    output = parent / path.name
    if output.exists() or output.is_symlink():
        raise SuccessorUpgradeError(f"{label} already exists")

    staging = parent / f".{output.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(staging, flags, 0o600)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)

        _private_file(staging, f"{label} staging file")
        if output.exists() or output.is_symlink():
            raise SuccessorUpgradeError(f"{label} appeared before publication")

        if os.name == "posix":
            os.link(staging, output, follow_symlinks=False)
            _fsync_dir(parent)
            staging.unlink()
        else:
            staging.rename(output)
        _fsync_dir(parent)
        return _private_file(output, label)
    except FileExistsError as exc:
        raise SuccessorUpgradeError(
            f"{label} appeared before publication"
        ) from exc
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


def _strict_canonical_json(
    raw: bytes,
    *,
    label: str,
    keys: set[str],
    schema: str,
) -> dict[str, Any]:
    try:
        value = strict_json_bytes(raw, label=label)
    except ProtocolError as exc:
        raise SuccessorUpgradeError(str(exc)) from exc
    if not isinstance(value, dict) or set(value) != keys:
        raise SuccessorUpgradeError(f"{label}: keys mismatch")
    if value.get("schema") != schema:
        raise SuccessorUpgradeError(f"{label}: schema mismatch")
    if raw != canonical_json_bytes(value):
        raise SuccessorUpgradeError(f"{label}: noncanonical JSON")
    return dict(value)


_TARGET_AUTHORITY_KEYS = {
    "schema",
    "candidate_id",
    "pack_sha256",
    "staging_root_id",
    "target_id",
    "target_name",
}

_TARGET_EVIDENCE_KEYS = {
    "schema",
    "candidate_id",
    "pack_sha256",
    "source_commit",
    "source_tree",
    "source_manifest_sha256",
    "mapping_manifest_sha256",
    "frozen_canonical_inventory_sha256",
    "frozen_project_state_inventory_sha256",
    "frozen_preservation_inventory_sha256",
    "frozen_root_index_sha256",
    "target_identity_sha256",
    "staging_identity_sha256",
    "canonical_epoch",
    "canonical_file_count",
    "canonical_total_bytes",
    "canonical_inventory_sha256",
    "preserved_file_count",
    "preserved_total_bytes",
    "preservation_inventory_sha256",
    "project_count",
    "reconciliation_state_sha256",
    "router_outcome",
    "root_index_sha256",
    "reader_epoch",
    "no_op_phase",
    "restart_state",
    "outcome",
    "cutover_authorized",
}


def _strict_target_authority(raw: bytes) -> dict[str, Any]:
    value = _strict_canonical_json(
        raw,
        label="MIGRATION_PRODUCTION_TARGET_AUTHORITY",
        keys=_TARGET_AUTHORITY_KEYS,
        schema=TARGET_AUTHORITY_SCHEMA,
    )
    for key in (
        "candidate_id",
        "pack_sha256",
        "staging_root_id",
        "target_id",
        "target_name",
    ):
        if not isinstance(value[key], str) or not value[key]:
            raise SuccessorUpgradeError(
                f"MIGRATION_PRODUCTION_TARGET_AUTHORITY.{key}: invalid"
            )
    return value


def _strict_target_qualification(raw: bytes) -> dict[str, Any]:
    value = _strict_canonical_json(
        raw,
        label="MIGRATION_PRODUCTION_TARGET_QUALIFICATION",
        keys=_TARGET_EVIDENCE_KEYS,
        schema=TARGET_EVIDENCE_SCHEMA,
    )
    if value.get("cutover_authorized") is not False:
        raise SuccessorUpgradeError(
            "MIGRATION_PRODUCTION_TARGET_QUALIFICATION.cutover_authorized: invalid"
        )
    return value


def _read_json_private(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = _private_file(path, label).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuccessorUpgradeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SuccessorUpgradeError(f"{label} must be one JSON object")
    return raw, value


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=None if cwd is None else str(cwd),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SuccessorUpgradeError(
            f"command outcome is uncertain: {args[0]}"
        ) from exc
    if result.returncode != 0:
        raise SuccessorUpgradeError(f"command failed: {args[0]}")
    return result


def _json_command(args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    result = _run(args, timeout=timeout)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SuccessorUpgradeError(
            f"command returned invalid JSON: {args[0]}"
        ) from exc
    if not isinstance(value, dict):
        raise SuccessorUpgradeError(
            f"command returned non-object JSON: {args[0]}"
        )
    return value


def _checkout_source(work: Path, spec: SuccessorSpec) -> Path:
    repo = work / "source"
    _run(["git", "init", "-q", str(repo)])
    _run(["git", "-C", str(repo), "remote", "add", "origin", REPOSITORY])
    _run(
        [
            "git",
            "-C",
            str(repo),
            "fetch",
            "-q",
            "--depth",
            "1",
            "origin",
            spec.new_source_commit,
        ],
        timeout=300,
    )
    _run(["git", "-C", str(repo), "checkout", "-q", "--detach", "FETCH_HEAD"])
    head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
    tree = _run(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"]
    ).stdout.strip()
    dirty = _run(["git", "-C", str(repo), "status", "--porcelain"]).stdout
    if head != spec.new_source_commit or tree != spec.new_source_tree or dirty:
        raise SuccessorUpgradeError("fetched successor source identity is not exact")
    return repo


def _build_payload_twice(
    repo: Path,
    work: Path,
    spec: SuccessorSpec,
) -> Path:
    builder = repo / "deploy" / "zero-based-vps" / "build_payload.py"
    first = work / "first.tar.gz"
    second = work / "second.tar.gz"
    metas = []
    for output in (first, second):
        metas.append(
            _json_command(
                [
                    sys.executable,
                    "-B",
                    str(builder),
                    "--repo-root",
                    str(repo),
                    "--source-commit",
                    spec.new_source_commit,
                    "--output",
                    str(output),
                ],
                timeout=600,
            )
        )
    first_raw = first.read_bytes()
    second_raw = second.read_bytes()
    if first_raw != second_raw:
        raise SuccessorUpgradeError("successor payload rebuild is not deterministic")
    observed = {
        "source_commit": metas[0].get("source_commit"),
        "payload_sha256": _sha(first_raw),
        "payload_size": len(first_raw),
        "file_count": metas[0].get("file_count"),
    }
    expected = {
        "source_commit": spec.new_source_commit,
        "payload_sha256": spec.new_payload_sha256,
        "payload_size": spec.new_payload_size,
        "file_count": spec.new_payload_file_count,
    }
    if observed != expected:
        raise SuccessorUpgradeError("successor payload identity mismatch")
    for key in expected:
        if metas[1].get(key) != metas[0].get(key):
            raise SuccessorUpgradeError(
                "second successor payload metadata differs"
            )
    return first


def _systemd_unit_state(unit: str) -> tuple[str, int]:
    result = _run(
        [
            "systemctl",
            "show",
            unit,
            "--property=ActiveState",
            "--property=MainPID",
        ]
    )
    values: dict[str, str] = {}
    for raw in result.stdout.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key] = value
    if set(values) != {"ActiveState", "MainPID"}:
        raise SuccessorUpgradeError(
            f"systemd state response is incomplete for {unit}"
        )
    try:
        main_pid = int(values["MainPID"])
    except ValueError as exc:
        raise SuccessorUpgradeError(
            f"systemd MainPID is invalid for {unit}"
        ) from exc
    if main_pid < 0:
        raise SuccessorUpgradeError(
            f"systemd MainPID is invalid for {unit}"
        )
    return values["ActiveState"], main_pid


def _exact_installed_unit(
    path: Path,
    expected: bytes,
    label: str,
) -> None:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise SuccessorUpgradeError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise SuccessorUpgradeError(f"{label} must be one regular file")
    if os.name == "posix" and (
        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o644
    ):
        raise SuccessorUpgradeError(
            f"{label} must be current-user owned mode 0644"
        )
    if path.read_bytes() != expected:
        raise SuccessorUpgradeError(f"{label} bytes mismatch")


def _preflight_upgrade_boundary(
    spec: SuccessorSpec,
    layout: UpgradeLayout,
    *,
    systemd_probe: Callable[[str], tuple[str, int]] = _systemd_unit_state,
) -> None:
    _validate_spec(spec)

    writer_state, writer_pid = systemd_probe(WRITER_UNIT)
    if writer_state != "inactive" or writer_pid != 0:
        raise SuccessorUpgradeError(
            "production writer must be exact inactive/MainPID=0"
        )

    releases = layout.install_root / "releases"
    predecessor = releases / spec.old_source_commit
    try:
        verify_release_directory(
            predecessor,
            expected_source_commit=spec.old_source_commit,
            expected_payload_sha256=spec.old_payload_sha256,
        )
    except PayloadMaterializeError as exc:
        raise SuccessorUpgradeError(
            "installed predecessor identity mismatch"
        ) from exc

    control_current = layout.install_root / "control-current"
    if not control_current.is_symlink():
        raise SuccessorUpgradeError(
            "control-current must be one canonical predecessor symlink"
        )
    if os.name == "posix" and control_current.lstat().st_uid != os.geteuid():
        raise SuccessorUpgradeError("control-current owner mismatch")
    if os.readlink(control_current) != f"releases/{spec.old_source_commit}":
        raise SuccessorUpgradeError(
            "control-current does not select exact predecessor"
        )

    deploy = predecessor / "deploy" / "zero-based-vps"
    for name in PERSISTENT_CONTROL_UNITS:
        _exact_installed_unit(
            layout.unit_dir / name,
            (deploy / name).read_bytes(),
            f"installed predecessor unit {name}",
        )

    worker = layout.unit_dir / SUCCESSOR_WORKER_UNIT
    if worker.exists() or worker.is_symlink():
        raise SuccessorUpgradeError(
            "successor Hub worker must be absent before upgrade"
        )

    for path, label in (
        (layout.operation_control_root / PROFILE_NAME, "Hub pre-apply profile"),
        (
            layout.operation_control_root / ACTIVATION_NAME,
            "Hub pre-apply activation",
        ),
    ):
        if path.exists() or path.is_symlink():
            raise SuccessorUpgradeError(
                f"{label} must be absent before successor upgrade"
            )


def materialize_successor(
    spec: SuccessorSpec,
    layout: UpgradeLayout,
) -> dict[str, Any]:
    _validate_spec(spec)
    releases = layout.install_root / "releases"
    predecessor = releases / spec.old_source_commit
    try:
        verify_release_directory(
            predecessor,
            expected_source_commit=spec.old_source_commit,
            expected_payload_sha256=spec.old_payload_sha256,
        )
    except PayloadMaterializeError as exc:
        raise SuccessorUpgradeError("installed predecessor identity mismatch") from exc

    successor = releases / spec.new_source_commit
    if successor.exists() or successor.is_symlink():
        try:
            return verify_release_directory(
                successor,
                expected_source_commit=spec.new_source_commit,
                expected_payload_sha256=spec.new_payload_sha256,
            )
        except PayloadMaterializeError as exc:
            raise SuccessorUpgradeError(
                "existing successor release is not exact"
            ) from exc

    with tempfile.TemporaryDirectory(prefix="keelaryn-control-successor-") as td:
        work = Path(td)
        repo = _checkout_source(work, spec)
        payload = _build_payload_twice(repo, work, spec)
        try:
            materialize_payload(
                payload,
                releases,
                expected_source_commit=spec.new_source_commit,
                expected_payload_sha256=spec.new_payload_sha256,
            )
        except PayloadMaterializeError as exc:
            raise SuccessorUpgradeError(
                "successor materialization failed"
            ) from exc

    try:
        return verify_release_directory(
            successor,
            expected_source_commit=spec.new_source_commit,
            expected_payload_sha256=spec.new_payload_sha256,
        )
    except PayloadMaterializeError as exc:
        raise SuccessorUpgradeError(
            "materialized successor failed exact verification"
        ) from exc


def _credential_environment(path: Path) -> dict[str, str]:
    _private_file(path, "migration qualification credential")
    required = {
        "KEELARYN_GOOGLE_CLIENT_ID",
        "KEELARYN_GOOGLE_CLIENT_SECRET",
        "KEELARYN_GOOGLE_REFRESH_TOKEN",
    }
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SuccessorUpgradeError(
            "migration qualification credential is unreadable"
        ) from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key not in required:
            continue
        if key in result:
            raise SuccessorUpgradeError(
                "migration qualification credential has duplicate key"
            )
        if (
            not value
            or value != value.strip()
            or "\x00" in value
            or "\r" in value
            or "\n" in value
        ):
            raise SuccessorUpgradeError(
                "migration qualification credential value is invalid"
            )
        result[key] = value
    if set(result) != required:
        raise SuccessorUpgradeError(
            "migration qualification credential keys mismatch"
        )
    return result


def resolve_legacy_source_root(
    drive,
    *,
    path_segments: Sequence[str],
    expected_identity_sha256: str,
) -> str:
    if not path_segments:
        raise SuccessorUpgradeError("legacy source path is empty")
    parent = "root"
    current = None
    for segment in path_segments:
        children = drive.list_children(parent)
        folded = [
            item
            for item in children
            if item.name.casefold() == segment.casefold()
        ]
        if len(folded) != 1 or folded[0].name != segment:
            raise SuccessorUpgradeError(
                "legacy source path is missing, duplicated, or case-conflicting"
            )
        current = folded[0]
        if current.trashed or not current.is_folder:
            raise SuccessorUpgradeError(
                "legacy source path segment is not one live folder"
            )
        parent = current.file_id
    assert current is not None
    if _sha(current.file_id.encode("utf-8")) != expected_identity_sha256:
        raise SuccessorUpgradeError("legacy source root identity mismatch")
    return current.file_id


def _load_current_hub_authority(
    layout: UpgradeLayout,
) -> tuple[bytes, dict[str, Any], str]:
    current = layout.install_root / "current"
    if not current.is_symlink():
        raise SuccessorUpgradeError("production current is not a symlink")
    target = os.readlink(current)
    match = re.fullmatch(r"releases/([0-9a-f]{40})", target)
    if match is None:
        raise SuccessorUpgradeError("production current target is noncanonical")
    framework_source = match.group(1)
    release = layout.install_root / target
    try:
        verify_release_directory(
            release,
            expected_source_commit=framework_source,
        )
    except PayloadMaterializeError as exc:
        raise SuccessorUpgradeError(
            "production current release identity mismatch"
        ) from exc

    tool = release / "deploy" / "zero-based-vps" / "hub_cutover.py"

    def observe_status() -> dict[str, Any]:
        value = _json_command(
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
                framework_source,
                "status",
            ]
        )
        if value.get("status") != "PREPARED":
            raise SuccessorUpgradeError(
                "production Hub cutover is not exact PREPARED"
            )
        return value

    active_path = layout.deployment_state_root / "ACTIVE_TRANSACTION.json"
    status_first = observe_status()
    active_raw, active = _read_json_private(
        active_path,
        "active Hub cutover transaction",
    )
    status_second = observe_status()
    active_raw_second, active_second = _read_json_private(
        active_path,
        "active Hub cutover transaction",
    )

    if (
        status_first != status_second
        or active_raw != active_raw_second
        or active != active_second
        or not current.is_symlink()
        or os.readlink(current) != target
    ):
        raise SuccessorUpgradeError(
            "production PREPARED authority changed during stabilization"
        )

    required = {
        "schema",
        "transaction_id",
        "tool",
        "finalizers",
        "old_hub_root_id",
        "new_hub_root_id",
    }
    if set(active) != required:
        raise SuccessorUpgradeError(
            "active Hub cutover transaction keys mismatch"
        )
    if active.get("transaction_id") != status_first.get("transaction_id"):
        raise SuccessorUpgradeError(
            "active Hub cutover transaction/status mismatch"
        )
    if (
        not isinstance(active.get("tool"), dict)
        or active["tool"].get("source_commit") != framework_source
    ):
        raise SuccessorUpgradeError(
            "active Hub cutover framework identity mismatch"
        )
    return active_raw, active, framework_source


def build_hub_pre_apply_profile(
    spec: SuccessorSpec,
    layout: UpgradeLayout,
    *,
    drive_factory: Callable[[Mapping[str, str]], Any] | None = None,
) -> tuple[bytes, Path]:
    _validate_spec(spec)
    active_raw, active, framework_source = _load_current_hub_authority(layout)

    candidate_root = _private_dir(
        layout.migration_root / spec.migration_candidate_id,
        "migration candidate root",
    )
    pack_root = candidate_root / "qualification-input" / "pack"
    pack = verify_migration_pack(pack_root)
    freeze = candidate_root / "migration-candidate-freeze.v1.json"
    authority = candidate_root / "production-target-authority.v1.json"
    qualification = (
        candidate_root / "production-target-qualification.v1.json"
    )
    credential = candidate_root / "qualification-production-drive.env"

    freeze_raw, freeze_value = _read_json_private(freeze, "freeze receipt")
    authority_raw = _private_file(
        authority,
        "target authority",
    ).read_bytes()
    qualification_raw = _private_file(
        qualification,
        "qualification evidence",
    ).read_bytes()
    authority_value = _strict_target_authority(authority_raw)
    qualification_value = _strict_target_qualification(qualification_raw)
    credential_raw = _private_file(
        credential,
        "migration qualification credential",
    ).read_bytes()

    candidate_source_commit = freeze_value.get("source_commit")
    candidate_source_tree = freeze_value.get("source_tree")
    if not isinstance(candidate_source_commit, str) or not isinstance(
        candidate_source_tree, str
    ):
        raise SuccessorUpgradeError("freeze source identity is invalid")
    try:
        verify_migration_candidate_freeze_identity(
            pack.root,
            freeze,
            candidate_source_commit,
            candidate_source_tree,
        )
    except Exception as exc:
        raise SuccessorUpgradeError(
            "migration freeze identity verification failed"
        ) from exc
    if (
        freeze_value.get("pack_sha256") != pack.pack_sha256
        or authority_value.get("candidate_id") != spec.migration_candidate_id
        or authority_value.get("pack_sha256") != pack.pack_sha256
        or qualification_value.get("candidate_id")
        != spec.migration_candidate_id
        or qualification_value.get("pack_sha256") != pack.pack_sha256
        or qualification_value.get("source_commit") != candidate_source_commit
        or qualification_value.get("source_tree") != candidate_source_tree
        or qualification_value.get("outcome") != "TARGET_QUALIFICATION_PASS"
        or qualification_value.get("cutover_authorized") is not False
    ):
        raise SuccessorUpgradeError(
            "migration frozen/target/qualification authorities disagree"
        )

    target_id = authority_value.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        raise SuccessorUpgradeError("target authority target ID is invalid")
    new_identity = _sha(target_id.encode("utf-8"))
    active_new = active.get("new_hub_root_id")
    if (
        not isinstance(active_new, str)
        or _sha(active_new.encode("utf-8")) != new_identity
        or qualification_value.get("target_identity_sha256") != new_identity
    ):
        raise SuccessorUpgradeError(
            "PREPARED NEW selector does not bind qualified target"
        )

    oauth_env = _credential_environment(credential)
    if drive_factory is None:
        def drive_factory(values: Mapping[str, str]):
            provider = GoogleOAuthRefreshTokenProvider.from_environment(values)
            return GoogleDriveBackend(provider)

    drive = drive_factory(oauth_env)
    source_root_id = resolve_legacy_source_root(
        drive,
        path_segments=LEGACY_SOURCE_PATH,
        expected_identity_sha256=spec.migration_source_identity_sha256,
    )
    source_manifest = pack.root / "authority" / MIGRATION_SOURCE_NAME
    try:
        verify_migration_source_against_drive(
            drive,
            source_root_id,
            source_manifest,
            phase="SUCCESSOR_PROFILE_SOURCE_VERIFY",
        )
    except Exception as exc:
        raise SuccessorUpgradeError(
            "fresh legacy Drive source verification failed"
        ) from exc

    profile_value = {
        "schema": PROFILE_SCHEMA,
        "operation": OPERATION,
        "request_profile": REQUEST_PROFILE,
        "authorization": AUTHORIZATION,
        "control_source_commit": spec.new_source_commit,
        "transaction_id": active["transaction_id"],
        "active_transaction_sha256": _sha(active_raw),
        "framework_source_commit": framework_source,
        "candidate_id": spec.migration_candidate_id,
        "candidate_source_commit": candidate_source_commit,
        "candidate_source_tree": candidate_source_tree,
        "pack_sha256": pack.pack_sha256,
        "freeze_receipt_sha256": _sha(freeze_raw),
        "target_authority_sha256": _sha(authority_raw),
        "qualification_evidence_sha256": _sha(qualification_raw),
        "credential_sha256": _sha(credential_raw),
        "migration_source_root_id": source_root_id,
        "migration_source_identity_sha256": (
            spec.migration_source_identity_sha256
        ),
        "new_selector_identity_sha256": new_identity,
    }
    profile_raw = _canonical(profile_value)
    try:
        parse_hub_pre_apply_profile(profile_raw)
    except Exception as exc:
        raise SuccessorUpgradeError(
            "synthesized Hub pre-apply profile is invalid"
        ) from exc

    staging = candidate_root / PROFILE_STAGING_NAME
    if staging.exists() or staging.is_symlink():
        existing = _private_file(
            staging,
            "staged Hub pre-apply profile",
        ).read_bytes()
        if existing != profile_raw:
            raise SuccessorUpgradeError(
                "staged Hub pre-apply profile conflicts with current authority"
            )
    else:
        _atomic_private_new(
            staging,
            profile_raw,
            "staged Hub pre-apply profile",
        )
    return profile_raw, staging


def _load_successor_updater(release: Path):
    path = release / "deploy" / "zero-based-vps" / "operation_control_plane_update.py"
    if path.is_symlink() or not path.is_file():
        raise SuccessorUpgradeError("successor updater is missing")
    name = "keelaryn_operation_control_successor_updater_exact"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SuccessorUpgradeError("cannot load exact successor updater")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def upgrade_successor(
    spec: SuccessorSpec,
    layout: UpgradeLayout,
    *,
    drive_factory: Callable[[Mapping[str, str]], Any] | None = None,
    systemd_probe: Callable[[str], tuple[str, int]] | None = None,
) -> dict[str, Any]:
    _require_root()
    _validate_spec(spec)
    _preflight_upgrade_boundary(
        spec,
        layout,
        systemd_probe=(
            _systemd_unit_state
            if systemd_probe is None
            else systemd_probe
        ),
    )
    materialize_successor(spec, layout)
    _, profile_path = build_hub_pre_apply_profile(
        spec,
        layout,
        drive_factory=drive_factory,
    )

    release = layout.install_root / "releases" / spec.new_source_commit
    updater = _load_successor_updater(release)
    try:
        completed = updater.update_control_plane(
            install_root=layout.install_root,
            unit_dir=layout.unit_dir,
            credential_path=layout.credential_path,
            operation_control_root=layout.operation_control_root,
            operation_root=layout.operation_root,
            transport_root=layout.transport_root,
            update_root=layout.update_root,
            profile_source=profile_path,
            expected_old_source_commit=spec.old_source_commit,
            expected_old_payload_sha256=spec.old_payload_sha256,
            expected_new_source_commit=spec.new_source_commit,
            expected_new_payload_sha256=spec.new_payload_sha256,
        )
    except Exception as exc:
        raise SuccessorUpgradeError(
            "transactional successor control update failed"
        ) from exc

    if completed.get("schema") != "keelaryn.operation-control-update-completed.v1":
        raise SuccessorUpgradeError(
            "successor updater returned non-COMPLETED authority"
        )
    return {
        "schema": RESULT_SCHEMA,
        "control_source_commit": spec.new_source_commit,
        "control_payload_sha256": spec.new_payload_sha256,
        "migration_candidate_id": spec.migration_candidate_id,
        "control_update": "COMPLETED",
        "hub_pre_apply_activation": "READY",
        "production_current_mutated": False,
        "hub_selector_mutated": False,
        "drive_mutations_performed": False,
    }


__all__ = [
    "LEGACY_SOURCE_PATH",
    "PROFILE_STAGING_NAME",
    "RESULT_SCHEMA",
    "SuccessorSpec",
    "SuccessorUpgradeError",
    "UpgradeLayout",
    "build_hub_pre_apply_profile",
    "materialize_successor",
    "resolve_legacy_source_root",
    "_preflight_upgrade_boundary",
    "upgrade_successor",
]
