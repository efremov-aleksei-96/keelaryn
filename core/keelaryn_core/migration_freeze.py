from __future__ import annotations

import os
import re
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .migration_common import (
    MIGRATION_MAPPING_NAME,
    MIGRATION_SOURCE_NAME,
    MigrationPack,
    MigrationPackBlocked,
    atomic_write_new,
    keys_exact,
    real_directory,
    small_file,
    source_file,
)
from .migration_mapping import parse_mapping
from .migration_pack import verify_migration_pack
from .migration_source import parse_source
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes


MIGRATION_FREEZE_SCHEMA = "keelaryn.migration-candidate-freeze.v1"
MIGRATION_FREEZE_STATUS = "FROZEN_UNQUALIFIED"
GIT_OID_RE = re.compile(r"[0-9a-f]{40}")


class MigrationFreezePostCommitBlocked(MigrationPackBlocked):
    """Freeze receipt is durable, but fresh post-publication verification failed."""


FaultHook = Callable[[str], None]


def _fault(hook: FaultHook | None, point: str) -> None:
    if hook is not None:
        hook(point)


def _git_oid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not GIT_OID_RE.fullmatch(value):
        raise MigrationPackBlocked(f"{label}: expected exactly 40 lowercase hexadecimal characters")
    return value


def _git(repo: Path, *args: str) -> bytes:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MigrationPackBlocked("migration freeze cannot execute Git identity check") from exc
    if result.returncode != 0:
        raise MigrationPackBlocked("migration freeze Git identity check failed")
    return result.stdout


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _git_identity(
    repo_root: str | Path,
    *,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
) -> tuple[Path, str, str]:
    repo = real_directory(Path(repo_root), "migration freeze repository root")
    try:
        top = Path(os.fsdecode(_git(repo, "rev-parse", "--show-toplevel").strip())).resolve()
    except (OSError, UnicodeError) as exc:
        raise MigrationPackBlocked("migration freeze repository root is not a valid Git worktree") from exc
    if not _same_path(repo.resolve(), top):
        raise MigrationPackBlocked("migration freeze repository root must be the exact Git worktree root")

    try:
        commit = _git(repo, "rev-parse", "--verify", "HEAD").strip().decode("ascii")
        tree = _git(repo, "rev-parse", "--verify", "HEAD^{tree}").strip().decode("ascii")
    except UnicodeDecodeError as exc:
        raise MigrationPackBlocked("migration freeze Git identity is not ASCII") from exc
    commit = _git_oid(commit, "migration freeze source commit")
    tree = _git_oid(tree, "migration freeze source tree")
    if expected_commit is not None and commit != _git_oid(expected_commit, "expected source commit"):
        raise MigrationPackBlocked("migration freeze source commit mismatch")
    if expected_tree is not None and tree != _git_oid(expected_tree, "expected source tree"):
        raise MigrationPackBlocked("migration freeze source tree mismatch")

    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise MigrationPackBlocked("migration freeze requires an exact clean Git worktree")
    return repo, commit, tree


def _inventory_sha256(schema: str, entries: list[dict[str, Any]]) -> str:
    return sha256(canonical_json_bytes({"schema": schema, "entries": entries})).hexdigest()


def _receipt_value(pack: MigrationPack, source_commit: str, source_tree: str) -> dict[str, Any]:
    source_commit = _git_oid(source_commit, "migration freeze source commit")
    source_tree = _git_oid(source_tree, "migration freeze source tree")

    source_raw = small_file(
        pack.root / "authority" / MIGRATION_SOURCE_NAME,
        "frozen migration source authority",
    )
    source = parse_source(source_raw)
    mapping_raw = small_file(
        pack.root / "authority" / MIGRATION_MAPPING_NAME,
        "frozen migration mapping authority",
    )
    mapping = parse_mapping(mapping_raw, source)
    destinations = dict(mapping.preservation_destinations)

    canonical_inventory = [
        {
            "target": item.target,
            "sha256": item.sha256,
            "size": item.size,
        }
        for item in sorted(pack.canonical_outputs, key=lambda value: value.target)
    ]
    project_inventory = [
        {
            "project_id": item.project_id,
            "sha256": item.sha256,
            "size": item.size,
        }
        for item in sorted(pack.project_initial_states, key=lambda value: value.project_id)
    ]
    preservation_inventory = [
        {
            "classification": item.classification,
            "destination": destinations[item.source],
            "sha256": item.sha256,
            "size": item.size,
        }
        for item in sorted(
            pack.preserved_outputs,
            key=lambda value: (destinations[value.source], value.classification, value.source),
        )
    ]

    if pack.root_index_size >= 0:
        root_index_raw = source_file(pack.root / "root", "INDEX.md", "frozen migration root INDEX")
        root_index_sha256: str | None = sha256(root_index_raw).hexdigest()
    else:
        root_index_sha256 = None

    return {
        "schema": MIGRATION_FREEZE_SCHEMA,
        "status": MIGRATION_FREEZE_STATUS,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "candidate_id": pack.candidate_id,
        "pack_sha256": pack.pack_sha256,
        "source_manifest_sha256": pack.source_manifest_sha256,
        "mapping_manifest_sha256": pack.mapping_manifest_sha256,
        "canonical_inventory_sha256": _inventory_sha256(
            "keelaryn.migration-freeze-canonical-inventory.v1",
            canonical_inventory,
        ),
        "project_state_inventory_sha256": _inventory_sha256(
            "keelaryn.migration-freeze-project-state-inventory.v1",
            project_inventory,
        ),
        "preservation_inventory_sha256": _inventory_sha256(
            "keelaryn.migration-freeze-preservation-inventory.v1",
            preservation_inventory,
        ),
        "root_index_sha256": root_index_sha256,
        "source_file_count": pack.source_file_count,
        "source_total_bytes": pack.source_total_bytes,
        "canonical_file_count": len(pack.canonical_outputs),
        "canonical_total_bytes": pack.canonical_total_bytes,
        "project_state_count": len(pack.project_initial_states),
        "project_state_total_bytes": pack.project_state_total_bytes,
        "preserved_file_count": len(pack.preserved_outputs),
        "preserved_total_bytes": pack.preserved_total_bytes,
        "has_root_index": pack.root_index_size >= 0,
    }


