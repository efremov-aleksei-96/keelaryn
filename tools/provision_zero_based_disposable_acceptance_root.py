from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

from keelaryn_core.drive_backend import DriveAlreadyExists, DriveNotFound, DriveUncertainMutation
from keelaryn_core.drive_mutation_gate import DriveMutationGate
from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.protocol import canonical_json_bytes, strict_json_bytes


ACCEPTANCE_ROOT_NAME = "Keelaryn__DISPOSABLE_LIVE_ACCEPTANCE_ROOT"
SENTINEL_NAME = "README.md"
SENTINEL_BYTES = (
    b"KEELARYN DISPOSABLE LIVE ACCEPTANCE ROOT\n"
    b"DO NOT USE A PRODUCTION OR PERSONAL HUB HERE.\n"
)
CHILD_PREFIX = "Keelaryn__Disposable_Acceptance_"

AUTHORITY_SCHEMA = "keelaryn.disposable-live-acceptance-authority.v1"
RESULT_SCHEMA = "keelaryn.disposable-live-acceptance-provision.v1"
FAILURE_SCHEMA = "keelaryn.disposable-live-acceptance-provision-failure.v1"
ENABLE_ENV = "KEELARYN_DISPOSABLE_ACCEPTANCE_PROVISION_ENABLE"
AUTHORITY_ENV = "KEELARYN_DISPOSABLE_ACCEPTANCE_AUTHORITY"
ROOT_PARENT_ID = "root"


class DisposableAcceptanceProvisionError(RuntimeError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _tool_sha256() -> str:
    return _sha256(Path(__file__).read_bytes())


def _private_parent(path: Path) -> Path:
    parent = path.absolute().parent
    if parent.is_symlink() or not parent.is_dir():
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority parent must be a real directory"
        )
    info = parent.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority parent must be owner-controlled mode 0700"
        )
    return parent


def _private_authority(path: Path) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority must be a regular file"
        )
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority must be owner-controlled mode 0600"
        )
    return path


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_write_new(path: Path, raw: bytes) -> None:
    parent = _private_parent(path)
    path = path.absolute()
    if path.exists() or path.is_symlink():
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority already exists"
        )

    temp = parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        fd = os.open(temp, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)

        os.replace(temp, path)
        _fsync_dir(parent)
        _private_authority(path)
    finally:
        temp.unlink(missing_ok=True)


def _strict_authority(raw: bytes) -> dict[str, str]:
    value = strict_json_bytes(raw, label="DISPOSABLE_ACCEPTANCE_AUTHORITY")
    expected = {
        "schema",
        "tool_sha256",
        "root_id",
        "sentinel_id",
        "root_name",
        "sentinel_name",
        "sentinel_sha256",
        "child_prefix",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority has invalid keys"
        )
    if value["schema"] != AUTHORITY_SCHEMA:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority schema mismatch"
        )
    for key in expected - {"schema"}:
        if not isinstance(value[key], str) or not value[key]:
            raise DisposableAcceptanceProvisionError(
                f"disposable acceptance authority {key} is invalid"
            )
    for key in ("tool_sha256", "sentinel_sha256"):
        if len(value[key]) != 64 or any(ch not in "0123456789abcdef" for ch in value[key]):
            raise DisposableAcceptanceProvisionError(
                f"disposable acceptance authority {key} is not exact SHA-256"
            )
    return dict(value)


