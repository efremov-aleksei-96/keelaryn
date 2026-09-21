from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


GATE_REVISION = "operation-control-gate-r0012"
CANDIDATE = "operation-control-r0006-20260921-01"
REPOSITORY = "https://github.com/efremov-aleksei-96/keelaryn.git"

SOURCE_COMMIT = "b371a9b9f28fe668cc8073019a3d5f352f9d9bf3"
SOURCE_TREE = "1e3a80f76283fb0800bb6e9d09202f6ab6755c5b"
PAYLOAD_SHA256 = "0d2201e94a75f8622b40118d93b9eee9064ebe6650d3140e73997aed92c8c3cd"
PAYLOAD_SIZE = 393732
PAYLOAD_FILE_COUNT = 199

PREDECESSOR_CANDIDATE = "operation-control-r0005-20260921-01"
PREDECESSOR_SOURCE_COMMIT = "08f2e211f53764590f6ff0f05f86b2de62c14418"
PREDECESSOR_PAYLOAD_SHA256 = "6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7"

PRODUCTION_SOURCE = "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
HUB_TRANSACTION_ID = "61a2bfb65c9a47d088a76eee0df89d14"
ACTIVE_TRANSACTION_SHA256 = "1d243586556019e132c454ebc8ccc252b755e5b43421434a6ff1eaf1c166ea34"
OLD_SELECTOR_IDENTITY_SHA256 = "15370553b6732a11d4e0a9a8a02066c1c089d8b0f443001cc39fe39b201c8444"
NEW_SELECTOR_IDENTITY_SHA256 = "dffc1b46b44d951b498ee7d781f6b992f0dc6356cfb38eebadbee792a847db39"

MIGRATION_CANDIDATE = "migration-r0072-20260919-01"
MIGRATION_PACK_SHA256 = "82eda038bb2c424d44137e3bfa8174778ab8a24d49bcca253430cc1aea2bc21b"
MIGRATION_FREEZE_SHA256 = "d469b6b5f20196445111da5b354284338ec4b3c9c4245d395e95b97115f1ff39"
MIGRATION_TARGET_AUTHORITY_SHA256 = "5ef842af448bbfba606abd4565c13f2c9a059a480ad0ad81cf9d688abe5fab10"
MIGRATION_QUALIFICATION_SHA256 = "5fda3af50ab1e9f9fb2d53a93d163f97a2842383b1b0d6d2c635c49df0cc2346"
MIGRATION_SOURCE_MANIFEST_SHA256 = "540b48d5c8b5e94cb5671988f2ce300648d651d7c73f47a7130bdd47acd7013e"
MIGRATION_CREDENTIAL_SHA256 = "24f562a3eb5d4ea93a24162e8a65d182cc2ab4c4298f70da7866c446cc7018ed"
MIGRATION_SOURCE_IDENTITY_SHA256 = "40907275bba002f58120cef28d8bf2c0950f6d69057075dbb632154075b21eb9"

