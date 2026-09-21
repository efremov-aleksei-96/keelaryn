from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any


PROFILE_SCHEMA = "keelaryn.operation-hub-pre-apply-profile.v1"
PROFILE_NAME = "hub-pre-apply-profile.json"
OPERATION = "HUB_PRE_APPLY"
REQUEST_PROFILE = "CURRENT_PREPARED"
AUTHORIZATION = "APPROVED"

_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[0-9a-f]{32}$")
_CANDIDATE = re.compile(r"^migration-r[0-9]{4}-[0-9]{8}-[0-9]{2}$")
_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{10,256}$")

_PROFILE_KEYS = {
    "schema",
    "operation",
    "request_profile",
    "authorization",
    "control_source_commit",
    "transaction_id",
    "active_transaction_sha256",
    "framework_source_commit",
    "candidate_id",
    "candidate_source_commit",
    "candidate_source_tree",
    "pack_sha256",
    "freeze_receipt_sha256",
    "target_authority_sha256",
    "qualification_evidence_sha256",
    "credential_sha256",
    "migration_source_root_id",
    "migration_source_identity_sha256",
    "new_selector_identity_sha256",
}


class HubPreApplyProfileError(RuntimeError):
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


def _hex(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise HubPreApplyProfileError(f"{label} is invalid")
    return value


def parse_hub_pre_apply_profile(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubPreApplyProfileError("Hub pre-apply profile is invalid JSON") from exc

    if not isinstance(value, dict) or set(value) != _PROFILE_KEYS:
        raise HubPreApplyProfileError("Hub pre-apply profile keys mismatch")
    if value["schema"] != PROFILE_SCHEMA:
        raise HubPreApplyProfileError("Hub pre-apply profile schema mismatch")
    if raw != _canonical(value):
        raise HubPreApplyProfileError("Hub pre-apply profile is not canonical JSON")
    if value["operation"] != OPERATION:
        raise HubPreApplyProfileError("Hub pre-apply operation mismatch")
    if value["request_profile"] != REQUEST_PROFILE:
        raise HubPreApplyProfileError("Hub pre-apply request profile mismatch")
    if value["authorization"] != AUTHORIZATION:
        raise HubPreApplyProfileError("Hub pre-apply authorization is not approved")

    _hex(value["transaction_id"], _ID, "transaction_id")
    for key in (
        "active_transaction_sha256",
        "pack_sha256",
        "freeze_receipt_sha256",
        "target_authority_sha256",
        "qualification_evidence_sha256",
        "credential_sha256",
        "migration_source_identity_sha256",
        "new_selector_identity_sha256",
    ):
        _hex(value[key], _SHA256, key)
    for key in (
        "control_source_commit",
        "framework_source_commit",
        "candidate_source_commit",
        "candidate_source_tree",
    ):
        _hex(value[key], _OID, key)

    candidate = value["candidate_id"]
    if not isinstance(candidate, str) or _CANDIDATE.fullmatch(candidate) is None:
        raise HubPreApplyProfileError("candidate_id is invalid")

    source_root = value["migration_source_root_id"]
    if not isinstance(source_root, str) or _DRIVE_ID.fullmatch(source_root) is None:
        raise HubPreApplyProfileError("migration source root ID is invalid")
    if _sha(source_root.encode("utf-8")) != value["migration_source_identity_sha256"]:
        raise HubPreApplyProfileError("migration source identity mismatch")

    return dict(value)


def read_hub_pre_apply_profile(
    path: str | Path,
    *,
    expected_mode: int = 0o600,
) -> dict[str, Any]:
    candidate = Path(path)
    try:
        info = candidate.stat(follow_symlinks=False)
    except OSError as exc:
        raise HubPreApplyProfileError(
            "Hub pre-apply profile cannot be inspected"
        ) from exc
    if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise HubPreApplyProfileError(
            "Hub pre-apply profile must be one regular file"
        )
    if stat.S_IMODE(info.st_mode) != expected_mode:
        raise HubPreApplyProfileError(
            f"Hub pre-apply profile must have mode {expected_mode:04o}"
        )
    if os.name == "posix" and info.st_uid != os.geteuid():
        raise HubPreApplyProfileError(
            "Hub pre-apply profile must be current-user owned"
        )
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise HubPreApplyProfileError(
            "Hub pre-apply profile cannot be read"
        ) from exc
    return parse_hub_pre_apply_profile(raw)


__all__ = [
    "AUTHORIZATION",
    "HubPreApplyProfileError",
    "OPERATION",
    "PROFILE_NAME",
    "PROFILE_SCHEMA",
    "REQUEST_PROFILE",
    "parse_hub_pre_apply_profile",
    "read_hub_pre_apply_profile",
]
