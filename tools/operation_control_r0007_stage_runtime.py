from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


private_input = _load(
    "keelaryn_r0007_stage_runtime_private_input",
    Path(__file__).with_name("operation_control_r0007_private_input.py"),
)
transaction = private_input.transaction
# Reuse the exact execution/authority module graph already loaded by the
# real-stage transaction layer. Loading stage_execution.py a second time
# creates a different IssuedStageAuthorization class identity and must not
# cross the production stage boundary.
execution = transaction.execution
stage = execution.stage

GATE_REVISION = "operation-control-r0007-stage-runtime-gate-r0001"
SCHEMA = "keelaryn.operation-control-r0007-stage-runtime.v1"
FAILURE_SCHEMA = "keelaryn.operation-control-r0007-stage-runtime-failure.v1"

TRANSACTION_ID = private_input.TRANSACTION_ID
DEFAULT_INPUT_ROOT = private_input.DEFAULT_INPUT_ROOT
DEFAULT_RELEASES_ROOT = Path("/opt/keelaryn/releases")
DEFAULT_WITNESS_ROOT = Path(
    "/var/lib/keelaryn/operation-control/r0007-stage-witness"
)
SCRIPT_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_INPUT_IDENTITY = {
    "source_commit": transaction.SOURCE_COMMIT,
    "payload_sha256": transaction.PAYLOAD_SHA256,
    "payload_size": transaction.PAYLOAD_SIZE,
    "file_count": transaction.PAYLOAD_FILE_COUNT,
}


class StageRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _inspect_parent(root: Path) -> Path:
    parent = root.absolute().parent
    try:
        info = parent.stat(follow_symlinks=False)
    except OSError as exc:
        raise StageRuntimeError(
            "WITNESS_PARENT_INVALID",
            "stage witness parent cannot be inspected",
        ) from exc
    if parent.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise StageRuntimeError(
            "WITNESS_PARENT_INVALID",
            "stage witness parent must be a real directory",
        )
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise StageRuntimeError(
                "WITNESS_PARENT_INVALID",
                "stage witness parent must be current-user owned and not group/world writable",
            )
    return parent


def _ensure_witness_root() -> tuple[Path, bool]:
    root = DEFAULT_WITNESS_ROOT.absolute()
    if root.exists() or root.is_symlink():
        return execution._private_dir(root, "operation-stage witness root"), False
    parent = _inspect_parent(root)
    try:
        os.mkdir(root, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise StageRuntimeError(
            "WITNESS_ROOT_CREATE_FAILED",
            "stage witness root creation failed",
        ) from exc
    if os.name == "posix":
        os.chmod(root, 0o700)
    transaction._fsync_dir(parent)
    return execution._private_dir(root, "operation-stage witness root"), True


def _verify_input(materializer: Any) -> tuple[Path, dict[str, Any]]:
    state = transaction.reconcile_private_input(
        input_root=DEFAULT_INPUT_ROOT,
        transaction_id=TRANSACTION_ID,
        materializer=materializer,
    )
    if (
        state.get("state") != "INPUT_EXACT"
        or state.get("exact") is not True
        or state.get("identity") != EXPECTED_INPUT_IDENTITY
    ):
        raise StageRuntimeError(
            "PRIVATE_INPUT_NOT_EXACT",
            "transaction-bound private input is not exact",
        )
    payload = transaction._input_path(DEFAULT_INPUT_ROOT, TRANSACTION_ID)
    return payload, state


def _context(work: Path) -> dict[str, Any]:
    repo = SCRIPT_REPOSITORY_ROOT.resolve()
    branch = private_input._verify_repository(repo)
    issued = private_input._resolve_issued(repo)
    live = private_input._fresh_live_boundary()
    _, materializer = private_input._load_frozen_materializer(work)
    payload, input_state = _verify_input(materializer)
    return {
        "repo": repo,
        "branch": branch,
        "issued": issued,
        "live": live,
        "materializer": materializer,
        "payload": payload,
        "input_state": input_state,
    }


def _reconcile_context(ctx: dict[str, Any]) -> dict[str, Any]:
    root = DEFAULT_WITNESS_ROOT.absolute()
    if not root.exists() and not root.is_symlink():
        execution._expected_prepared(
            repository_root=ctx["repo"],
            issued=ctx["issued"],
            payload=ctx["payload"],
            materializer=ctx["materializer"],
            boundary_probe=execution.production.live_boundary_probe,
        )
        release = stage.reconcile_stage(
            DEFAULT_RELEASES_ROOT,
            ctx["materializer"],
        )
        if release["state"] == "STAGED_EXACT":
            raise StageRuntimeError(
                "UNATTRIBUTED_STAGED_RELEASE",
                "exact staged release exists while canonical witness root is absent",
            )
        if release["state"] != "NOT_STAGED":
            raise StageRuntimeError(
                release["state"],
                "release state requires reconciliation before stage execution",
            )
        return {
            "state": "NEW",
            "release_state": "NOT_STAGED",
            "prepared": False,
            "completed": False,
            "witness_root_state": "ABSENT",
        }
    value = execution.reconcile_execution(
        repository_root=ctx["repo"],
        issued=ctx["issued"],
        payload=ctx["payload"],
        releases_root=DEFAULT_RELEASES_ROOT,
        witness_root=root,
        materializer=ctx["materializer"],
        boundary_probe=execution.production.live_boundary_probe,
    )
    return {
        **value,
        "witness_root_state": "PRESENT",
    }


def _safe_live(live: dict[str, Any]) -> dict[str, Any]:
    return {
        "production_source_commit": live["production_source_commit"],
        "control_source_commit": live["control_source_commit"],
        "legacy_hub_status": live["legacy_hub"]["status"],
        "legacy_hub_transaction_id": live["legacy_hub"]["transaction_id"],
        "selector_role": live["legacy_hub"]["selector_role"],
        "writer": live["services"]["writer"],
        "r0007_snapshot_unit": live["r0007_snapshot_unit"],
    }


def _base(
    *,
    command: str,
    ctx: dict[str, Any],
    execution_state: dict[str, Any],
    witness_root_created: bool,
    release_publication_performed: bool,
    stage_witness_mutation_performed: bool,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "gate_revision": GATE_REVISION,
        "command": command,
        "transaction_id": TRANSACTION_ID,
        "branch_tip": ctx["branch"]["expected"],
        "authority_commit": private_input.AUTHORITY_COMMIT,
        "authority_path": private_input.AUTHORITY_PATH,
        "authority_git_blob": private_input.AUTHORITY_BLOB,
        "authority_sha256": private_input.AUTHORITY_SHA256,
        "input_root": str(DEFAULT_INPUT_ROOT),
        "input_state": ctx["input_state"],
        "releases_root": str(DEFAULT_RELEASES_ROOT),
        "witness_root": str(DEFAULT_WITNESS_ROOT),
        "witness_root_created": witness_root_created,
        "execution": execution_state,
        "live_boundary": _safe_live(ctx["live"]),
        "release_publication_performed": release_publication_performed,
        "stage_witness_mutation_performed": stage_witness_mutation_performed,
        "activation_performed": False,
        "legacy_hub_mutation_performed": False,
        "writer_mutation_performed": False,
        "credential_mutation_performed": False,
        "drive_mutations_performed": False,
    }


def reconcile() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0007-stage-runtime-reconcile-"
    ) as td:
        ctx = _context(Path(td))
        observed = _reconcile_context(ctx)
        return _base(
            command="reconcile",
            ctx=ctx,
            execution_state=observed,
            witness_root_created=False,
            release_publication_performed=False,
            stage_witness_mutation_performed=False,
        )