INSTALL_ROOT = Path("/opt/keelaryn")
CONTROL_CURRENT = INSTALL_ROOT / "control-current"
PRODUCTION_CURRENT = INSTALL_ROOT / "current"
SELECTOR = Path("/etc/keelaryn/hub.env")
STATE_ROOT = Path("/var/lib/keelaryn/deployment")
MUTATION_GATE_ROOT = Path("/var/lib/keelaryn/mutation-gate")
MIGRATION_ROOT = Path("/var/lib/keelaryn/migration")
UNIT_DIR = Path("/etc/systemd/system")
CREDENTIAL_PATH = Path("/etc/keelaryn/operation-control/github-operations.env")
OPERATION_CONTROL_ROOT = Path("/var/lib/keelaryn/operation-control")
OPERATION_ROOT = Path("/var/lib/keelaryn/operations")
TRANSPORT_ROOT = Path("/var/lib/keelaryn-operation-transport")
UPDATE_ROOT = Path("/var/lib/keelaryn/operation-control-updates")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class GateError(RuntimeError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        value = subprocess.run(
            args,
            cwd=None if cwd is None else str(cwd),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"command outcome is uncertain: {args[0]}") from exc
    if value.returncode != 0:
        raise GateError(f"command returned nonzero: {args[0]}")
    return value


def _json_command(args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    value = _run(args, timeout=timeout)
    try:
        result = json.loads(value.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(f"command returned invalid JSON: {args[0]}") from exc
    if not isinstance(result, dict):
        raise GateError(f"command returned non-object JSON: {args[0]}")
    return result


def _require_root() -> None:
    if os.name == "posix" and os.geteuid() != 0:
        raise GateError("r0006 production qualification/upgrade requires root")


def _readlink_exact(path: Path, expected: str, label: str) -> None:
    if not path.is_symlink():
        raise GateError(f"{label} is not one canonical symlink")
    if os.readlink(path) != expected:
        raise GateError(f"{label} target mismatch")


def _private_file(path: Path, label: str, mode: int = 0o600) -> bytes:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise GateError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise GateError(f"{label} must be one regular file")
    if os.name == "posix" and (
        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode
    ):
        raise GateError(f"{label} owner/mode mismatch")
    return path.read_bytes()


def _pack_file(path: Path, label: str) -> bytes:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise GateError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise GateError(f"{label} must be one regular file")
    if os.name == "posix":
        if info.st_uid != os.geteuid():
            raise GateError(f"{label} owner mismatch")
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise GateError(
                f"{label} must not be group/world writable"
            )
    return path.read_bytes()


def _systemd_show(unit: str) -> tuple[str, int]:
    value = _run(
        [
            "systemctl",
            "show",
            unit,
            "--property=ActiveState",
            "--property=MainPID",
        ],
        timeout=30,
    )
    parsed: dict[str, str] = {}
    for line in value.stdout.splitlines():
        if "=" in line:
            key, raw = line.split("=", 1)
            parsed[key] = raw
    if set(parsed) != {"ActiveState", "MainPID"}:
        raise GateError(f"systemd response incomplete: {unit}")
    try:
        pid = int(parsed["MainPID"])
    except ValueError as exc:
        raise GateError(f"systemd MainPID invalid: {unit}") from exc
    return parsed["ActiveState"], pid


def _checkout_frozen(work: Path) -> Path:
    source = work / "source"
    _run(["git", "init", "-q", str(source)])
    _run(["git", "-C", str(source), "remote", "add", "origin", REPOSITORY])
    _run(
        [
            "git",
            "-C",
            str(source),
            "fetch",
            "-q",
            "--depth",
            "1",
            "origin",
            SOURCE_COMMIT,
        ],
        timeout=300,
    )
    _run(["git", "-C", str(source), "checkout", "-q", "--detach", "FETCH_HEAD"])
    head = _run(["git", "-C", str(source), "rev-parse", "HEAD"]).stdout.strip()
    tree = _run(
        ["git", "-C", str(source), "rev-parse", "HEAD^{tree}"]
    ).stdout.strip()
    dirty = _run(["git", "-C", str(source), "status", "--porcelain"]).stdout
    if head != SOURCE_COMMIT or tree != SOURCE_TREE or dirty:
        raise GateError("frozen r0006 source identity mismatch")
    return source


def _rebuild_frozen(source: Path, work: Path) -> dict[str, Any]:
    builder = source / "deploy" / "zero-based-vps" / "build_payload.py"
    first = work / "first.tar.gz"
    second = work / "second.tar.gz"
    first_meta = _json_command(
        [
            sys.executable,
            "-B",
            str(builder),
            "--repo-root",
            str(source),
            "--source-commit",
            SOURCE_COMMIT,
            "--output",
            str(first),
        ],
        timeout=600,
    )
    second_meta = _json_command(
        [
            sys.executable,
            "-B",
            str(builder),
            "--repo-root",
            str(source),
            "--source-commit",
            SOURCE_COMMIT,
            "--output",
            str(second),
        ],
        timeout=600,
    )
    first_raw = first.read_bytes()
    if first_raw != second.read_bytes():
        raise GateError("frozen r0006 payload rebuild is not deterministic")
    observed = {
        "source_commit": first_meta.get("source_commit"),
        "payload_sha256": _sha(first_raw),
        "payload_size": len(first_raw),
        "file_count": first_meta.get("file_count"),
    }
    expected = {
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }
    if observed != expected:
        raise GateError(f"frozen r0006 payload identity mismatch: {observed}")
    for key in expected:
        if second_meta.get(key) != first_meta.get(key):
            raise GateError("second frozen payload metadata differs")
    return observed


def _load_engine(source: Path):
    path = source / "deploy" / "zero-based-vps" / "operation_control_successor_upgrade.py"
    deploy = str(path.parent)
    core = str(source / "core")
    for value in (core, deploy):
        if value not in sys.path:
            sys.path.insert(0, value)
    name = "keelaryn_operation_control_r0006_frozen_engine"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateError("cannot load exact frozen r0006 upgrade engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _successor_spec(module):
    return module.SuccessorSpec(
        old_source_commit=PREDECESSOR_SOURCE_COMMIT,
        old_payload_sha256=PREDECESSOR_PAYLOAD_SHA256,
        new_source_commit=SOURCE_COMMIT,
        new_source_tree=SOURCE_TREE,
        new_payload_sha256=PAYLOAD_SHA256,
        new_payload_size=PAYLOAD_SIZE,
        new_payload_file_count=PAYLOAD_FILE_COUNT,
        migration_candidate_id=MIGRATION_CANDIDATE,
        migration_source_identity_sha256=MIGRATION_SOURCE_IDENTITY_SHA256,
    )


def _layout(module):
    return module.UpgradeLayout(
        install_root=INSTALL_ROOT,
        selector=SELECTOR,
        deployment_state_root=STATE_ROOT,
        mutation_gate_root=MUTATION_GATE_ROOT,
        migration_root=MIGRATION_ROOT,
        unit_dir=UNIT_DIR,
        credential_path=CREDENTIAL_PATH,
        operation_control_root=OPERATION_CONTROL_ROOT,
        operation_root=OPERATION_ROOT,
        transport_root=TRANSPORT_ROOT,
        update_root=UPDATE_ROOT,
    )


def _production_anchor() -> dict[str, Any]:
    _readlink_exact(
        PRODUCTION_CURRENT,
        f"releases/{PRODUCTION_SOURCE}",
        "production current",
    )
    writer_state, writer_pid = _systemd_show("keelaryn-drive.service")
    if writer_state != "inactive" or writer_pid != 0:
        raise GateError("production writer is not exact inactive/MainPID=0")

    production = INSTALL_ROOT / "releases" / PRODUCTION_SOURCE
    tool = production / "deploy" / "zero-based-vps" / "hub_cutover.py"
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
    if (
        status.get("status") != "PREPARED"
        or status.get("transaction_id") != HUB_TRANSACTION_ID
    ):
        raise GateError("production Hub cutover PREPARED authority mismatch")

    active_raw = _private_file(
        STATE_ROOT / "ACTIVE_TRANSACTION.json",
        "ACTIVE_TRANSACTION",
    )
    if _sha(active_raw) != ACTIVE_TRANSACTION_SHA256:
        raise GateError("ACTIVE_TRANSACTION SHA-256 mismatch")
    try:
        active = json.loads(active_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("ACTIVE_TRANSACTION JSON invalid") from exc
    if not isinstance(active, dict):
        raise GateError("ACTIVE_TRANSACTION must be one JSON object")
    if active.get("transaction_id") != HUB_TRANSACTION_ID:
        raise GateError("ACTIVE_TRANSACTION transaction mismatch")

    old_id = active.get("old_hub_root_id")
    new_id = active.get("new_hub_root_id")
    if not isinstance(old_id, str) or not isinstance(new_id, str):
        raise GateError("ACTIVE_TRANSACTION selector identities invalid")
    if _sha(old_id.encode("utf-8")) != OLD_SELECTOR_IDENTITY_SHA256:
        raise GateError("OLD selector identity mismatch")
    if _sha(new_id.encode("utf-8")) != NEW_SELECTOR_IDENTITY_SHA256:
        raise GateError("NEW selector identity mismatch")
    return {
        "production_source": PRODUCTION_SOURCE,
        "writer": "INACTIVE_MAINPID_0",
        "hub_cutover": "PREPARED",
        "transaction_id": HUB_TRANSACTION_ID,
        "active_transaction_sha256": ACTIVE_TRANSACTION_SHA256,
        "old_selector_identity_sha256": OLD_SELECTOR_IDENTITY_SHA256,
        "new_selector_identity_sha256": NEW_SELECTOR_IDENTITY_SHA256,
    }


def _migration_anchor() -> dict[str, Any]:
    root = MIGRATION_ROOT / MIGRATION_CANDIDATE
    if root.is_symlink() or not root.is_dir():
        raise GateError("r0072 migration candidate root missing/not real")

    private_paths = {
        "freeze_receipt_sha256": (
            root / "migration-candidate-freeze.v1.json",
            MIGRATION_FREEZE_SHA256,
        ),
        "target_authority_sha256": (
            root / "production-target-authority.v1.json",
            MIGRATION_TARGET_AUTHORITY_SHA256,
        ),
        "qualification_evidence_sha256": (
            root / "production-target-qualification.v1.json",
            MIGRATION_QUALIFICATION_SHA256,
        ),
        "qualification_credential_sha256": (
            root / "qualification-production-drive.env",
            MIGRATION_CREDENTIAL_SHA256,
        ),
    }
    pack_paths = {
        "source_manifest_sha256": (
            root
            / "qualification-input"
            / "pack"
            / "authority"
            / "MIGRATION_SOURCE.json",
            MIGRATION_SOURCE_MANIFEST_SHA256,
        ),
    }
    observed: dict[str, str] = {
        "candidate": MIGRATION_CANDIDATE,
        "pack_sha256": MIGRATION_PACK_SHA256,
        "migration_source_identity_sha256": MIGRATION_SOURCE_IDENTITY_SHA256,
    }
    for key, (path, expected) in private_paths.items():
        raw = _private_file(path, key)
        digest = _sha(raw)
        if digest != expected:
            raise GateError(f"r0072 authority hash mismatch: {key}")
        observed[key] = digest

    for key, (path, expected) in pack_paths.items():
        raw = _pack_file(path, key)
        digest = _sha(raw)
        if digest != expected:
            raise GateError(f"r0072 pack input hash mismatch: {key}")
        observed[key] = digest

    pack_manifest = _pack_file(
        root / "qualification-input" / "pack" / "MIGRATION_PACK.json",
        "r0072 migration pack manifest",
    )
    if _sha(pack_manifest) != MIGRATION_PACK_SHA256:
        raise GateError("r0072 MIGRATION_PACK SHA-256 mismatch")
    return observed


def _control_anchor(module, spec, layout) -> dict[str, Any]:
    try:
        module._preflight_upgrade_boundary(
            spec,
            layout,
            systemd_probe=_systemd_show,
        )
    except Exception as exc:
        raise GateError(f"r0006 predecessor preflight failed: {exc}") from exc
    return {
        "control_current": "EXACT_R0005",
        "predecessor_source_commit": PREDECESSOR_SOURCE_COMMIT,
        "predecessor_payload_sha256": PREDECESSOR_PAYLOAD_SHA256,
        "successor_worker_profile_activation": "ABSENT",
    }


def reconcile() -> dict[str, Any]:
    _require_root()
    before = _production_anchor()
    migration = _migration_anchor()
    with tempfile.TemporaryDirectory(prefix="keelaryn-r0006-reconcile-") as td:
        source = _checkout_frozen(Path(td))
        module = _load_engine(source)
        control = _control_anchor(module, _successor_spec(module), _layout(module))
    after = _production_anchor()
    if before != after:
        raise GateError("production boundary changed during r0006 reconcile")
    return {
        "schema": "keelaryn.operation-control-r0006-reconcile.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "production_boundary": after,
        "control_boundary": control,
        "migration_boundary": migration,
        "persistent_mutations_performed": False,
        "drive_mutations_performed": False,
    }


def qualify() -> dict[str, Any]:
    _require_root()
    before = _production_anchor()
    migration = _migration_anchor()
    with tempfile.TemporaryDirectory(prefix="keelaryn-r0006-qualify-") as td:
        work = Path(td)
        source = _checkout_frozen(work)
        payload = _rebuild_frozen(source, work)
        module = _load_engine(source)
        control = _control_anchor(module, _successor_spec(module), _layout(module))
        try:
            active_raw, active, framework = module._load_current_hub_authority(
                _layout(module)
            )
        except Exception as exc:
            raise GateError(
                f"frozen engine production authority check failed: {exc}"
            ) from exc
        if (
            framework != PRODUCTION_SOURCE
            or active.get("transaction_id") != HUB_TRANSACTION_ID
            or _sha(active_raw) != ACTIVE_TRANSACTION_SHA256
        ):
            raise GateError("frozen engine production authority differs from pinned anchor")
    after = _production_anchor()
    if before != after:
        raise GateError("production boundary changed during r0006 qualification")
    return {
        "schema": "keelaryn.operation-control-r0006-production-qualification.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload": payload,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "control_boundary": control,
        "migration_boundary": migration,
        "persistent_mutations_performed": False,
        "drive_mutations_performed": False,
        "production_qualified": True,
        "next_action": "UPGRADE",
    }


def upgrade() -> dict[str, Any]:
    _require_root()
    qualification = qualify()

    # Fresh source/load after the read-only qualification transaction.
    with tempfile.TemporaryDirectory(prefix="keelaryn-r0006-upgrade-") as td:
        source = _checkout_frozen(Path(td))
        module = _load_engine(source)
        spec = _successor_spec(module)
        layout = _layout(module)
        try:
            result = module.upgrade_successor(spec, layout)
        except Exception as exc:
            raise GateError(
                f"r0006 transactional successor upgrade failed: {exc}"
            ) from exc

    after = _production_anchor()
    _readlink_exact(
        CONTROL_CURRENT,
        f"releases/{SOURCE_COMMIT}",
        "control-current after r0006 upgrade",
    )
    if result.get("control_update") != "COMPLETED":
        raise GateError("r0006 successor engine did not return COMPLETED")
    return {
        "schema": "keelaryn.operation-control-r0006-production-upgrade.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "qualification": qualification,
        "upgrade_result": result,
        "production_boundary_after": after,
        "control_current": "EXACT_R0006",
        "hub_pre_apply_activation": "READY",
        "production_current_mutated": False,
        "hub_selector_mutated": False,
        "drive_mutations_performed": False,
        "next_action": "REMOTE_HUB_PRE_APPLY",
    }


def selftest() -> dict[str, Any]:
    hashes = (
        PAYLOAD_SHA256,
        PREDECESSOR_PAYLOAD_SHA256,
        ACTIVE_TRANSACTION_SHA256,
        OLD_SELECTOR_IDENTITY_SHA256,
        NEW_SELECTOR_IDENTITY_SHA256,
        MIGRATION_PACK_SHA256,
        MIGRATION_FREEZE_SHA256,
        MIGRATION_TARGET_AUTHORITY_SHA256,
        MIGRATION_QUALIFICATION_SHA256,
        MIGRATION_SOURCE_MANIFEST_SHA256,
        MIGRATION_CREDENTIAL_SHA256,
        MIGRATION_SOURCE_IDENTITY_SHA256,
    )
    if len(SOURCE_COMMIT) != 40 or len(SOURCE_TREE) != 40:
        raise GateError("r0006 source identities invalid")
    if any(_SHA256.fullmatch(value) is None for value in hashes):
        raise GateError("r0006 frozen SHA-256 identity invalid")
    if len(HUB_TRANSACTION_ID) != 32:
        raise GateError("r0006 Hub transaction identity invalid")
    return {
        "schema": "keelaryn.operation-control-r0006-gate-selftest.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "predecessor_candidate": PREDECESSOR_CANDIDATE,
        "migration_candidate": MIGRATION_CANDIDATE,
        "production_source": PRODUCTION_SOURCE,
        "hub_transaction_id": HUB_TRANSACTION_ID,
        "reconcile_surface": True,
        "read_only_qualification_surface": True,
        "single_command_upgrade_surface": True,
        "upgrade_requalifies_before_mutation": True,
        "pass": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-control-r0006")
    parser.add_argument(
        "command",
        choices=("selftest", "reconcile", "qualify", "upgrade"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "selftest":
            value = selftest()
        elif args.command == "reconcile":
            value = reconcile()
        elif args.command == "qualify":
            value = qualify()
        else:
            value = upgrade()
    except (GateError, OSError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
