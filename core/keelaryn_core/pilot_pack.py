from __future__ import annotations

import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .protocol import ID_RE, ProtocolError, canonical_json_bytes, strict_json_bytes, validate_relative_path


PILOT_SOURCE_SCHEMA = "keelaryn.pilot-source.v1"
PILOT_PACK_SCHEMA = "keelaryn.pilot-pack.v1"
PILOT_PACK_NAME = "PILOT_PACK.json"
PILOT_FILES_DIR = "files"
MAX_PILOT_FILES = 32
MAX_PILOT_FILE_BYTES = 16 * 1024 * 1024
MAX_PILOT_TOTAL_BYTES = 32 * 1024 * 1024


class PilotPackBlocked(ProtocolError):
    """A private real-Hub-subset pilot pack cannot be built or verified safely."""


@dataclass(frozen=True)
class PilotPackEntry:
    operation_id: str
    source: str
    target: str
    payload: str
    sha256: str
    size: int


@dataclass(frozen=True)
class PilotPack:
    root: Path
    pilot_id: str
    entries: tuple[PilotPackEntry, ...]
    manifest_raw: bytes

    @property
    def pack_sha256(self) -> str:
        return sha256(self.manifest_raw).hexdigest()

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.entries)

    def payload_bytes(self, entry: PilotPackEntry) -> bytes:
        path = self.root.joinpath(*entry.payload.split("/"))
        raw = _read_regular_file(path, label=f"pilot payload {entry.operation_id}", max_bytes=MAX_PILOT_FILE_BYTES)
        if len(raw) != entry.size or sha256(raw).hexdigest() != entry.sha256:
            raise PilotPackBlocked(f"pilot payload fingerprint mismatch: {entry.operation_id}")
        return raw

    def public_summary(self) -> dict[str, Any]:
        return {
            "schema": PILOT_PACK_SCHEMA,
            "pilot_id": self.pilot_id,
            "pack_sha256": self.pack_sha256,
            "file_count": len(self.entries),
            "total_bytes": self.total_bytes,
        }


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise PilotPackBlocked(f"{label}: keys mismatch missing={missing} extra={extra}")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise PilotPackBlocked(f"{label}: invalid identifier")
    return value


def _relative_path(value: Any, label: str) -> str:
    try:
        return validate_relative_path(value, label)
    except ProtocolError as exc:
        raise PilotPackBlocked(str(exc)) from exc


def _target_path(value: Any, label: str) -> str:
    target = _relative_path(value, label)
    if "/" in target:
        raise PilotPackBlocked(f"{label}: MVP pilot target must be a canonical-root file")
    return target


