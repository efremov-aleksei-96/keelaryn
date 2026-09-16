from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA = "keelaryn.zero-vps-payload.v1"
PAYLOAD_ROOT = "keelaryn-zero"
INCLUDED_ROOTS = (
    "core/keelaryn_core",
    "tests/core",
    "tests/live",
    "deploy/zero-based-vps",
)
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".tar.gz")
EXCLUDED_DIR_NAMES = {"__pycache__", ".git"}


class PayloadBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class PayloadFile:
    path: str
    sha256: str
    size: int
    data: bytes


def _source_commit(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise PayloadBuildError("source commit must be exactly 40 lowercase hexadecimal characters")
    return value


def _safe_regular_file(path: Path, repo_root: Path) -> PayloadFile:
    try:
        relative = path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise PayloadBuildError("payload file escapes repository root") from exc
    if path.is_symlink():
        raise PayloadBuildError(f"symlinks are forbidden in VPS payload: {relative}")
    try:
        info = path.stat()
    except OSError as exc:
        raise PayloadBuildError(f"cannot stat payload file: {relative}") from exc
    if not path.is_file():
        raise PayloadBuildError(f"payload member is not a regular file: {relative}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PayloadBuildError(f"cannot read payload file: {relative}") from exc
    return PayloadFile(relative, hashlib.sha256(data).hexdigest(), len(data), data)


def collect_files(repo_root: Path) -> tuple[PayloadFile, ...]:
    repo_root = repo_root.resolve()
    files: list[PayloadFile] = []
    seen: set[str] = set()
    for root_name in INCLUDED_ROOTS:
        root = repo_root / root_name
        if not root.is_dir() or root.is_symlink():
            raise PayloadBuildError(f"required payload root is missing/not a real directory: {root_name}")
        for current, dirs, names in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(
                name
                for name in dirs
                if name not in EXCLUDED_DIR_NAMES and not (current_path / name).is_symlink()
            )
            for name in sorted(names):
                candidate = current_path / name
                if name.endswith(EXCLUDED_SUFFIXES):
                    continue
                member = _safe_regular_file(candidate, repo_root)
                if member.path in seen:
                    raise PayloadBuildError(f"duplicate payload path: {member.path}")
                seen.add(member.path)
                files.append(member)
    files.sort(key=lambda item: item.path)
    if not files:
        raise PayloadBuildError("VPS payload would be empty")
    return tuple(files)


def manifest_bytes(source_commit: str, files: Iterable[PayloadFile]) -> bytes:
    source_commit = _source_commit(source_commit)
    value = {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "files": [
            {"path": item.path, "sha256": item.sha256, "size": item.size}
            for item in files
        ],
    }
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _tar_info(name: str, size: int, *, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = mode
    return info


def build_payload(repo_root: Path, source_commit: str, output: Path) -> dict[str, object]:
    source_commit = _source_commit(source_commit)
    repo_root = repo_root.resolve()
    files = collect_files(repo_root)
    manifest = manifest_bytes(source_commit, files)
    source_raw = (source_commit + "\n").encode("ascii")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    try:
        temp.unlink(missing_ok=True)
        with temp.open("wb") as raw_out:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0, compresslevel=9) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for item in files:
                        name = f"{PAYLOAD_ROOT}/{item.path}"
                        archive.addfile(_tar_info(name, item.size), io.BytesIO(item.data))
                    archive.addfile(
                        _tar_info(f"{PAYLOAD_ROOT}/SOURCE_COMMIT", len(source_raw)),
                        io.BytesIO(source_raw),
                    )
                    archive.addfile(
                        _tar_info(f"{PAYLOAD_ROOT}/PAYLOAD_MANIFEST.json", len(manifest)),
                        io.BytesIO(manifest),
                    )
            raw_out.flush()
            os.fsync(raw_out.fileno())
        os.replace(temp, output)
        try:
            directory_fd = os.open(output.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Some filesystems do not support directory fsync. The archive bytes
            # remain complete and atomically renamed; callers still verify SHA-256.
            pass
    finally:
        temp.unlink(missing_ok=True)

    raw = output.read_bytes()
    return {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "file_count": len(files),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "payload_size": len(raw),
        "output": str(output),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build-zero-vps-payload")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_payload(args.repo_root, args.source_commit, args.output)
    except (PayloadBuildError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
