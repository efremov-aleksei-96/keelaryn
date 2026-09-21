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
