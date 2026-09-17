from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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


class LiveMigrationDisposableRehearsalError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise LiveMigrationDisposableRehearsalError(
            f"missing required environment: {name}"
        )
    return value


def _private_pack_path() -> Path:
    value = Path(_required("KEELARYN_MIGRATION_PACK_DIR")).resolve()
    repo = REPO.resolve()
    if value == repo or repo in value.parents:
        raise LiveMigrationDisposableRehearsalError(
            "private migration pack must remain outside the Git worktree"
        )
    return value


def _same_pack(first, second) -> None:
    if (
        first.candidate_id != second.candidate_id
        or first.pack_sha256 != second.pack_sha256
        or first.manifest_raw != second.manifest_raw
    ):
        raise LiveMigrationDisposableRehearsalError(
            "private migration pack changed before disposable mutation"
        )


def main() -> int:
    phase = "preflight"
    try:
        if _required("KEELARYN_MIGRATION_DISPOSABLE_REHEARSAL_ENABLE") != "YES":
            raise LiveMigrationDisposableRehearsalError(
                "disposable migration rehearsal is not explicitly enabled"
            )

        run_id = _safe_run_id(_required("KEELARYN_MIGRATION_REHEARSAL_RUN_ID"))
        acceptance_root_id = _required("KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID")
        pack_dir = _private_pack_path()

        # Private bytes are verified before OAuth or any Drive observation/mutation.
        initial_pack = verify_migration_pack(pack_dir)

        phase = "oauth"
        token_provider = GoogleOAuthRefreshTokenProvider.from_environment()
        drive = GoogleDriveBackend(token_provider)

        phase = "acceptance-root-guard"
        verify_acceptance_root(drive, acceptance_root_id)

        child_name = f"{CHILD_PREFIX}Migration_{run_id}"
        existing = [
            item
            for item in drive.list_children(acceptance_root_id, name=child_name)
            if not item.trashed
        ]
        if existing:
            raise LiveMigrationDisposableRehearsalError(
                "disposable migration rehearsal run ID already has Drive material"
            )

        # Freshly bind the exact private pack again at the mutation boundary.
        boundary_pack = verify_migration_pack(pack_dir)
        _same_pack(initial_pack, boundary_pack)

        phase = "child-create"
        reserved_id = drive.generate_ids(1)[0]
        child = drive.create_folder(
            acceptance_root_id,
            child_name,
            file_id=reserved_id,
            label="migration disposable rehearsal Hub",
        )
        if child.file_id != reserved_id or child.name != child_name or not child.is_folder:
            raise LiveMigrationDisposableRehearsalError(
                "created disposable migration child identity is invalid"
            )

        phase = "migration-rehearsal"
        evidence = DriveMigrationDisposableRehearsal(
            drive,
            child.file_id,
        ).run(pack_dir)

        phase = "evidence"
        value = evidence.to_json_value()
        if value.get("schema") != "keelaryn.migration-rehearsal-evidence.v1":
            raise LiveMigrationDisposableRehearsalError(
                "migration rehearsal evidence schema is invalid"
            )
        if value.get("candidate_id") != initial_pack.candidate_id:
            raise LiveMigrationDisposableRehearsalError(
                "migration rehearsal candidate identity mismatch"
            )
        if value.get("pack_sha256") != initial_pack.pack_sha256:
            raise LiveMigrationDisposableRehearsalError(
                "migration rehearsal pack identity mismatch"
            )
        if value.get("outcome") != "PASS":
            raise LiveMigrationDisposableRehearsalError(
                "migration rehearsal did not reach PASS"
            )
        if value.get("canonical_epoch") != 1:
            raise LiveMigrationDisposableRehearsalError(
                "migration rehearsal did not finish at canonical epoch 1"
            )
        if value.get("no_op_phase") != "IDLE" or value.get("restart_state") != "READY_CLEAN":
            raise LiveMigrationDisposableRehearsalError(
                "migration rehearsal did not prove final IDLE/READY_CLEAN state"
            )

        public = {
            "schema": "keelaryn.migration-disposable-live-run.v1",
            "run_id": run_id,
            "rehearsal": value,
            "existing_hub_reused": False,
            "production_selector_mutated": False,
        }
        rendered = json.dumps(
            public,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        # Never expose raw Drive IDs or private filesystem paths in portable evidence.
        forbidden = (
            acceptance_root_id,
            child.file_id,
            str(pack_dir),
        )
        if any(secret and secret in rendered for secret in forbidden):
            raise LiveMigrationDisposableRehearsalError(
                "sanitized migration rehearsal output leaked private identity/path"
            )

        print(rendered, flush=True)
        return 0
    except Exception as exc:
        # Exception text can contain private source names, Drive IDs or paths.
        print(
            json.dumps(
                {
                    "schema": "keelaryn.migration-disposable-live-failure.v1",
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
