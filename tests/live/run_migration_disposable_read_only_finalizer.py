from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(LIVE))

from drive_disposable_acceptance import (  # noqa: E402
    CHILD_PREFIX,
    _safe_run_id,
    verify_acceptance_root,
)
from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider  # noqa: E402
from keelaryn_core.drive_rest import GoogleDriveBackend  # noqa: E402
from keelaryn_core.migration_pack import verify_migration_pack  # noqa: E402
from keelaryn_core.migration_rehearsal import DriveMigrationDisposableRehearsal  # noqa: E402
from keelaryn_core.protocol import ProtocolError  # noqa: E402


SCHEMA = "keelaryn.migration-disposable-read-only-finalization.v1"
CLOSURE_SCHEMA = "keelaryn.migration-disposable-construction-closure.v1"
MUTATION_CLOSURE_PATHS = (
    "tests/live/run_migration_disposable_rehearsal.py",
    "tests/live/drive_disposable_acceptance.py",
    "core/keelaryn_core/drive_backend.py",
    "core/keelaryn_core/drive_bootstrap.py",
    "core/keelaryn_core/drive_bundle.py",
    "core/keelaryn_core/drive_change.py",
    "core/keelaryn_core/drive_claim.py",
    "core/keelaryn_core/drive_consumption.py",
    "core/keelaryn_core/drive_control.py",
    "core/keelaryn_core/drive_core.py",
    "core/keelaryn_core/drive_discovery.py",
    "core/keelaryn_core/drive_execution_rollback.py",
    "core/keelaryn_core/drive_factory.py",
    "core/keelaryn_core/drive_ingestion.py",
    "core/keelaryn_core/drive_master.py",
    "core/keelaryn_core/drive_oauth.py",
    "core/keelaryn_core/drive_postcheck.py",
    "core/keelaryn_core/drive_project.py",
    "core/keelaryn_core/drive_reader.py",
    "core/keelaryn_core/drive_recovery_block.py",
    "core/keelaryn_core/drive_rest.py",
    "core/keelaryn_core/drive_runtime.py",
    "core/keelaryn_core/drive_service.py",
    "core/keelaryn_core/drive_snapshot.py",
    "core/keelaryn_core/drive_transaction.py",
    "core/keelaryn_core/drive_workflow.py",
    "core/keelaryn_core/engine.py",
    "core/keelaryn_core/engine_abort.py",
    "core/keelaryn_core/engine_finalize.py",
    "core/keelaryn_core/engine_mutate.py",
    "core/keelaryn_core/engine_prepare.py",
    "core/keelaryn_core/migration_common.py",
    "core/keelaryn_core/migration_drive.py",
    "core/keelaryn_core/migration_inventory.py",
    "core/keelaryn_core/migration_mapping.py",
    "core/keelaryn_core/migration_materialization.py",
    "core/keelaryn_core/migration_pack.py",
    "core/keelaryn_core/migration_publication.py",
    "core/keelaryn_core/migration_rehearsal.py",
    "core/keelaryn_core/migration_router.py",
    "core/keelaryn_core/migration_source.py",
    "core/keelaryn_core/project_state.py",
    "core/keelaryn_core/protocol.py",
    "core/keelaryn_core/reconciliation_state.py",
    "core/keelaryn_core/storage.py",
    "core/keelaryn_core/work_state.py",
    "core/keelaryn_core/work_state_protocol.py",
    "core/keelaryn_core/workflow_protocol.py",
    "core/keelaryn_core/workspace.py",
)


class LiveMigrationDisposableReadOnlyFinalizationError(RuntimeError):
    pass


class ReadOnlyDriveMutationBlocked(ProtocolError):
    pass


