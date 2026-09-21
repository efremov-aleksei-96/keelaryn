from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any


ACTIVATION_SCHEMA = "keelaryn.operation-hub-pre-apply-activation.v1"
ACTIVATION_NAME = "hub-pre-apply-activation.json"
OPERATION = "HUB_PRE_APPLY"
CONTROL_UPDATE_COMPLETED_SCHEMA = "keelaryn.operation-control-update-completed.v1"

_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEYS = {
    "schema",
    "operation",
    "control_source_commit",
    "profile_sha256",
    "control_update_transaction_id",
    "control_update_completed_sha256",
}
_COMPLETED_KEYS = {
    "schema",
    "transaction_id",
    "production_current_unchanged",
    "control_current",
    "persistent_services",
    "worker_unit",
    "preauthorization",
    "credential_unchanged",
}


class HubPreApplyActivationError(RuntimeError):
    pass


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


def activation_bytes(
    *,
    control_source_commit: str,
    profile_raw: bytes,
    control_update_transaction_id: str,
    control_update_completed_raw: bytes,
) -> bytes:
    if _OID.fullmatch(control_source_commit) is None:
        raise HubPreApplyActivationError("control source commit is invalid")
    if _SHA256.fullmatch(control_update_transaction_id) is None:
        raise HubPreApplyActivationError("control update transaction ID is invalid")
    return _canonical(
        {
            "schema": ACTIVATION_SCHEMA,
            "operation": OPERATION,
            "control_source_commit": control_source_commit,
            "profile_sha256": _sha(profile_raw),
            "control_update_transaction_id": control_update_transaction_id,
            "control_update_completed_sha256": _sha(control_update_completed_raw),
        }
    )


def parse_hub_pre_apply_activation(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubPreApplyActivationError(
            "Hub pre-apply activation is invalid JSON"
        ) from exc
    if not isinstance(value, dict) or set(value) != _KEYS:
        raise HubPreApplyActivationError("Hub pre-apply activation keys mismatch")
    if value["schema"] != ACTIVATION_SCHEMA or value["operation"] != OPERATION:
        raise HubPreApplyActivationError("Hub pre-apply activation identity mismatch")
    if raw != _canonical(value):
        raise HubPreApplyActivationError(
            "Hub pre-apply activation is not canonical JSON"
        )
    if _OID.fullmatch(value["control_source_commit"]) is None:
        raise HubPreApplyActivationError("activation control source is invalid")
    for key in (
        "profile_sha256",
        "control_update_transaction_id",
        "control_update_completed_sha256",
    ):
        if not isinstance(value[key], str) or _SHA256.fullmatch(value[key]) is None:
            raise HubPreApplyActivationError(f"{key} is invalid")
    return dict(value)


def read_hub_pre_apply_activation(
    path: str | Path,
    *,
    expected_mode: int = 0o600,
) -> dict[str, Any]:
    candidate = Path(path)
    try:
        info = candidate.stat(follow_symlinks=False)
    except OSError as exc:
        raise HubPreApplyActivationError(
            "Hub pre-apply activation cannot be inspected"
        ) from exc
    if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise HubPreApplyActivationError(
            "Hub pre-apply activation must be one regular file"
        )
    if stat.S_IMODE(info.st_mode) != expected_mode:
        raise HubPreApplyActivationError(
            f"Hub pre-apply activation must have mode {expected_mode:04o}"
        )
    if os.name == "posix" and info.st_uid != os.geteuid():
        raise HubPreApplyActivationError(
            "Hub pre-apply activation must be current-user owned"
        )
    return parse_hub_pre_apply_activation(candidate.read_bytes())


def verify_hub_pre_apply_activation(
    activation: dict[str, Any],
    *,
    control_source_commit: str,
    profile_raw: bytes,
) -> None:
    if (
        activation["operation"] != OPERATION
        or activation["control_source_commit"] != control_source_commit
        or activation["profile_sha256"] != _sha(profile_raw)
    ):
        raise HubPreApplyActivationError(
            "Hub pre-apply activation does not bind exact profile/source"
        )


def _private_dir(path: Path, label: str) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise HubPreApplyActivationError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise HubPreApplyActivationError(f"{label} must be one real directory")
    if os.name == "posix" and (
        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise HubPreApplyActivationError(
            f"{label} must be current-user owned mode 0700"
        )
    return path


def read_control_update_completed(
    update_root: str | Path,
    activation: dict[str, Any],
) -> bytes:
    root = _private_dir(Path(update_root), "control update root")
    transaction_id = activation["control_update_transaction_id"]
    transaction = _private_dir(
        root / transaction_id,
        "control update transaction",
    )
    completed = transaction / "COMPLETED.json"
    try:
        info = completed.stat(follow_symlinks=False)
    except OSError as exc:
        raise HubPreApplyActivationError(
            "control update COMPLETED authority cannot be inspected"
        ) from exc
    if completed.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise HubPreApplyActivationError(
            "control update COMPLETED authority must be one regular file"
        )
    if os.name == "posix" and (
        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise HubPreApplyActivationError(
            "control update COMPLETED authority must be current-user owned mode 0600"
        )
    try:
        raw = completed.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubPreApplyActivationError(
            "control update COMPLETED authority is unreadable/invalid"
        ) from exc
    if not isinstance(value, dict) or set(value) != _COMPLETED_KEYS:
        raise HubPreApplyActivationError(
            "control update COMPLETED authority keys mismatch"
        )
    if raw != _canonical(value):
        raise HubPreApplyActivationError(
            "control update COMPLETED authority is not canonical JSON"
        )
    if (
        value["schema"] != CONTROL_UPDATE_COMPLETED_SCHEMA
        or value["transaction_id"] != transaction_id
        or value["production_current_unchanged"] is not True
        or value["control_current"] != "SUCCESSOR"
        or value["persistent_services"] != "ACTIVE_STABLE"
        or value["worker_unit"] != "STATIC_INACTIVE"
        or value["preauthorization"] != "EXACT"
        or value["credential_unchanged"] is not True
    ):
        raise HubPreApplyActivationError(
            "control update COMPLETED authority semantics mismatch"
        )
    if _sha(raw) != activation["control_update_completed_sha256"]:
        raise HubPreApplyActivationError(
            "control update COMPLETED authority hash mismatch"
        )
    return raw


def verify_hub_pre_apply_activation_authority(
    activation: dict[str, Any],
    *,
    control_source_commit: str,
    profile_raw: bytes,
    update_root: str | Path,
) -> None:
    verify_hub_pre_apply_activation(
        activation,
        control_source_commit=control_source_commit,
        profile_raw=profile_raw,
    )
    read_control_update_completed(update_root, activation)