def stage_once() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0007-stage-runtime-stage-"
    ) as td:
        ctx = _context(Path(td))
        pre = _reconcile_context(ctx)

        branch2 = private_input._verify_repository(
            ctx["repo"],
            ctx["branch"]["expected"],
        )
        issued2 = private_input._resolve_issued(ctx["repo"])
        live2 = private_input._fresh_live_boundary()
        payload2, input2 = _verify_input(ctx["materializer"])
        if (
            branch2 != ctx["branch"]
            or issued2.transaction_id != ctx["issued"].transaction_id
            or live2 != ctx["live"]
            or payload2 != ctx["payload"]
            or input2 != ctx["input_state"]
        ):
            raise StageRuntimeError(
                "MUTATION_BOUNDARY_DRIFT",
                "Git/authority/runtime/private-input boundary changed before stage",
            )

        witness_root, created = _ensure_witness_root()
        try:
            completed = execution.execute_once(
                repository_root=ctx["repo"],
                issued=issued2,
                payload=payload2,
                releases_root=DEFAULT_RELEASES_ROOT,
                witness_root=witness_root,
                materializer=ctx["materializer"],
                boundary_probe=execution.production.live_boundary_probe,
            )
        except Exception:
            raise

        post = execution.reconcile_execution(
            repository_root=ctx["repo"],
            issued=issued2,
            payload=payload2,
            releases_root=DEFAULT_RELEASES_ROOT,
            witness_root=witness_root,
            materializer=ctx["materializer"],
            boundary_probe=execution.production.live_boundary_probe,
        )
        if post.get("state") != "COMPLETED_EXACT":
            raise StageRuntimeError(
                "POST_STAGE_RECONCILE_FAILED",
                "stage execution did not reconcile to COMPLETED_EXACT",
            )

        execution_state = completed.get("execution_state")
        published = execution_state == "COMPLETED_EXACT" and pre.get("state") == "NEW"
        witness_mutated = execution_state in {
            "COMPLETED_EXACT",
            "RECOVERED_COMPLETED_EXACT",
        }
        return _base(
            command="stage",
            ctx={
                **ctx,
                "branch": branch2,
                "issued": issued2,
                "live": live2,
                "input_state": input2,
            },
            execution_state={
                "pre": pre,
                "result": completed,
                "post": post,
            },
            witness_root_created=created,
            release_publication_performed=published,
            stage_witness_mutation_performed=witness_mutated or created,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0007-stage-runtime"
    )
    parser.add_argument("command", choices=("reconcile", "stage"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "reconcile":
            value = reconcile()
        elif args.command == "stage":
            value = stage_once()
        else:
            raise StageRuntimeError("COMMAND_INVALID", "unsupported command")
    except (
        StageRuntimeError,
        private_input.PrivateInputError,
        transaction.RealStageTransactionError,
        execution.StageExecutionError,
        execution.authority.StageAuthorityError,
        execution.production.ProductionStagePrepError,
        stage.StageError,
        OSError,
    ) as exc:
        stage_command = args.command == "stage"
        print(
            json.dumps(
                {
                    "schema": FAILURE_SCHEMA,
                    "command": args.command,
                    "transaction_id": TRANSACTION_ID,
                    "error_code": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                    "reconcile_required": stage_command,
                    "release_publication_performed": None if stage_command else False,
                    "stage_witness_mutation_performed": None if stage_command else False,
                    "activation_performed": False,
                    "legacy_hub_mutation_performed": False,
                    "writer_mutation_performed": False,
                    "credential_mutation_performed": False,
                    "drive_mutations_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