def _strict_receipt(raw: bytes) -> dict[str, Any]:
    try:
        value = strict_json_bytes(raw, label="MIGRATION_CANDIDATE_FREEZE")
    except ProtocolError as exc:
        raise MigrationPackBlocked(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationPackBlocked("MIGRATION_CANDIDATE_FREEZE: must be object")
    keys_exact(
        value,
        {
            "schema",
            "status",
            "source_commit",
            "source_tree",
            "candidate_id",
            "pack_sha256",
            "source_manifest_sha256",
            "mapping_manifest_sha256",
            "canonical_inventory_sha256",
            "project_state_inventory_sha256",
            "preservation_inventory_sha256",
            "root_index_sha256",
            "source_file_count",
            "source_total_bytes",
            "canonical_file_count",
            "canonical_total_bytes",
            "project_state_count",
            "project_state_total_bytes",
            "preserved_file_count",
            "preserved_total_bytes",
            "has_root_index",
        },
        "MIGRATION_CANDIDATE_FREEZE",
    )
    if value["schema"] != MIGRATION_FREEZE_SCHEMA or value["status"] != MIGRATION_FREEZE_STATUS:
        raise MigrationPackBlocked("MIGRATION_CANDIDATE_FREEZE: schema/status mismatch")
    _git_oid(value["source_commit"], "MIGRATION_CANDIDATE_FREEZE.source_commit")
    _git_oid(value["source_tree"], "MIGRATION_CANDIDATE_FREEZE.source_tree")
    return value


def _outside_authorities(output: Path, repo: Path, pack_root: Path) -> None:
    candidate = output.absolute().resolve(strict=False)
    repo_resolved = repo.resolve()
    pack_resolved = pack_root.resolve()
    if candidate == repo_resolved or repo_resolved in candidate.parents:
        raise MigrationPackBlocked("migration freeze receipt must remain outside the Git worktree")
    if candidate == pack_resolved or pack_resolved in candidate.parents:
        raise MigrationPackBlocked("migration freeze receipt must remain outside the immutable migration pack")


def verify_migration_candidate_freeze(
    pack_dir: str | Path,
    receipt_path: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    raw = small_file(Path(receipt_path), "migration candidate freeze receipt")
    receipt = _strict_receipt(raw)
    repo, commit, tree = _git_identity(
        repo_root,
        expected_commit=receipt["source_commit"],
        expected_tree=receipt["source_tree"],
    )
    pack = verify_migration_pack(pack_dir)
    _outside_authorities(Path(receipt_path), repo, pack.root)
    expected = _receipt_value(pack, commit, tree)
    if raw != canonical_json_bytes(expected):
        raise MigrationPackBlocked("migration candidate freeze receipt no longer matches exact source/pack identity")
    return expected


def freeze_migration_candidate(
    pack_dir: str | Path,
    repo_root: str | Path,
    expected_source_commit: str,
    expected_source_tree: str,
    output_receipt: str | Path,
    *,
    fault_hook: FaultHook | None = None,
) -> dict[str, Any]:
    pack = verify_migration_pack(pack_dir)
    repo, commit, tree = _git_identity(
        repo_root,
        expected_commit=expected_source_commit,
        expected_tree=expected_source_tree,
    )
    output = Path(output_receipt).absolute()
    _outside_authorities(output, repo, pack.root)
    expected = _receipt_value(pack, commit, tree)
    raw = canonical_json_bytes(expected)

    if output.exists() or output.is_symlink():
        existing = small_file(output, "migration candidate freeze receipt")
        if existing != raw:
            raise MigrationPackBlocked("migration candidate freeze receipt already exists with different identity")
    else:
        fresh_pack = verify_migration_pack(pack_dir)
        _, fresh_commit, fresh_tree = _git_identity(
            repo,
            expected_commit=commit,
            expected_tree=tree,
        )
        if canonical_json_bytes(_receipt_value(fresh_pack, fresh_commit, fresh_tree)) != raw:
            raise MigrationPackBlocked("migration candidate identity changed before freeze commit")
        atomic_write_new(output, raw)
        _fault(fault_hook, "freeze.after_receipt_publish")

    try:
        final_pack = verify_migration_pack(pack_dir)
        _, final_commit, final_tree = _git_identity(
            repo,
            expected_commit=commit,
            expected_tree=tree,
        )
        if canonical_json_bytes(_receipt_value(final_pack, final_commit, final_tree)) != raw:
            raise MigrationPackBlocked("post-freeze source/pack identity mismatch")
    except MigrationPackBlocked as exc:
        raise MigrationFreezePostCommitBlocked(
            "migration freeze receipt is durably published, but post-commit verification failed"
        ) from exc
    return expected


__all__ = [
    "MIGRATION_FREEZE_SCHEMA",
    "MIGRATION_FREEZE_STATUS",
    "MigrationFreezePostCommitBlocked",
    "freeze_migration_candidate",
    "verify_migration_candidate_freeze",
]
