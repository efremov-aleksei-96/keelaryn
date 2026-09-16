from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "keelaryn.zero-vps-payload.v1"
PAYLOAD_ROOT = "keelaryn-zero"
SOURCE_NAME = f"{PAYLOAD_ROOT}/SOURCE_COMMIT"
MANIFEST_NAME = f"{PAYLOAD_ROOT}/PAYLOAD_MANIFEST.json"


class PayloadMaterializeError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedMember:
    path: str
    sha256: str
    size: int
    data: bytes


def _source_commit(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise PayloadMaterializeError("invalid source commit identity")
    return value


def _safe_manifest_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PayloadMaterializeError("manifest contains invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PayloadMaterializeError(f"manifest path is unsafe: {value}")
    normalized = path.as_posix()
    if normalized != value or normalized.startswith(PAYLOAD_ROOT + "/"):
        raise PayloadMaterializeError(f"manifest path is not canonical: {value}")
    return normalized


def _sha(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise PayloadMaterializeError("manifest contains invalid sha256")
    return value


def _size(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PayloadMaterializeError("manifest contains invalid size")
    return value


def _regular_members(raw: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for info in archive:
                name = info.name
                if name in members:
                    raise PayloadMaterializeError(f"duplicate archive member: {name}")
                if not info.isreg():
                    raise PayloadMaterializeError(f"non-regular archive member forbidden: {name}")
                path = PurePosixPath(name)
                if (
                    path.is_absolute()
                    or len(path.parts) < 2
                    or path.parts[0] != PAYLOAD_ROOT
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or path.as_posix() != name
                ):
                    raise PayloadMaterializeError(f"unsafe archive member path: {name}")
                stream = archive.extractfile(info)
                if stream is None:
                    raise PayloadMaterializeError(f"cannot read archive member: {name}")
                data = stream.read()
                if len(data) != info.size:
                    raise PayloadMaterializeError(f"archive member size mismatch: {name}")
                members[name] = data
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise PayloadMaterializeError("payload is not a valid gzip/tar archive") from exc
    return members


def verify_payload(raw: bytes, *, expected_source_commit: str | None = None) -> tuple[str, tuple[VerifiedMember, ...]]:
    if not isinstance(raw, bytes) or not raw:
        raise PayloadMaterializeError("payload bytes are empty")
    members = _regular_members(raw)
    if SOURCE_NAME not in members or MANIFEST_NAME not in members:
        raise PayloadMaterializeError("payload metadata members are missing")

    try:
        source_text = members[SOURCE_NAME].decode("ascii")
    except UnicodeDecodeError as exc:
        raise PayloadMaterializeError("SOURCE_COMMIT is not ASCII") from exc
    if not source_text.endswith("\n") or source_text.count("\n") != 1:
        raise PayloadMaterializeError("SOURCE_COMMIT has invalid framing")
    source_commit = _source_commit(source_text[:-1])
    if expected_source_commit is not None and source_commit != _source_commit(expected_source_commit):
        raise PayloadMaterializeError("payload source commit does not match expected identity")

    try:
        manifest = json.loads(members[MANIFEST_NAME].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadMaterializeError("PAYLOAD_MANIFEST.json is invalid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "source_commit", "files"}:
        raise PayloadMaterializeError("payload manifest has invalid root shape")
    if manifest["schema"] != SCHEMA or _source_commit(manifest["source_commit"]) != source_commit:
        raise PayloadMaterializeError("payload manifest identity does not match SOURCE_COMMIT")
    entries = manifest["files"]
    if not isinstance(entries, list) or not entries:
        raise PayloadMaterializeError("payload manifest files must be a non-empty array")

    verified: list[VerifiedMember] = []
    expected_archive_names = {SOURCE_NAME, MANIFEST_NAME}
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise PayloadMaterializeError(f"manifest file entry {index} has invalid shape")
        path = _safe_manifest_path(entry["path"])
        if path in seen_paths:
            raise PayloadMaterializeError(f"duplicate manifest path: {path}")
        seen_paths.add(path)
        digest = _sha(entry["sha256"])
        size = _size(entry["size"])
        archive_name = f"{PAYLOAD_ROOT}/{path}"
        expected_archive_names.add(archive_name)
        data = members.get(archive_name)
        if data is None:
            raise PayloadMaterializeError(f"manifest member missing from archive: {path}")
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise PayloadMaterializeError(f"payload member fingerprint mismatch: {path}")
        verified.append(VerifiedMember(path, digest, size, data))

    extras = set(members) - expected_archive_names
    if extras:
        raise PayloadMaterializeError("archive contains members not bound by manifest: " + ", ".join(sorted(extras)))
    return source_commit, tuple(verified)


def materialize_payload(payload: Path, releases_root: Path, *, expected_source_commit: str | None = None) -> dict[str, object]:
    payload = payload.resolve()
    releases_root = releases_root.resolve()
    try:
        raw = payload.read_bytes()
    except OSError as exc:
        raise PayloadMaterializeError("cannot read payload archive") from exc
    source_commit, members = verify_payload(raw, expected_source_commit=expected_source_commit)

    releases_root.mkdir(parents=True, exist_ok=True)
    destination = releases_root / source_commit
    if destination.exists() or destination.is_symlink():
        raise PayloadMaterializeError("release destination already exists; immutable releases are never overwritten")

    stage = Path(tempfile.mkdtemp(prefix=f".{source_commit}.stage-", dir=releases_root))
    try:
        for member in members:
            target = stage / PurePosixPath(member.path)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            with target.open("xb") as stream:
                stream.write(member.data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(target, 0o644)
        (stage / "SOURCE_COMMIT").write_text(source_commit + "\n", encoding="ascii", newline="\n")
        manifest_copy = {
            "schema": SCHEMA,
            "source_commit": source_commit,
            "files": [
                {"path": member.path, "sha256": member.sha256, "size": member.size}
                for member in members
            ],
        }
        manifest_path = stage / "PAYLOAD_MANIFEST.json"
        manifest_path.write_text(
            json.dumps(manifest_copy, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        # Re-read every staged payload member before publication.
        for member in members:
            target = stage / PurePosixPath(member.path)
            data = target.read_bytes()
            if len(data) != member.size or hashlib.sha256(data).hexdigest() != member.sha256:
                raise PayloadMaterializeError(f"staged release verification failed: {member.path}")

        os.replace(stage, destination)
        try:
            directory_fd = os.open(releases_root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise

    return {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "file_count": len(members),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "payload_size": len(raw),
        "release_directory": str(destination),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="materialize-zero-vps-payload")
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--releases-root", required=True, type=Path)
    parser.add_argument("--expected-source-commit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = materialize_payload(
            args.payload,
            args.releases_root,
            expected_source_commit=args.expected_source_commit,
        )
    except (PayloadMaterializeError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