class ReadOnlyDriveProxy:
    """DriveBackend guard that permits observation only.

    Any mutation-capable call fails before reaching the wrapped backend. This lets
    the exact ordinary rehearsal acceptance logic be replayed against a durable
    completed child without trusting idempotence as a substitute for read-only
    enforcement.
    """

    def __init__(self, drive):
        self._drive = drive
        self.mutation_attempt_count = 0

    def _blocked(self, operation: str):
        self.mutation_attempt_count += 1
        raise ReadOnlyDriveMutationBlocked(
            f"read-only finalizer blocked mutation-capable Drive operation: {operation}"
        )

    def generate_ids(self, count: int):
        return self._blocked("generate_ids")

    def create_folder(self, *args, **kwargs):
        return self._blocked("create_folder")

    def create_blob(self, *args, **kwargs):
        return self._blocked("create_blob")

    def copy_blob(self, *args, **kwargs):
        return self._blocked("copy_blob")

    def move_rename(self, *args, **kwargs):
        return self._blocked("move_rename")

    def replace_blob_content(self, *args, **kwargs):
        return self._blocked("replace_blob_content")

    def update_content(self, *args, **kwargs):
        return self._blocked("update_content")

    def trash(self, *args, **kwargs):
        return self._blocked("trash")

    def delete(self, *args, **kwargs):
        return self._blocked("delete")

    def get(self, file_id: str, *, include_trashed: bool = True):
        return self._drive.get(file_id, include_trashed=include_trashed)

    def list_children(
        self,
        parent_id: str,
        *,
        name: str | None = None,
        include_trashed: bool = False,
    ):
        return self._drive.list_children(
            parent_id,
            name=name,
            include_trashed=include_trashed,
        )

    def download(self, file_id: str) -> bytes:
        return self._drive.download(file_id)

    def exact_name(self, parent_id: str, name: str):
        return self._drive.exact_name(parent_id, name)


def _emit_progress(
    phase: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    value: dict[str, Any] = {
        "schema": "keelaryn.migration-disposable-read-only-progress.v1",
        "phase": phase,
    }
    if current is not None or total is not None:
        if (
            not isinstance(current, int)
            or isinstance(current, bool)
            or not isinstance(total, int)
            or isinstance(total, bool)
            or current < 1
            or total < 1
            or current > total
        ):
            raise LiveMigrationDisposableReadOnlyFinalizationError(
                "read-only finalization progress counters are invalid"
            )
        value["current"] = current
        value["total"] = total
    print(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            f"missing required environment: {name}"
        )
    return value


def _commit(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            f"{label} must be exactly 40 lowercase hexadecimal characters"
        )
    return value


def _private_pack_path() -> Path:
    value = Path(_required("KEELARYN_MIGRATION_PACK_DIR")).resolve()
    repo = REPO.resolve()
    if value == repo or repo in value.parents:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "private migration pack must remain outside the Git worktree"
        )
    return value


def _same_pack(first, second) -> None:
    if (
        first.candidate_id != second.candidate_id
        or first.pack_sha256 != second.pack_sha256
        or first.manifest_raw != second.manifest_raw
    ):
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "private migration pack changed during read-only finalization"
        )


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "Git provenance query failed"
        )
    return result.stdout.strip()


def _blob_oid(commit: str, path: str) -> str:
    oid = _git("rev-parse", f"{commit}:{path}")
    if (
        len(oid) not in {40, 64}
        or any(ch not in "0123456789abcdef" for ch in oid)
    ):
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "mutation closure Git blob identity is invalid"
        )
    return oid


