from __future__ import annotations

import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.migration_common import (  # noqa: E402
    MigrationPackBlocked,
    small_file,
)
from keelaryn_core.migration_freeze import (  # noqa: E402
    MIGRATION_FREEZE_STATUS,
    MigrationFreezePostCommitBlocked,
    _git_identity,
    freeze_migration_candidate,
    verify_migration_candidate_freeze,
)
from keelaryn_core.migration_pack import verify_migration_pack  # noqa: E402
from keelaryn_core.protocol import ProtocolError, strict_json_bytes  # noqa: E402


SCHEMA = "keelaryn.migration-candidate-freeze-live.v1"
FAILURE_SCHEMA = "keelaryn.migration-candidate-freeze-live-failure.v1"
READ_ONLY_REHEARSAL_SCHEMA = "keelaryn.migration-disposable-read-only-finalization.v2"
REHEARSAL_SCHEMA = "keelaryn.migration-rehearsal-evidence.v1"


class LiveMigrationCandidateFreezeError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise LiveMigrationCandidateFreezeError(
            f"missing required environment: {name}"
        )
    return value


def _commit(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise LiveMigrationCandidateFreezeError(
            f"{label} must be exactly 40 lowercase hexadecimal characters"
        )
    return value


def _digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise LiveMigrationCandidateFreezeError(f"{label} must be exact SHA-256")
    return value


def _path(name: str) -> Path:
    return Path(_required(name)).absolute()


def _outside_repo_and_pack(path: Path, pack_root: Path, label: str) -> None:
    resolved = path.resolve(strict=False)
    repo = REPO.resolve()
    pack = pack_root.resolve()
    if resolved == repo or repo in resolved.parents:
        raise LiveMigrationCandidateFreezeError(
            f"{label} must remain outside the Git worktree"
        )
    if resolved == pack or pack in resolved.parents:
        raise LiveMigrationCandidateFreezeError(
            f"{label} must remain outside the immutable migration pack"
        )


def _strict_rehearsal_evidence(
    raw: bytes,
    *,
    expected_source_commit: str,
    candidate_id: str,
    pack_sha256: str,
) -> dict[str, Any]:
    try:
        value = strict_json_bytes(
            raw,
            label="MIGRATION_DISPOSABLE_READ_ONLY_FINALIZATION",
        )
    except ProtocolError as exc:
        raise LiveMigrationCandidateFreezeError(str(exc)) from exc
    expected = {
        "schema",
        "run_id",
        "mutation_source_commit",
        "current_source_commit",
        "mutation_closure_file_count",
        "mutation_closure_sha256",
        "rehearsal",
        "existing_hub_reused",
        "read_only_guard_enforced",
        "drive_mutations_performed",
        "production_selector_mutated",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal evidence has invalid root keys"
        )
    if value["schema"] != READ_ONLY_REHEARSAL_SCHEMA:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal evidence schema mismatch"
        )
    _commit(
        value["mutation_source_commit"],
        "read-only rehearsal mutation source commit",
    )
    current = _commit(
        value["current_source_commit"],
        "read-only rehearsal current source commit",
    )
    if current != expected_source_commit:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal evidence source commit does not match freeze source"
        )
    count = value["mutation_closure_file_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal mutation closure count is invalid"
        )
    _digest(
        value["mutation_closure_sha256"],
        "read-only rehearsal mutation closure SHA-256",
    )
    if (
        value["existing_hub_reused"] is not True
        or value["read_only_guard_enforced"] is not True
        or value["drive_mutations_performed"] is not False
        or value["production_selector_mutated"] is not False
    ):
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal evidence does not prove no-mutation finalization"
        )

    rehearsal = value["rehearsal"]
    rehearsal_keys = {
        "schema",
        "candidate_id",
        "pack_sha256",
        "canonical_epoch",
        "canonical_file_count",
        "canonical_total_bytes",
        "canonical_inventory_sha256",
        "preserved_file_count",
        "preserved_total_bytes",
        "preservation_inventory_sha256",
        "project_count",
        "reconciliation_state_sha256",
        "router_outcome",
        "root_index_sha256",
        "reader_epoch",
        "no_op_phase",
        "restart_state",
        "outcome",
    }
    if not isinstance(rehearsal, dict) or set(rehearsal) != rehearsal_keys:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal nested evidence has invalid keys"
        )
    if rehearsal["schema"] != REHEARSAL_SCHEMA:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal nested evidence schema mismatch"
        )
    if rehearsal["candidate_id"] != candidate_id:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal candidate does not match private pack"
        )
    if rehearsal["pack_sha256"] != pack_sha256:
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal pack does not match private pack"
        )
    if (
        rehearsal["outcome"] != "PASS"
        or rehearsal["canonical_epoch"] != 1
        or rehearsal["reader_epoch"] != 1
        or rehearsal["no_op_phase"] != "IDLE"
        or rehearsal["restart_state"] != "READY_CLEAN"
    ):
        raise LiveMigrationCandidateFreezeError(
            "read-only rehearsal evidence is not exact terminal PASS"
        )
    return value


