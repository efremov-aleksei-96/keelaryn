from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_backend import DriveBackend, DriveNotFound
from keelaryn_core.drive_bootstrap import DriveHubBootstrap
from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider
from keelaryn_core.drive_rest import GoogleDriveBackend
from keelaryn_core.drive_service import DrivePollingService
from keelaryn_core.protocol import ProtocolError, canonical_json_bytes


ACCEPTANCE_ROOT_NAME = "Keelaryn__DISPOSABLE_LIVE_ACCEPTANCE_ROOT"
SENTINEL_NAME = "README.md"
SENTINEL_BYTES = (
    b"KEELARYN DISPOSABLE LIVE ACCEPTANCE ROOT\n"
    b"DO NOT USE A PRODUCTION OR PERSONAL HUB HERE.\n"
)
CHILD_PREFIX = "Keelaryn__Disposable_Acceptance_"


class DisposableAcceptanceBlocked(ProtocolError):
    pass


@dataclass(frozen=True)
class AcceptanceCaseResult:
    decision: str
    outcome: str
    hub_id: str
    canonical_epoch: int


@dataclass(frozen=True)
class DisposableAcceptanceResult:
    run_id: str
    pass_case: AcceptanceCaseResult
    fail_case: AcceptanceCaseResult

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "pass": {
                    "outcome": self.pass_case.outcome,
                    "canonical_epoch": self.pass_case.canonical_epoch,
                },
                "fail": {
                    "outcome": self.fail_case.outcome,
                    "canonical_epoch": self.fail_case.canonical_epoch,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def _safe_run_id(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 96:
        raise DisposableAcceptanceBlocked("acceptance run_id is invalid")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for ch in value):
        raise DisposableAcceptanceBlocked("acceptance run_id contains unsupported characters")
    return value


def verify_acceptance_root(drive: DriveBackend, root_id: str) -> None:
    try:
        root = drive.get(root_id, include_trashed=False)
    except DriveNotFound as exc:
        raise DisposableAcceptanceBlocked("disposable acceptance root does not exist") from exc
    if root.trashed or not root.is_folder or root.name != ACCEPTANCE_ROOT_NAME:
        raise DisposableAcceptanceBlocked("target is not the exact disposable acceptance root")

    sentinel = drive.list_children(root_id, name=SENTINEL_NAME)
    if len(sentinel) != 1 or sentinel[0].trashed or sentinel[0].is_folder:
        raise DisposableAcceptanceBlocked("disposable acceptance sentinel README.md is missing/ambiguous")
    if drive.download(sentinel[0].file_id) != SENTINEL_BYTES:
        raise DisposableAcceptanceBlocked("disposable acceptance sentinel bytes do not match")

    for child in drive.list_children(root_id):
        if child.file_id == sentinel[0].file_id:
            continue
        if child.trashed or not child.is_folder or not child.name.startswith(CHILD_PREFIX):
            raise DisposableAcceptanceBlocked(
                f"unexpected object exists in disposable acceptance root: {child.name}"
            )


def _create_folder(drive: DriveBackend, parent_id: str, name: str, label: str):
    file_id = drive.generate_ids(1)[0]
    return drive.create_folder(parent_id, name, file_id=file_id, label=label)


def _create_blob(drive: DriveBackend, parent_id: str, name: str, raw: bytes, label: str):
    file_id = drive.generate_ids(1)[0]
    return drive.create_blob(parent_id, name, raw, file_id=file_id, label=label)


def _present(raw: bytes) -> dict[str, object]:
    return {"state": "PRESENT", "sha256": sha256(raw).hexdigest(), "size": len(raw)}


def _seed_ready_change(drive: DriveBackend, hub_id: str, decision: str, run_id: str) -> tuple[str, str]:
    bootstrap = DriveHubBootstrap(drive, hub_id).run()
    if bootstrap.master["canonical_epoch"] != 0 or bootstrap.master["canonical_read_status"] != "SAFE":
        raise DisposableAcceptanceBlocked("fresh acceptance Hub did not bootstrap as SAFE epoch 0")

    canonical = bootstrap.layout.canonical_root_id
    replace_old = f"replace-old-{run_id}".encode("utf-8")
    replace_new = f"replace-new-{run_id}".encode("utf-8")
    delete_old = f"delete-old-{run_id}".encode("utf-8")
    add_new = f"add-new-{run_id}".encode("utf-8")
    _create_blob(drive, canonical, "replace.txt", replace_old, "accept.seed.replace")
    _create_blob(drive, canonical, "delete.txt", delete_old, "accept.seed.delete")

    change_id = f"accept-{decision.lower()}-{run_id}"
    change_folder = _create_folder(
        drive,
        bootstrap.layout.changes_parent_id,
        change_id,
        "accept.ready.change-folder",
    )
    prepared = _create_folder(drive, change_folder.file_id, "prepared", "accept.ready.prepared")
    _create_blob(drive, prepared.file_id, "add.bin", add_new, "accept.ready.add")
    _create_blob(drive, prepared.file_id, "replace.bin", replace_new, "accept.ready.replace")

    change = {
        "schema": "keelaryn.change.v1",
        "change_id": change_id,
        "base_canonical_epoch": 0,
        "operations": [
            {
                "operation_id": "add",
                "kind": "ADD",
                "target": "added.txt",
                "old": {"state": "ABSENT"},
                "new": _present(add_new),
                "prepared_path": "prepared/add.bin",
            },
            {
                "operation_id": "replace",
                "kind": "REPLACE",
                "target": "replace.txt",
                "old": _present(replace_old),
                "new": _present(replace_new),
                "prepared_path": "prepared/replace.bin",
            },
            {
                "operation_id": "delete",
                "kind": "DELETE",
                "target": "delete.txt",
                "old": _present(delete_old),
                "new": {"state": "ABSENT"},
            },
        ],
    }
    change_raw = canonical_json_bytes(change)
    _create_blob(drive, change_folder.file_id, "CHANGE.json", change_raw, "accept.ready.change")
    _create_blob(
        drive,
        change_folder.file_id,
        "READY.json",
        canonical_json_bytes(
            {
                "schema": "keelaryn.ready.v1",
                "state": "READY_FOR_COMMIT",
                "change_id": change_id,
                "change_sha256": sha256(change_raw).hexdigest(),
            }
        ),
        "accept.ready.marker",
    )
    return change_id, bootstrap.layout.postcheck_parent_id


def _verify_case(drive: DriveBackend, hub_id: str, decision: str, run_id: str) -> AcceptanceCaseResult:
    change_id, postcheck_parent = _seed_ready_change(drive, hub_id, decision, run_id)
    service = DrivePollingService(drive, hub_id)
    first = service.run_once()
    if first.phase != "WAIT_POSTCHECK":
        raise DisposableAcceptanceBlocked(f"{decision} case did not reach WAIT_POSTCHECK: {first.phase}")

    # Discover exact active identity from root MASTER without depending on process-local bundle.
    from keelaryn_core.drive_master import DriveMasterTransition
    from keelaryn_core.protocol import strict_json_bytes, validate_master

    _, master_raw = DriveMasterTransition.read_unique_master(drive, hub_id)
    active_master = validate_master(strict_json_bytes(master_raw, label="MASTER.acceptance-active"))
    active = active_master["active_change"]
    if active is None or active["change_id"] != change_id:
        raise DisposableAcceptanceBlocked("acceptance active MASTER does not identify seeded change")

    _create_blob(
        drive,
        postcheck_parent,
        f"{change_id}.json",
        canonical_json_bytes(
            {
                "schema": "keelaryn.postcheck.v1",
                "change_id": change_id,
                "change_sha256": active["change_sha256"],
                "base_canonical_epoch": active["base_canonical_epoch"],
                "decision": decision,
                "reason": f"disposable live acceptance {decision}",
            }
        ),
        f"accept.postcheck.{decision.lower()}",
    )

    final = DrivePollingService(drive, hub_id).run_once()
    expected = "COMMITTED" if decision == "PASS" else "ROLLED_BACK"
    if final.phase != expected or not final.ready_clean:
        raise DisposableAcceptanceBlocked(
            f"{decision} case ended in {final.phase}/ready_clean={final.ready_clean}, expected {expected}/true"
        )
    idle = DrivePollingService(drive, hub_id).run_once()
    if idle.phase != "IDLE" or not idle.ready_clean:
        raise DisposableAcceptanceBlocked(f"{decision} case did not become clean IDLE")

    _, final_raw = DriveMasterTransition.read_unique_master(drive, hub_id)
    final_master = validate_master(strict_json_bytes(final_raw, label="MASTER.acceptance-final"))
    completed = final_master["last_completed_change"]
    if completed is None or completed["change_id"] != change_id or completed["outcome"] != expected:
        raise DisposableAcceptanceBlocked("acceptance final MASTER completion provenance mismatch")
    if final_master["canonical_epoch"] != 1:
        raise DisposableAcceptanceBlocked("acceptance transaction did not increment canonical epoch exactly once")

    canonical = DriveHubBootstrap(drive, hub_id).run().layout.canonical_root_id
    added = drive.exact_name(canonical, "added.txt")
    replaced = drive.exact_name(canonical, "replace.txt")
    deleted = drive.exact_name(canonical, "delete.txt")
    if decision == "PASS":
        if added is None or replaced is None or deleted is not None:
            raise DisposableAcceptanceBlocked("PASS canonical outcome does not match ADD/REPLACE/DELETE expectation")
    else:
        if added is not None or replaced is None or deleted is None:
            raise DisposableAcceptanceBlocked("FAIL rollback canonical outcome does not restore OLD state")

    return AcceptanceCaseResult(decision, expected, hub_id, final_master["canonical_epoch"])


def run_disposable_acceptance(drive: DriveBackend, acceptance_root_id: str, run_id: str) -> DisposableAcceptanceResult:
    run_id = _safe_run_id(run_id)
    verify_acceptance_root(drive, acceptance_root_id)

    hubs = {}
    for decision in ("PASS", "FAIL"):
        child = _create_folder(
            drive,
            acceptance_root_id,
            f"{CHILD_PREFIX}{run_id}_{decision}",
            f"accept.hub.{decision.lower()}.create",
        )
        hubs[decision] = child.file_id

    pass_case = _verify_case(drive, hubs["PASS"], "PASS", run_id)
    fail_case = _verify_case(drive, hubs["FAIL"], "FAIL", run_id)
    return DisposableAcceptanceResult(run_id, pass_case, fail_case)


def main() -> int:
    if os.environ.get("KEELARYN_DRIVE_ACCEPT_DISPOSABLE") != "YES":
        print("ERROR: KEELARYN_DRIVE_ACCEPT_DISPOSABLE=YES is required", file=sys.stderr)
        return 2
    root_id = os.environ.get("KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID")
    run_id = os.environ.get("KEELARYN_ACCEPTANCE_RUN_ID")
    if not root_id or not run_id:
        print("ERROR: disposable acceptance root/run ID is not configured", file=sys.stderr)
        return 2
    try:
        provider = GoogleOAuthRefreshTokenProvider.from_environment()
        result = run_disposable_acceptance(GoogleDriveBackend(provider), root_id, run_id)
        print(result.to_json(), flush=True)
        return 0
    except Exception as exc:
        # Credentials are never interpolated into this harness's own messages.
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
