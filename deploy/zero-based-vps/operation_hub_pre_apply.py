from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core"
sys.path.insert(0, str(CORE))

from keelaryn_core.operation_hub_pre_apply_activation import (  # noqa: E402
    ACTIVATION_NAME,
    HubPreApplyActivationError,
    read_hub_pre_apply_activation,
    verify_hub_pre_apply_activation_authority,
)
from keelaryn_core.operation_hub_pre_apply_profile import (  # noqa: E402
    HubPreApplyProfileError,
    PROFILE_NAME,
    PROFILE_SCHEMA,
    read_hub_pre_apply_profile,
)


PROFILE_PATH = Path("/var/lib/keelaryn/operation-control") / PROFILE_NAME
CONTROL_CURRENT = Path("/opt/keelaryn/control-current")
CURRENT = Path("/opt/keelaryn/current")
SELECTOR = Path("/etc/keelaryn/hub.env")
STATE_ROOT = Path("/var/lib/keelaryn/deployment")
MUTATION_GATE_ROOT = Path("/var/lib/keelaryn/mutation-gate")
MIGRATION_ROOT = Path("/var/lib/keelaryn/migration")
WRITER_UNIT = "keelaryn-drive.service"


class HubPreApplyWorkerError(RuntimeError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def _private_file(path: Path, label: str) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise HubPreApplyWorkerError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise HubPreApplyWorkerError(f"{label} must be one regular file")
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise HubPreApplyWorkerError(
                f"{label} must be current-user owned mode 0600"
            )
    return path


def _hex(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise HubPreApplyWorkerError(f"{label} is invalid")
    return value


def _load_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    try:
        return read_hub_pre_apply_profile(path)
    except HubPreApplyProfileError as exc:
        raise HubPreApplyWorkerError(str(exc)) from exc


def _oauth_environment(path: Path) -> dict[str, str]:
    path = _private_file(path, "r0072 qualification credential")
    required = {
        "KEELARYN_GOOGLE_CLIENT_ID",
        "KEELARYN_GOOGLE_CLIENT_SECRET",
        "KEELARYN_GOOGLE_REFRESH_TOKEN",
    }
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise HubPreApplyWorkerError("qualification credential is unreadable") from exc

    for raw_line in lines:
        line = raw_line.strip()
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
            raise HubPreApplyWorkerError("qualification credential has duplicate key")
        if (
            not value
            or value != value.strip()
            or "\x00" in value
            or "\r" in value
            or "\n" in value
        ):
            raise HubPreApplyWorkerError("qualification credential value is invalid")
        result[key] = value

    if set(result) != required:
        raise HubPreApplyWorkerError("qualification credential keys mismatch")
    return result


def _run(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 7200):
    try:
        return subprocess.run(
            args,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HubPreApplyWorkerError("subprocess outcome is uncertain") from exc


def _writer_inactive() -> bool:
    active = _run(["systemctl", "is-active", WRITER_UNIT], timeout=60)
    pid = _run(
        ["systemctl", "show", WRITER_UNIT, "-p", "MainPID", "--value"],
        timeout=60,
    )
    return (
        active.returncode in {0, 3}
        and active.stdout.strip() == "inactive"
        and pid.returncode == 0
        and pid.stdout.strip() == "0"
    )


def _status(profile: dict[str, Any]) -> dict[str, Any]:
    tool = CURRENT / "deploy" / "zero-based-vps" / "hub_cutover.py"
    result = _run(
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
            profile["framework_source_commit"],
            "status",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        raise HubPreApplyWorkerError("Hub cutover status failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HubPreApplyWorkerError("Hub cutover status is invalid") from exc
    if not isinstance(value, dict):
        raise HubPreApplyWorkerError("Hub cutover status is not an object")
    return value


def _artifact(path: Path, expected_sha: str, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise HubPreApplyWorkerError(f"{label} is absent or unsafe")
    raw = path.read_bytes()
    if _sha(raw) != expected_sha:
        raise HubPreApplyWorkerError(f"{label} identity mismatch")
    return raw


def run(profile_path: Path = PROFILE_PATH) -> dict[str, Any]:
    if os.name == "posix" and os.geteuid() != 0:
        raise HubPreApplyWorkerError("Hub pre-apply worker requires root")

    profile = _load_profile(profile_path)
    try:
        profile_raw = profile_path.read_bytes()
        activation = read_hub_pre_apply_activation(
            profile_path.parent / ACTIVATION_NAME
        )
        verify_hub_pre_apply_activation_authority(
            activation,
            control_source_commit=profile["control_source_commit"],
            profile_raw=profile_raw,
            update_root=profile_path.parent.parent / "operation-control-updates",
        )
    except (OSError, HubPreApplyActivationError) as exc:
        raise HubPreApplyWorkerError(
            "Hub pre-apply activation is unavailable or mismatched"
        ) from exc

    if (
        not CONTROL_CURRENT.is_symlink()
        or os.readlink(CONTROL_CURRENT)
        != f'releases/{profile["control_source_commit"]}'
    ):
        raise HubPreApplyWorkerError("control-current identity mismatch")

    if (
        not CURRENT.is_symlink()
        or os.readlink(CURRENT)
        != f'releases/{profile["framework_source_commit"]}'
    ):
        raise HubPreApplyWorkerError("production current identity mismatch")
    if not _writer_inactive():
        raise HubPreApplyWorkerError("writer must remain inactive")

    active = STATE_ROOT / "ACTIVE_TRANSACTION.json"
    active_raw = _private_file(active, "active Hub cutover transaction").read_bytes()
    if _sha(active_raw) != profile["active_transaction_sha256"]:
        raise HubPreApplyWorkerError("active Hub cutover authority mismatch")

    before = _status(profile)
    if (
        before.get("status") != "PREPARED"
        or before.get("transaction_id") != profile["transaction_id"]
    ):
        raise HubPreApplyWorkerError("Hub cutover is not exact PREPARED transaction")

    candidate_root = MIGRATION_ROOT / profile["candidate_id"]
    if candidate_root.is_symlink() or not candidate_root.is_dir():
        raise HubPreApplyWorkerError("migration candidate root is absent or unsafe")

    pack = candidate_root / "qualification-input" / "pack"
    freeze = candidate_root / "migration-candidate-freeze.v1.json"
    authority = candidate_root / "production-target-authority.v1.json"
    qualification = candidate_root / "production-target-qualification.v1.json"
    credential = candidate_root / "qualification-production-drive.env"
    receipt = candidate_root / "pre-apply-cutover-receipt.v3.json"

    freeze_raw = _artifact(
        freeze, profile["freeze_receipt_sha256"], "freeze receipt"
    )
    authority_raw = _artifact(
        authority, profile["target_authority_sha256"], "target authority"
    )
    qualification_raw = _artifact(
        qualification,
        profile["qualification_evidence_sha256"],
        "qualification evidence",
    )
    _artifact(credential, profile["credential_sha256"], "qualification credential")

    try:
        freeze_value = json.loads(freeze_raw)
        authority_value = json.loads(authority_raw)
        qualification_value = json.loads(qualification_raw)
    except json.JSONDecodeError as exc:
        raise HubPreApplyWorkerError("migration authority JSON is invalid") from exc

    if (
        freeze_value.get("source_commit") != profile["candidate_source_commit"]
        or freeze_value.get("source_tree") != profile["candidate_source_tree"]
        or freeze_value.get("pack_sha256") != profile["pack_sha256"]
    ):
        raise HubPreApplyWorkerError("freeze identity mismatch")
    if (
        authority_value.get("candidate_id") != profile["candidate_id"]
        or authority_value.get("pack_sha256") != profile["pack_sha256"]
        or not isinstance(authority_value.get("target_id"), str)
        or _sha(authority_value["target_id"].encode("utf-8"))
        != profile["new_selector_identity_sha256"]
    ):
        raise HubPreApplyWorkerError("target authority mismatch")
    if (
        qualification_value.get("candidate_id") != profile["candidate_id"]
        or qualification_value.get("pack_sha256") != profile["pack_sha256"]
        or qualification_value.get("source_commit")
        != profile["candidate_source_commit"]
        or qualification_value.get("source_tree") != profile["candidate_source_tree"]
        or qualification_value.get("target_identity_sha256")
        != profile["new_selector_identity_sha256"]
        or qualification_value.get("outcome") != "TARGET_QUALIFICATION_PASS"
        or qualification_value.get("cutover_authorized") is not False
    ):
        raise HubPreApplyWorkerError("qualification evidence mismatch")

    oauth = _oauth_environment(credential)
    env = dict(os.environ)
    env.update(oauth)
    env.update(
        {
            "KEELARYN_PRODUCTION_CUTOVER_ENABLE": "YES",
            "KEELARYN_HUB_SELECTOR_PATH": str(SELECTOR),
            "KEELARYN_DEPLOYMENT_STATE_ROOT": str(STATE_ROOT),
            "KEELARYN_MUTATION_GATE_ROOT": str(MUTATION_GATE_ROOT),
            "KEELARYN_SOURCE_COMMIT": profile["framework_source_commit"],
            "KEELARYN_MIGRATION_SOURCE_ROOT_ID": profile["migration_source_root_id"],
            "KEELARYN_PRE_APPLY_CUTOVER_RECEIPT": str(receipt),
            "KEELARYN_MIGRATION_PACK_DIR": str(pack),
            "KEELARYN_MIGRATION_FREEZE_RECEIPT": str(freeze),
            "KEELARYN_MIGRATION_TARGET_AUTHORITY": str(authority),
            "KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE": str(qualification),
        }
    )

    finalizer = CURRENT / "tests" / "live" / "run_migration_pre_apply_cutover.py"
    result = _run([sys.executable, "-B", str(finalizer)], env=env)
    if result.returncode != 0:
        raise HubPreApplyWorkerError("production pre-apply finalizer reported failure")

    after = _status(profile)
    if (
        after.get("status") != "APPLIED"
        or after.get("transaction_id") != profile["transaction_id"]
    ):
        raise HubPreApplyWorkerError("post-finalizer Hub status is not exact APPLIED")
    if not _writer_inactive():
        raise HubPreApplyWorkerError("writer changed during pre-apply finalization")

    receipt_raw = _private_file(receipt, "pre-apply receipt").read_bytes()
    try:
        receipt_value = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubPreApplyWorkerError("pre-apply receipt is invalid") from exc
    if receipt_raw != _canonical(receipt_value):
        raise HubPreApplyWorkerError("pre-apply receipt is not canonical JSON")
    if (
        receipt_value.get("schema")
        != "keelaryn.migration-pre-apply-private-receipt.v3"
        or receipt_value.get("transaction_id") != profile["transaction_id"]
        or receipt_value.get("active_transaction_sha256")
        != profile["active_transaction_sha256"]
        or receipt_value.get("framework_source_commit")
        != profile["framework_source_commit"]
        or receipt_value.get("source_commit") != profile["candidate_source_commit"]
        or receipt_value.get("source_tree") != profile["candidate_source_tree"]
        or receipt_value.get("pack_sha256") != profile["pack_sha256"]
        or receipt_value.get("new_selector_identity_sha256")
        != profile["new_selector_identity_sha256"]
        or receipt_value.get("migration_source_identity_sha256")
        != profile["migration_source_identity_sha256"]
        or receipt_value.get("outcome") != "PRE_APPLY_VERIFIED"
    ):
        raise HubPreApplyWorkerError("pre-apply receipt identity mismatch")

    return {
        "schema": "keelaryn.operation-hub-pre-apply-result.v1",
        "status": "APPLIED",
        "writer_state": "INACTIVE",
        "mutation": "SELECTOR_APPLIED",
    }


def main() -> int:
    phase = "PREFLIGHT"
    try:
        phase = "EXECUTE"
        result = run()
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-hub-pre-apply-failure.v1",
                    "phase": phase,
                    "error_class": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