def _load_or_create_authority(
    drive,
    path: Path,
    *,
    tool_sha256: str,
) -> tuple[dict[str, str], bool]:
    path = path.absolute()
    _private_parent(path)

    if path.exists() or path.is_symlink():
        raw = _private_authority(path).read_bytes()
        value = _strict_authority(raw)
        expected = {
            "schema": AUTHORITY_SCHEMA,
            "tool_sha256": value["tool_sha256"],
            "root_id": value["root_id"],
            "sentinel_id": value["sentinel_id"],
            "root_name": ACCEPTANCE_ROOT_NAME,
            "sentinel_name": SENTINEL_NAME,
            "sentinel_sha256": _sha256(SENTINEL_BYTES),
            "child_prefix": CHILD_PREFIX,
        }
        if value != expected:
            raise DisposableAcceptanceProvisionError(
                "disposable acceptance authority disagrees with exact root contract"
            )
        return value, False

    existing = drive.list_children(ROOT_PARENT_ID, name=ACCEPTANCE_ROOT_NAME)
    if existing:
        raise DisposableAcceptanceProvisionError(
            "unmanaged disposable acceptance root already exists"
        )

    root_id, sentinel_id = drive.generate_ids(2)
    value = {
        "schema": AUTHORITY_SCHEMA,
        "tool_sha256": tool_sha256,
        "root_id": root_id,
        "sentinel_id": sentinel_id,
        "root_name": ACCEPTANCE_ROOT_NAME,
        "sentinel_name": SENTINEL_NAME,
        "sentinel_sha256": _sha256(SENTINEL_BYTES),
        "child_prefix": CHILD_PREFIX,
    }
    _atomic_write_new(path, canonical_json_bytes(value))
    return value, True


def _verify_root_namespace(drive, root_id: str) -> None:
    matches = drive.list_children(ROOT_PARENT_ID, name=ACCEPTANCE_ROOT_NAME)
    if len(matches) != 1 or matches[0].file_id != root_id:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance root namespace is absent, ambiguous, or conflicting"
        )


def _ensure_root(drive, authority: dict[str, str]) -> bool:
    root_id = authority["root_id"]
    try:
        root = drive.get(root_id, include_trashed=True)
    except DriveNotFound:
        if drive.list_children(ROOT_PARENT_ID, name=ACCEPTANCE_ROOT_NAME):
            raise DisposableAcceptanceProvisionError(
                "disposable acceptance root name became conflicting before create"
            )
        attempted = True
        try:
            drive.create_folder(
                ROOT_PARENT_ID,
                ACCEPTANCE_ROOT_NAME,
                file_id=root_id,
                label="drive.disposable-acceptance.root.create",
            )
        except (DriveUncertainMutation, DriveAlreadyExists):
            pass
        try:
            root = drive.get(root_id, include_trashed=True)
        except DriveNotFound as exc:
            raise DisposableAcceptanceProvisionError(
                "reserved disposable acceptance root is not observable after create attempt"
            ) from exc
    else:
        attempted = False

    if root.trashed or not root.is_folder or root.name != ACCEPTANCE_ROOT_NAME:
        raise DisposableAcceptanceProvisionError(
            "reserved disposable acceptance root resolves to conflicting Drive object"
        )

    _verify_root_namespace(drive, root_id)
    return attempted


def _verify_children(
    drive,
    authority: dict[str, str],
    *,
    allow_missing_sentinel: bool,
) -> None:
    root_id = authority["root_id"]
    sentinel_id = authority["sentinel_id"]
    children = drive.list_children(root_id)

    sentinel_matches = [item for item in children if item.name == SENTINEL_NAME]
    if len(sentinel_matches) > 1:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance sentinel name is ambiguous"
        )
    if sentinel_matches and sentinel_matches[0].file_id != sentinel_id:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance sentinel name conflicts with reserved identity"
        )

    for item in children:
        if item.file_id == sentinel_id:
            continue
        if item.trashed or not item.is_folder or not item.name.startswith(CHILD_PREFIX):
            raise DisposableAcceptanceProvisionError(
                "disposable acceptance root contains unexpected objects"
            )

    if not allow_missing_sentinel:
        if len(sentinel_matches) != 1 or sentinel_matches[0].file_id != sentinel_id:
            raise DisposableAcceptanceProvisionError(
                "disposable acceptance sentinel is missing"
            )