def _public_freeze(
    freeze: dict[str, Any],
    *,
    freeze_receipt_sha256: str,
    rehearsal_evidence_sha256: str,
) -> dict[str, Any]:
    if freeze.get("status") != MIGRATION_FREEZE_STATUS:
        raise LiveMigrationCandidateFreezeError(
            "candidate freeze did not reach FROZEN_UNQUALIFIED"
        )
    return {
        "schema": SCHEMA,
        "status": freeze["status"],
        "source_commit": freeze["source_commit"],
        "source_tree": freeze["source_tree"],
        "candidate_id": freeze["candidate_id"],
        "pack_sha256": freeze["pack_sha256"],
        "freeze_receipt_sha256": freeze_receipt_sha256,
        "rehearsal_evidence_sha256": rehearsal_evidence_sha256,
        "durable_receipt_published": True,
        "production_selector_mutated": False,
        "cutover_authorized": False,
    }


def main() -> int:
    phase = "preflight"
    durable_receipt_published = False
    try:
        if _required("KEELARYN_MIGRATION_CANDIDATE_FREEZE_ENABLE") != "YES":
            raise LiveMigrationCandidateFreezeError(
                "migration candidate freeze is not explicitly enabled"
            )

        pack_dir = _path("KEELARYN_MIGRATION_PACK_DIR")
        receipt_path = _path("KEELARYN_MIGRATION_FREEZE_RECEIPT")
        rehearsal_path = _path("KEELARYN_MIGRATION_REHEARSAL_EVIDENCE")
        source_commit = _commit(
            _required("KEELARYN_SOURCE_COMMIT"),
            "requested source commit",
        )

        phase = "source-identity"
        repo, observed_commit, source_tree = _git_identity(
            REPO,
            expected_commit=source_commit,
        )
        if observed_commit != source_commit:
            raise LiveMigrationCandidateFreezeError(
                "observed Git HEAD does not match requested source commit"
            )

        phase = "pack"
        pack = verify_migration_pack(pack_dir)

        phase = "rehearsal-evidence"
        _outside_repo_and_pack(
            rehearsal_path,
            pack.root,
            "read-only rehearsal evidence",
        )
        rehearsal_raw = small_file(
            rehearsal_path,
            "read-only disposable rehearsal evidence",
        )
        rehearsal = _strict_rehearsal_evidence(
            rehearsal_raw,
            expected_source_commit=source_commit,
            candidate_id=pack.candidate_id,
            pack_sha256=pack.pack_sha256,
        )
        rehearsal_sha256 = sha256(rehearsal_raw).hexdigest()

        phase = "freeze"
        freeze = freeze_migration_candidate(
            pack.root,
            repo,
            source_commit,
            source_tree,
            receipt_path,
        )
        durable_receipt_published = True

        phase = "post-freeze-verify"
        verified = verify_migration_candidate_freeze(
            pack.root,
            receipt_path,
            repo,
        )
        if verified != freeze:
            raise LiveMigrationCandidateFreezeError(
                "post-freeze verification changed candidate identity"
            )
        receipt_raw = small_file(
            receipt_path,
            "migration candidate freeze receipt",
        )
        receipt_sha256 = sha256(receipt_raw).hexdigest()

        phase = "evidence"
        public = _public_freeze(
            verified,
            freeze_receipt_sha256=receipt_sha256,
            rehearsal_evidence_sha256=rehearsal_sha256,
        )
        rendered = json.dumps(
            public,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        forbidden = (
            str(pack_dir),
            str(receipt_path),
            str(rehearsal_path),
            str(repo),
            rehearsal.get("run_id", ""),
        )
        if any(secret and secret in rendered for secret in forbidden):
            raise LiveMigrationCandidateFreezeError(
                "sanitized candidate freeze evidence leaked private/local identity"
            )
        print(rendered, flush=True)
        return 0
    except MigrationFreezePostCommitBlocked as exc:
        durable_receipt_published = True
        print(
            json.dumps(
                {
                    "schema": FAILURE_SCHEMA,
                    "phase": "freeze-post-commit",
                    "error_class": type(exc).__name__,
                    "durable_receipt_published": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": FAILURE_SCHEMA,
                    "phase": phase,
                    "error_class": type(exc).__name__,
                    "durable_receipt_published": durable_receipt_published,
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