def _is_linklike(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
    except OSError as exc:
        raise PilotPackBlocked(f"cannot inspect path link state: {path}: {exc}") from exc
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if bool(isjunction(path)):
                return True
        except OSError as exc:
            raise PilotPackBlocked(f"cannot inspect path junction state: {path}: {exc}") from exc
    return False


def _require_real_directory(path: Path, label: str) -> Path:
    try:
        st = path.lstat()
    except OSError as exc:
        raise PilotPackBlocked(f"{label}: directory is unavailable: {exc}") from exc
    if stat.S_ISLNK(st.st_mode) or _is_linklike(path) or not stat.S_ISDIR(st.st_mode):
        raise PilotPackBlocked(f"{label}: expected a real directory")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise PilotPackBlocked(f"{label}: cannot resolve directory: {exc}") from exc


def _resolve_source(root: Path, relative: str) -> Path:
    current = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = current / part
        try:
            st = current.lstat()
        except OSError as exc:
            raise PilotPackBlocked(f"pilot source is unavailable: {relative}: {exc}") from exc
        if stat.S_ISLNK(st.st_mode) or _is_linklike(current):
            raise PilotPackBlocked(f"pilot source traverses a link/reparse point: {relative}")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(st.st_mode):
                raise PilotPackBlocked(f"pilot source parent is not a directory: {relative}")
        elif not stat.S_ISREG(st.st_mode):
            raise PilotPackBlocked(f"pilot source is not a regular file: {relative}")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PilotPackBlocked(f"pilot source escapes the source root: {relative}") from exc
    return resolved


def _read_regular_file(path: Path, *, label: str, max_bytes: int) -> bytes:
    if _is_linklike(path):
        raise PilotPackBlocked(f"{label}: symlink/reparse objects are forbidden")
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise PilotPackBlocked(f"{label}: cannot open file safely: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise PilotPackBlocked(f"{label}: expected regular file")
        if before.st_size > max_bytes:
            raise PilotPackBlocked(f"{label}: file exceeds pilot size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes:
            raise PilotPackBlocked(f"{label}: file exceeds pilot size limit")
        after = os.fstat(fd)
        stable = (
            before.st_dev == after.st_dev
            and before.st_ino == after.st_ino
            and before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
        )
        if not stable or len(raw) != after.st_size:
            raise PilotPackBlocked(f"{label}: file changed while being read")
    finally:
        os.close(fd)
    try:
        current = path.lstat()
    except OSError as exc:
        raise PilotPackBlocked(f"{label}: file disappeared after read: {exc}") from exc
    if stat.S_ISLNK(current.st_mode) or _is_linklike(path) or not stat.S_ISREG(current.st_mode):
        raise PilotPackBlocked(f"{label}: file identity changed after read")
    try:
        if not os.path.samestat(after, current):
            raise PilotPackBlocked(f"{label}: file identity changed after read")
    except OSError as exc:
        raise PilotPackBlocked(f"{label}: cannot revalidate file identity: {exc}") from exc
    return raw


def _write_new(path: Path, raw: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise PilotPackBlocked(f"cannot write pilot pack file {path.name}: {exc}") from exc


def _validate_source_manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = strict_json_bytes(raw, label="PILOT_SOURCE")
    except ProtocolError as exc:
        raise PilotPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise PilotPackBlocked("PILOT_SOURCE: must be object")
    _exact_keys(value, {"schema", "pilot_id", "entries"}, "PILOT_SOURCE")
    if value["schema"] != PILOT_SOURCE_SCHEMA:
        raise PilotPackBlocked("PILOT_SOURCE: unsupported schema")
    _identifier(value["pilot_id"], "PILOT_SOURCE.pilot_id")
    entries = value["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_PILOT_FILES:
        raise PilotPackBlocked(f"PILOT_SOURCE.entries: expected 1..{MAX_PILOT_FILES} entries")
    sources: set[str] = set()
    targets: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"PILOT_SOURCE.entries[{index}]"
        if not isinstance(entry, dict):
            raise PilotPackBlocked(f"{label}: must be object")
        _exact_keys(entry, {"source", "target"}, label)
        source = _relative_path(entry["source"], f"{label}.source")
        target = _target_path(entry["target"], f"{label}.target")
        if source in sources:
            raise PilotPackBlocked("PILOT_SOURCE: duplicate source")
        if target in targets:
            raise PilotPackBlocked("PILOT_SOURCE: duplicate target")
        sources.add(source)
        targets.add(target)
    return value


def _parse_pack_manifest(raw: bytes) -> tuple[str, tuple[PilotPackEntry, ...]]:
    try:
        value = strict_json_bytes(raw, label="PILOT_PACK")
    except ProtocolError as exc:
        raise PilotPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise PilotPackBlocked("PILOT_PACK: must be object")
    _exact_keys(value, {"schema", "pilot_id", "entries"}, "PILOT_PACK")
    if value["schema"] != PILOT_PACK_SCHEMA:
        raise PilotPackBlocked("PILOT_PACK: unsupported schema")
    pilot_id = _identifier(value["pilot_id"], "PILOT_PACK.pilot_id")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not 1 <= len(raw_entries) <= MAX_PILOT_FILES:
        raise PilotPackBlocked(f"PILOT_PACK.entries: expected 1..{MAX_PILOT_FILES} entries")
    entries: list[PilotPackEntry] = []
    operation_ids: set[str] = set()
    sources: set[str] = set()
    targets: set[str] = set()
    payloads: set[str] = set()
    total = 0
    for index, item in enumerate(raw_entries):
        label = f"PILOT_PACK.entries[{index}]"
        if not isinstance(item, dict):
            raise PilotPackBlocked(f"{label}: must be object")
        _exact_keys(item, {"operation_id", "source", "target", "payload", "sha256", "size"}, label)
        operation_id = _identifier(item["operation_id"], f"{label}.operation_id")
        source = _relative_path(item["source"], f"{label}.source")
        target = _target_path(item["target"], f"{label}.target")
        payload = _relative_path(item["payload"], f"{label}.payload")
        expected_payload = f"{PILOT_FILES_DIR}/{operation_id}.bin"
        if payload != expected_payload:
            raise PilotPackBlocked(f"{label}.payload: must equal {expected_payload}")
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise PilotPackBlocked(f"{label}.sha256: invalid SHA-256")
        size = item["size"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_PILOT_FILE_BYTES:
            raise PilotPackBlocked(f"{label}.size: invalid pilot file size")
        if operation_id in operation_ids or source in sources or target in targets or payload in payloads:
            raise PilotPackBlocked("PILOT_PACK: duplicate operation/source/target/payload identity")
        operation_ids.add(operation_id)
        sources.add(source)
        targets.add(target)
        payloads.add(payload)
        total += size
        if total > MAX_PILOT_TOTAL_BYTES:
            raise PilotPackBlocked("PILOT_PACK: total payload exceeds pilot scope limit")
        entries.append(PilotPackEntry(operation_id, source, target, payload, digest, size))
    return pilot_id, tuple(entries)


def build_pilot_pack(source_root: str | Path, source_manifest: str | Path, output_dir: str | Path) -> PilotPack:
    source_root_path = _require_real_directory(Path(source_root), "pilot source root")
    manifest_path = Path(source_manifest)
    manifest_raw = _read_regular_file(manifest_path, label="pilot source manifest", max_bytes=1024 * 1024)
    source = _validate_source_manifest(manifest_raw)

    output = Path(output_dir)
    parent = _require_real_directory(output.parent, "pilot pack output parent")
    output = parent / output.name
    if output.exists() or output.is_symlink():
        raise PilotPackBlocked("pilot pack output already exists")

    staging = parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    if staging.exists():
        raise PilotPackBlocked("pilot pack staging collision")
    try:
        staging.mkdir(mode=0o700)
        files_dir = staging / PILOT_FILES_DIR
        files_dir.mkdir(mode=0o700)
        pack_entries: list[dict[str, Any]] = []
        total = 0
        for index, item in enumerate(source["entries"], start=1):
            source_rel = item["source"]
            target = item["target"]
            source_path = _resolve_source(source_root_path, source_rel)
            raw = _read_regular_file(
                source_path,
                label=f"pilot source {source_rel}",
                max_bytes=MAX_PILOT_FILE_BYTES,
            )
            total += len(raw)
            if total > MAX_PILOT_TOTAL_BYTES:
                raise PilotPackBlocked("pilot source selection exceeds total pilot size limit")
            operation_id = f"import-{index:03d}"
            payload = f"{PILOT_FILES_DIR}/{operation_id}.bin"
            _write_new(files_dir / f"{operation_id}.bin", raw)
            pack_entries.append(
                {
                    "operation_id": operation_id,
                    "source": source_rel,
                    "target": target,
                    "payload": payload,
                    "sha256": sha256(raw).hexdigest(),
                    "size": len(raw),
                }
            )

        pack_raw = canonical_json_bytes(
            {
                "schema": PILOT_PACK_SCHEMA,
                "pilot_id": source["pilot_id"],
                "entries": pack_entries,
            }
        )
        _write_new(staging / PILOT_PACK_NAME, pack_raw)
        staging.rename(output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return verify_pilot_pack(output)


def verify_pilot_pack(pack_dir: str | Path) -> PilotPack:
    root = _require_real_directory(Path(pack_dir), "pilot pack root")
    root_names = {item.name for item in root.iterdir()}
    if root_names != {PILOT_PACK_NAME, PILOT_FILES_DIR}:
        raise PilotPackBlocked("pilot pack root contains missing or unexpected material")
    files_dir = _require_real_directory(root / PILOT_FILES_DIR, "pilot pack files directory")
    manifest_raw = _read_regular_file(root / PILOT_PACK_NAME, label="PILOT_PACK.json", max_bytes=1024 * 1024)
    pilot_id, entries = _parse_pack_manifest(manifest_raw)

    expected_names = {f"{entry.operation_id}.bin" for entry in entries}
    actual_names = {item.name for item in files_dir.iterdir()}
    if actual_names != expected_names:
        raise PilotPackBlocked("pilot pack files directory contains missing or unexpected material")
    for entry in entries:
        payload_path = files_dir / f"{entry.operation_id}.bin"
        raw = _read_regular_file(payload_path, label=f"pilot payload {entry.operation_id}", max_bytes=MAX_PILOT_FILE_BYTES)
        if len(raw) != entry.size or sha256(raw).hexdigest() != entry.sha256:
            raise PilotPackBlocked(f"pilot payload fingerprint mismatch: {entry.operation_id}")

    return PilotPack(root, pilot_id, entries, manifest_raw)


__all__ = [
    "MAX_PILOT_FILE_BYTES",
    "MAX_PILOT_FILES",
    "MAX_PILOT_TOTAL_BYTES",
    "PILOT_PACK_NAME",
    "PILOT_PACK_SCHEMA",
    "PILOT_SOURCE_SCHEMA",
    "PilotPack",
    "PilotPackBlocked",
    "PilotPackEntry",
    "build_pilot_pack",
    "verify_pilot_pack",
]