def _ensure_sentinel(drive, authority: dict[str, str]) -> bool:
    root_id = authority["root_id"]
    sentinel_id = authority["sentinel_id"]

    _verify_children(drive, authority, allow_missing_sentinel=True)

    try:
        sentinel = drive.get(sentinel_id, include_trashed=True)
    except DriveNotFound:
        _verify_children(drive, authority, allow_missing_sentinel=True)
        attempted = True
        try:
            drive.create_blob(
                root_id,
                SENTINEL_NAME,
                SENTINEL_BYTES,
                file_id=sentinel_id,
                label="drive.disposable-acceptance.sentinel.create",
            )
        except (DriveUncertainMutation, DriveAlreadyExists):
            pass
        try:
            sentinel = drive.get(sentinel_id, include_trashed=True)
        except DriveNotFound as exc:
            raise DisposableAcceptanceProvisionError(
                "reserved disposable acceptance sentinel is not observable after create attempt"
            ) from exc
    else:
        attempted = False

    if (
        sentinel.trashed
        or sentinel.is_folder
        or sentinel.parent_id != root_id
        or sentinel.name != SENTINEL_NAME
    ):
        raise DisposableAcceptanceProvisionError(
            "reserved disposable acceptance sentinel resolves to conflicting Drive object"
        )
    if drive.download(sentinel_id) != SENTINEL_BYTES:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance sentinel bytes do not match exact contract"
        )

    _verify_children(drive, authority, allow_missing_sentinel=False)
    return attempted


def provision_disposable_acceptance_root(
    drive,
    authority_path: Path,
    *,
    tool_sha256: str,
) -> dict[str, Any]:
    authority, authority_created = _load_or_create_authority(
        drive,
        authority_path,
        tool_sha256=tool_sha256,
    )
    root_attempted = _ensure_root(drive, authority)
    sentinel_attempted = _ensure_sentinel(drive, authority)

    _verify_root_namespace(drive, authority["root_id"])
    _verify_children(drive, authority, allow_missing_sentinel=False)

    sentinel = drive.get(authority["sentinel_id"], include_trashed=False)
    if drive.download(sentinel.file_id) != SENTINEL_BYTES:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance sentinel changed at final audit"
        )

    authority_raw = _private_authority(authority_path).read_bytes()
    if _strict_authority(authority_raw) != authority:
        raise DisposableAcceptanceProvisionError(
            "disposable acceptance authority changed during provisioning"
        )

    disposable_children = [
        item
        for item in drive.list_children(authority["root_id"])
        if item.file_id != authority["sentinel_id"]
    ]

    return {
        "schema": RESULT_SCHEMA,
        "status": "PROVISION_PASS",
        "acceptance_root_identity_sha256": _sha256(authority["root_id"].encode("utf-8")),
        "sentinel_identity_sha256": _sha256(authority["sentinel_id"].encode("utf-8")),
        "sentinel_bytes_sha256": _sha256(SENTINEL_BYTES),
        "authority_sha256": _sha256(authority_raw),
        "authority_created": authority_created,
        "existing_disposable_child_count": len(disposable_children),
        "drive_mutations_performed": root_attempted or sentinel_attempted,
        "production_selector_mutated": False,
        "cutover_authorized": False,
    }


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise DisposableAcceptanceProvisionError(f"missing required environment: {name}")
    return value


def main() -> int:
    phase = "preflight"
    try:
        if _required(ENABLE_ENV) != "YES":
            raise DisposableAcceptanceProvisionError(
                "disposable acceptance provisioning is not explicitly enabled"
            )
        authority_path = Path(_required(AUTHORITY_ENV))

        phase = "mutation-gate"
        with DriveMutationGate.from_environment():
            phase = "oauth"
            provider = GoogleOAuthRefreshTokenProvider.from_environment()
            drive = GoogleDriveBackend(provider)

            phase = "provision"
            result = provision_disposable_acceptance_root(
                drive,
                authority_path,
                tool_sha256=_tool_sha256(),
            )

        rendered = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        authority = _strict_authority(_private_authority(authority_path).read_bytes())
        forbidden = (
            authority["root_id"],
            authority["sentinel_id"],
            str(authority_path),
        )
        if any(secret and secret in rendered for secret in forbidden):
            raise DisposableAcceptanceProvisionError(
                "sanitized disposable acceptance provisioning output leaked private identity/path"
            )

        print(rendered, flush=True)
        return 0

    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": FAILURE_SCHEMA,
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
