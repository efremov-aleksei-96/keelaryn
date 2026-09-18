from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCHEMA = "keelaryn.zero-vps-deployment-state-normalization.v1"
ACTIVE_NAME = "ACTIVE_TRANSACTION.json"
LOCK_NAME = "LOCK"
RECORD_NAME_RE = re.compile(r"[0-9a-f]{32}\.json")
HISTORY_SCHEMAS = {
    "keelaryn.zero-vps-release-switch.v1",
    "keelaryn.zero-vps-hub-cutover.v1",
    "keelaryn.zero-vps-hub-cutover.v2",
}
TERMINAL_SCHEMAS = {
    "keelaryn.zero-vps-release-switch-terminal.v1",
    "keelaryn.zero-vps-hub-cutover-terminal.v1",
}
ALLOWED_RECORD_MODES = {0o600, 0o644}


class DeploymentStateNormalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Record:
    relative: str
    path: Path
    mode: int
    dev: int
    ino: int
    size: int
    sha256: str
    schema: str
    transaction_id: str


def _strict_json(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DeploymentStateNormalizationError(f"{label} is not UTF-8") from exc

    def hook(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DeploymentStateNormalizationError(
                    f"{label} contains duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        raise DeploymentStateNormalizationError(f"{label} is invalid JSON") from exc


def _owned_directory(path: Path, label: str, mode: int) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_dir():
        raise DeploymentStateNormalizationError(f"{label} must be a real directory")
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode:
        raise DeploymentStateNormalizationError(
            f"{label} must be owner-controlled mode {mode:04o}"
        )
    return path


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _open_record(path: Path) -> int:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise DeploymentStateNormalizationError(
            "deployment-state normalization requires POSIX O_NOFOLLOW support"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        return os.open(path, flags)
    except OSError as exc:
        raise DeploymentStateNormalizationError(
            f"cannot open provenance record without following symlinks: {path.name}"
        ) from exc


def _inspect_record(path: Path, directory_name: str) -> Record:
    if not RECORD_NAME_RE.fullmatch(path.name):
        raise DeploymentStateNormalizationError(
            f"deployment {directory_name} contains invalid record name: {path.name}"
        )
    fd = _open_record(path)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise DeploymentStateNormalizationError(
                f"deployment {directory_name} record must be regular: {path.name}"
            )
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid != os.geteuid():
            raise DeploymentStateNormalizationError(
                f"deployment {directory_name} record has untrusted owner: {path.name}"
            )
        if mode not in ALLOWED_RECORD_MODES:
            raise DeploymentStateNormalizationError(
                f"deployment {directory_name} record mode is neither 0600 nor legacy 0644: "
                f"{path.name} mode={mode:04o}"
            )
        raw = _read_fd(fd)
    finally:
        os.close(fd)

    value = _strict_json(raw, f"deployment {directory_name} record {path.name}")
    if not isinstance(value, dict):
        raise DeploymentStateNormalizationError(
            f"deployment {directory_name} record root must be an object: {path.name}"
        )
    txid = path.stem
    if value.get("transaction_id") != txid:
        raise DeploymentStateNormalizationError(
            f"deployment {directory_name} record transaction_id mismatch: {path.name}"
        )
    schema = value.get("schema")
    allowed_schemas = TERMINAL_SCHEMAS if directory_name == "terminal" else HISTORY_SCHEMAS
    if schema not in allowed_schemas:
        raise DeploymentStateNormalizationError(
            f"deployment {directory_name} record schema is not recognized: {path.name}"
        )
    return Record(
        relative=f"{directory_name}/{path.name}",
        path=path,
        mode=mode,
        dev=info.st_dev,
        ino=info.st_ino,
        size=info.st_size,
        sha256=hashlib.sha256(raw).hexdigest(),
        schema=schema,
        transaction_id=txid,
    )


def _audit(state_root: Path) -> tuple[Record, ...]:
    state_root = _owned_directory(state_root, "deployment state root", 0o700)
    terminal = _owned_directory(
        state_root / "terminal", "deployment terminal directory", 0o700
    )
    history = _owned_directory(
        state_root / "history", "deployment history directory", 0o700
    )
    active = state_root / ACTIVE_NAME
    if active.exists() or active.is_symlink():
        raise DeploymentStateNormalizationError(
            "deployment state is not IDLE; active transaction authority exists"
        )
    observed = {item.name for item in state_root.iterdir()}
    if observed != {LOCK_NAME, "terminal", "history"}:
        raise DeploymentStateNormalizationError(
            "deployment state root contains unexpected or incomplete objects"
        )

    records: list[Record] = []
    for directory, name in ((terminal, "terminal"), (history, "history")):
        for item in sorted(directory.iterdir(), key=lambda value: value.name):
            records.append(_inspect_record(item, name))
    return tuple(records)


@contextmanager
def _locked(state_root: Path) -> Iterator[None]:
    state_root = _owned_directory(state_root, "deployment state root", 0o700)
    lock = state_root / LOCK_NAME
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise DeploymentStateNormalizationError(
            "deployment-state normalization requires POSIX O_NOFOLLOW support"
        )
    flags = os.O_RDWR | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(lock, flags)
    except OSError as exc:
        raise DeploymentStateNormalizationError(
            "cannot open deployment lock without following symlinks"
        ) from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise DeploymentStateNormalizationError(
                "deployment lock must be owner-controlled regular file mode 0600"
            )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeploymentStateNormalizationError(
                "deployment state is busy; normalization requires IDLE exclusive authority"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _snapshot_identity(records: tuple[Record, ...]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            item.relative,
            item.mode,
            item.dev,
            item.ino,
            item.size,
            item.sha256,
            item.schema,
            item.transaction_id,
        )
        for item in records
    )


def _normalize_one(record: Record) -> None:
    fd = _open_record(record.path)
    try:
        info = os.fstat(fd)
        raw = _read_fd(fd)
        observed = (
            stat.S_IMODE(info.st_mode),
            info.st_dev,
            info.st_ino,
            info.st_size,
            hashlib.sha256(raw).hexdigest(),
        )
        expected = (
            record.mode,
            record.dev,
            record.ino,
            record.size,
            record.sha256,
        )
        if observed != expected:
            raise DeploymentStateNormalizationError(
                f"provenance record changed at normalization commit boundary: {record.relative}"
            )
        if record.mode == 0o644:
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        after = os.fstat(fd)
        after_raw = _read_fd(fd)
        if (
            stat.S_IMODE(after.st_mode) != 0o600
            or after.st_dev != record.dev
            or after.st_ino != record.ino
            or after.st_size != record.size
            or hashlib.sha256(after_raw).hexdigest() != record.sha256
        ):
            raise DeploymentStateNormalizationError(
                f"provenance record identity changed during normalization: {record.relative}"
            )
    finally:
        os.close(fd)


def normalize_deployment_state(state_root: Path, *, apply: bool) -> dict[str, Any]:
    state_root = state_root.absolute()
    with _locked(state_root):
        before = _audit(state_root)
        legacy = tuple(item for item in before if item.mode == 0o644)
        if not apply:
            return {
                "schema": SCHEMA,
                "status": "NORMALIZATION_REQUIRED" if legacy else "CLEAN",
                "record_count": len(before),
                "legacy_count": len(legacy),
                "changed_count": 0,
                "byte_identity_preserved": True,
                "legacy_records": [
                    {"path": item.relative, "sha256": item.sha256}
                    for item in legacy
                ],
            }

        boundary = _audit(state_root)
        if _snapshot_identity(boundary) != _snapshot_identity(before):
            raise DeploymentStateNormalizationError(
                "deployment provenance changed before normalization commit boundary"
            )

        for record in legacy:
            _normalize_one(record)

        after = _audit(state_root)
        before_by_path = {item.relative: item for item in before}
        after_by_path = {item.relative: item for item in after}
        if set(after_by_path) != set(before_by_path):
            raise DeploymentStateNormalizationError(
                "deployment provenance record set changed during normalization"
            )
        for relative, prior in before_by_path.items():
            current = after_by_path[relative]
            if (
                current.sha256 != prior.sha256
                or current.dev != prior.dev
                or current.ino != prior.ino
                or current.size != prior.size
                or current.schema != prior.schema
                or current.transaction_id != prior.transaction_id
                or current.mode != 0o600
            ):
                raise DeploymentStateNormalizationError(
                    f"deployment provenance identity changed after normalization: {relative}"
                )

        return {
            "schema": SCHEMA,
            "status": "NORMALIZED" if legacy else "CLEAN",
            "record_count": len(after),
            "legacy_count": len(legacy),
            "changed_count": len(legacy),
            "byte_identity_preserved": True,
            "changed_records": [
                {
                    "path": item.relative,
                    "sha256": item.sha256,
                    "mode_before": "0644",
                    "mode_after": "0600",
                }
                for item in legacy
            ],
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-zero-deployment-state-normalize")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path("/var/lib/keelaryn/deployment"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("apply")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = normalize_deployment_state(
            args.state_root,
            apply=args.command == "apply",
        )
    except (DeploymentStateNormalizationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