def _verify_git_provenance() -> dict[str, Any]:
    expected_current = _commit(
        _required("KEELARYN_SOURCE_COMMIT"),
        "current source commit",
    )
    construction = _commit(
        _required("KEELARYN_MIGRATION_REHEARSAL_CONSTRUCTION_SOURCE_COMMIT"),
        "rehearsal construction source commit",
    )
    current = _commit(_git("rev-parse", "HEAD"), "observed Git HEAD")
    if current != expected_current:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "current Git HEAD does not match requested source commit"
        )
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "read-only finalization requires a clean Git worktree"
        )
    _git("cat-file", "-e", f"{construction}^{{commit}}")

    entries: list[dict[str, str]] = []
    for path in MUTATION_CLOSURE_PATHS:
        construction_blob = _blob_oid(construction, path)
        current_blob = _blob_oid(current, path)
        if construction_blob != current_blob:
            raise LiveMigrationDisposableReadOnlyFinalizationError(
                "mutation-bearing rehearsal closure changed since construction"
            )
        entries.append({"path": path, "blob_oid": current_blob})

    raw = (
        json.dumps(
            {
                "schema": CLOSURE_SCHEMA,
                "construction_source_commit": construction,
                "current_source_commit": current,
                "entries": entries,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return {
        "construction_source_commit": construction,
        "current_source_commit": current,
        "mutation_closure_file_count": len(entries),
        "mutation_closure_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _validate_evidence(value: dict[str, Any], pack) -> None:
    if value.get("schema") != "keelaryn.migration-rehearsal-evidence.v1":
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "migration rehearsal evidence schema is invalid"
        )
    if value.get("candidate_id") != pack.candidate_id:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "migration rehearsal candidate identity mismatch"
        )
    if value.get("pack_sha256") != pack.pack_sha256:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "migration rehearsal pack identity mismatch"
        )
    if value.get("outcome") != "PASS" or value.get("canonical_epoch") != 1:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "read-only rehearsal finalization did not prove PASS at canonical epoch 1"
        )
    if value.get("reader_epoch") != 1:
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "read-only rehearsal finalization did not prove reader epoch 1"
        )
    if value.get("no_op_phase") != "IDLE" or value.get("restart_state") != "READY_CLEAN":
        raise LiveMigrationDisposableReadOnlyFinalizationError(
            "read-only rehearsal finalization did not prove IDLE/READY_CLEAN"
        )


def main() -> int:
    phase = "preflight"
    try:
        if (
            _required("KEELARYN_MIGRATION_DISPOSABLE_READ_ONLY_FINALIZE_ENABLE")
            != "YES"
        ):
            raise LiveMigrationDisposableReadOnlyFinalizationError(
                "disposable read-only finalization is not explicitly enabled"
            )
        run_id = _safe_run_id(_required("KEELARYN_MIGRATION_REHEARSAL_RUN_ID"))
        acceptance_root_id = _required("KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID")
        pack_dir = _private_pack_path()

        phase = "git-provenance"
        provenance = _verify_git_provenance()

        phase = "pack"
        initial_pack = verify_migration_pack(pack_dir)

        phase = "oauth"
        token_provider = GoogleOAuthRefreshTokenProvider.from_environment()
        live_drive = GoogleDriveBackend(token_provider)
        drive = ReadOnlyDriveProxy(live_drive)

        phase = "acceptance-root-guard"
        verify_acceptance_root(drive, acceptance_root_id)
        child_name = f"{CHILD_PREFIX}Migration_{run_id}"
        existing = [
            item
            for item in drive.list_children(acceptance_root_id, name=child_name)
            if not item.trashed
        ]
        if len(existing) != 1:
            raise LiveMigrationDisposableReadOnlyFinalizationError(
                "read-only finalization requires exactly one existing rehearsal child"
            )
        child = existing[0]
        if not child.is_folder or child.name != child_name:
            raise LiveMigrationDisposableReadOnlyFinalizationError(
                "existing rehearsal child identity is invalid"
            )

        phase = "read-only-replay"
        evidence = DriveMigrationDisposableRehearsal(
            drive,
            child.file_id,
            progress=_emit_progress,
        ).run(pack_dir)
        if drive.mutation_attempt_count != 0:
            raise LiveMigrationDisposableReadOnlyFinalizationError(
                "read-only finalization observed a mutation-capable Drive call"
            )

        phase = "evidence"
        final_pack = verify_migration_pack(pack_dir)
        _same_pack(initial_pack, final_pack)
        value = evidence.to_json_value()
        _validate_evidence(value, final_pack)

        public = {
            "schema": SCHEMA,
            "run_id": run_id,
            **provenance,
            "rehearsal": value,
            "existing_hub_reused": True,
            "read_only_guard_enforced": True,
            "drive_mutations_performed": False,
            "production_selector_mutated": False,
        }
        rendered = json.dumps(
            public,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        forbidden = (
            acceptance_root_id,
            child.file_id,
            str(pack_dir),
        )
        if any(secret and secret in rendered for secret in forbidden):
            raise LiveMigrationDisposableReadOnlyFinalizationError(
                "sanitized finalization output leaked private identity/path"
            )
        print(rendered, flush=True)
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.migration-disposable-read-only-finalization-failure.v1",
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
