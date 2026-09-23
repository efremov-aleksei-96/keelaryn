from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import subprocess
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


transaction = _load(
    "keelaryn_r0008_private_input_transaction",
    Path(__file__).with_name("operation_control_r0008_real_stage_transaction.py"),
)
authority = transaction.authority
production = transaction.production

GATE_REVISION = "operation-control-r0008-private-input-gate-r0001"
SCHEMA = "keelaryn.operation-control-r0008-private-input.v1"
FAILURE_SCHEMA = "keelaryn.operation-control-r0008-private-input-failure.v1"

BRANCH = "dev/zero-based-keelaryn"
SOURCE_REMOTE = "https://github.com/efremov-aleksei-96/keelaryn.git"
TRANSACTION_ID = "a6383609e9a6442ad86445ba62baff93"
AUTHORITY_COMMIT = "03f3e794fdcbd18e07d21dcb633c463674ce4e6b"
AUTHORITY_PATH = (
    "docs/authorizations/operation-control-r0008-stage/"
    + TRANSACTION_ID
    + ".json"
)
AUTHORITY_BLOB = "101b05042471abf7d10415cea36ba3053093364d"
AUTHORITY_SHA256 = "2bc92df91d1272c30783879c794a36e066e5ad024a262c70ba09c33ec50e7864"
BOUNDARY_BLOB = "615bb687b39b60eea5b7638b063a2d1587cca6d2"
BOUNDARY_SHA256 = "701abe5f5ea53386f6cf15e0d3068c2f354d3393529457813b9bbb47b4b13296"

DEFAULT_INPUT_ROOT = Path(
    "/var/lib/keelaryn/operation-control/r0008-stage-input"
)

SCRIPT_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class PrivateInputError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _hex(value: str, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise PrivateInputError("IDENTITY_INVALID", f"{label} is invalid")
    return value


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        value = subprocess.run(
            args,
            cwd=None if cwd is None else str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrivateInputError(
            "COMMAND_OUTCOME_UNCERTAIN",
            f"command outcome uncertain: {args[0]}",
        ) from exc
    if check and value.returncode != 0:
        raise PrivateInputError(
            "COMMAND_FAILED",
            value.stderr.decode("utf-8", errors="replace").strip()
            or f"command failed: {args[0]}",
        )
    return value


def _git_commit(root: Path, ref: str) -> str:
    value = _run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{ref}^{{commit}}"]
    ).stdout.decode("ascii").strip()
    return _hex(value, 40, "Git commit")


def _remote_branch_tip() -> str:
    result = _run(
        ["git", "ls-remote", "--heads", SOURCE_REMOTE, f"refs/heads/{BRANCH}"],
        timeout=120,
    )
    lines = [
        line
        for line in result.stdout.decode("ascii").splitlines()
        if line.strip()
    ]
    if len(lines) != 1:
        raise PrivateInputError(
            "REMOTE_BRANCH_INVALID",
            "authoritative remote branch did not resolve exactly once",
        )
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != f"refs/heads/{BRANCH}":
        raise PrivateInputError(
            "REMOTE_BRANCH_INVALID",
            "authoritative remote branch response is malformed",
        )
    return _hex(fields[0], 40, "remote branch tip")


def _verify_repository(
    root: Path,
    expected_branch_tip: str | None = None,
) -> dict[str, str]:
    root = root.resolve()
    if not (root / ".git").is_dir():
        raise PrivateInputError(
            "REPOSITORY_INVALID",
            "repository root is not a Git checkout",
        )
    local_branch = _git_commit(root, f"refs/heads/{BRANCH}")
    local_head = _git_commit(root, "HEAD")
    remote_branch = _remote_branch_tip()
    if local_branch != local_head or remote_branch != local_head:
        raise PrivateInputError(
            "BRANCH_TIP_DRIFT",
            "local HEAD, authoritative branch and live remote branch differ",
        )
    if expected_branch_tip is not None:
        expected = _hex(expected_branch_tip, 40, "expected branch tip")
        if local_head != expected:
            raise PrivateInputError(
                "BRANCH_TIP_DRIFT",
                "authoritative branch changed from the transaction precheck",
            )
    else:
        expected = local_head
    return {
        "expected": expected,
        "local_branch": local_branch,
        "local_head": local_head,
        "remote_branch": remote_branch,
    }


def _resolve_issued(root: Path):
    issued = authority.resolve_git_authorization(
        root,
        authority_commit=AUTHORITY_COMMIT,
        authority_path_value=AUTHORITY_PATH,
        expected_authority_blob=AUTHORITY_BLOB,
    )
    authority.require_issued_authorization(issued)
    record = issued.record
    provenance = issued.provenance
    expected_record = {
        "transaction_id": TRANSACTION_ID,
        "scope": "R0008_RELEASE_STAGE_ONLY",
        "candidate": "operation-control-r0008-20260921-01",
        "source_commit": transaction.SOURCE_COMMIT,
        "source_tree": transaction.SOURCE_TREE,
        "payload_sha256": transaction.PAYLOAD_SHA256,
        "payload_size": transaction.PAYLOAD_SIZE,
        "file_count": transaction.PAYLOAD_FILE_COUNT,
        "production_stage_authorized": True,
        "activation_authorized": False,
        "drive_content_mutation_authorized": False,
        "legacy_hub_mutation_authorized": False,
        "writer_mutation_authorized": False,
        "credential_mutation_authorized": False,
    }
    for key, expected in expected_record.items():
        if record.get(key) != expected:
            raise PrivateInputError(
                "AUTHORITY_IDENTITY_MISMATCH",
                f"issued authority field mismatch: {key}",
            )
    expected_provenance = {
        "authority_commit": AUTHORITY_COMMIT,
        "authority_path": AUTHORITY_PATH,
        "authority_git_blob": AUTHORITY_BLOB,
        "authority_sha256": AUTHORITY_SHA256,
        "boundary_evidence_git_blob": BOUNDARY_BLOB,
        "boundary_evidence_sha256": BOUNDARY_SHA256,
    }
    for key, expected in expected_provenance.items():
        if provenance.get(key) != expected:
            raise PrivateInputError(
                "AUTHORITY_PROVENANCE_MISMATCH",
                f"issued authority provenance mismatch: {key}",
            )
    return issued


def _project_live_boundary(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != "keelaryn.operation-control-r0008-bootstrap-reconcile.v1":
        raise PrivateInputError(
            "LIVE_BOUNDARY_INVALID",
            "live boundary schema mismatch",
        )
    if value.get("production_mutations_performed") is not False:
        raise PrivateInputError(
            "LIVE_BOUNDARY_INVALID",
            "live reconcile claims production mutation",
        )
    if value.get("drive_mutations_performed") is not False:
        raise PrivateInputError(
            "LIVE_BOUNDARY_INVALID",
            "live reconcile claims Drive mutation",
        )
    boundary = value.get("production_boundary")
    if not isinstance(boundary, dict):
        raise PrivateInputError(
            "LIVE_BOUNDARY_INVALID",
            "live production boundary missing",
        )
    units = boundary.get("services", {}).get("operation_units", {})
    projected_units: dict[str, Any] = {}
    for name in (
        "keelaryn-operation-agent.service",
        "keelaryn-operation-transport.service",
    ):
        unit = units.get(name, {})
        projected_units[name] = {
            "active_state": unit.get("active_state"),
            "enabled": unit.get("enabled"),
            "exact_release_bytes": unit.get("exact_release_bytes"),
        }
    hub = boundary.get("legacy_hub", {})
    inhibit = hub.get("mutation_inhibit", {})
    credential = boundary.get("credential", {})
    return {
        "production_source_commit": boundary.get("production_source_commit"),
        "control_source_commit": boundary.get("control_source_commit"),
        "control_release": boundary.get("control_release"),
        "services": {
            "writer": boundary.get("services", {}).get("writer"),
            "operation_units": projected_units,
        },
        "legacy_hub": {
            "status": hub.get("status"),
            "transaction_id": hub.get("transaction_id"),
            "active_transaction_sha256": hub.get("active_transaction_sha256"),
            "selector_role": hub.get("selector_role"),
            "old_selector_identity_sha256": hub.get(
                "old_selector_identity_sha256"
            ),
            "new_selector_identity_sha256": hub.get(
                "new_selector_identity_sha256"
            ),
            "mutation_inhibit": {
                "state": inhibit.get("state"),
                "authority_matches": inhibit.get("authority_matches"),
            },
            "authority_scope": hub.get("authority_scope"),
        },
        "credential": {
            "sha256": credential.get("sha256"),
            "bootstrap_receipt_exact": credential.get(
                "bootstrap_receipt_exact"
            ),
        },
        "r0008_snapshot_unit": boundary.get("r0008_snapshot_unit"),
    }


def _fresh_live_boundary() -> dict[str, Any]:
    observed = _project_live_boundary(production.prep.reconcile())
    expected = production._qualification_boundary()
    if observed != expected:
        raise PrivateInputError(
            "LIVE_BOUNDARY_DRIFT",
            "live runtime boundary differs from qualified exact boundary",
        )
    return observed


def _inspect_parent_for_root(root: Path) -> Path:
    parent = root.absolute().parent
    try:
        info = parent.stat(follow_symlinks=False)
    except OSError as exc:
        raise PrivateInputError(
            "PRIVATE_INPUT_PARENT_INVALID",
            "private input parent cannot be inspected",
        ) from exc
    if parent.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise PrivateInputError(
            "PRIVATE_INPUT_PARENT_INVALID",
            "private input parent must be a real directory",
        )
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise PrivateInputError(
                "PRIVATE_INPUT_PARENT_INVALID",
                "private input parent must be current-user owned and not group/world writable",
            )
    return parent


def _input_prestate(
    input_root: Path,
    *,
    materializer: Any | None,
) -> dict[str, Any]:
    root = input_root.absolute()
    if not root.exists() and not root.is_symlink():
        return {
            "state": "INPUT_ROOT_ABSENT",
            "path": f"{TRANSACTION_ID}.r0008.tar.gz",
            "exact": False,
        }
    if materializer is None:
        raise PrivateInputError(
            "MATERIALIZER_REQUIRED",
            "materializer required for existing input root",
        )
    return transaction.reconcile_private_input(
        input_root=root,
        transaction_id=TRANSACTION_ID,
        materializer=materializer,
    )


def _ensure_input_root(input_root: Path) -> tuple[Path, bool]:
    root = input_root.absolute()
    if root.exists() or root.is_symlink():
        return transaction._private_dir(root, "stage input root"), False
    parent = _inspect_parent_for_root(root)
    try:
        os.mkdir(root, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise PrivateInputError(
            "PRIVATE_INPUT_ROOT_CREATE_FAILED",
            "private input root creation failed",
        ) from exc
    if os.name == "posix":
        os.chmod(root, 0o700)
    transaction._fsync_dir(parent)
    return transaction._private_dir(root, "stage input root"), True


def _load_frozen_materializer(work: Path):
    source = transaction._checkout_exact_source(
        remote_url=SOURCE_REMOTE,
        work=work,
    )
    materializer = production._load_exact_materializer(
        source / "deploy" / "zero-based-vps" / "materialize_payload.py"
    )
    return source, materializer


def _base_result(
    *,
    command: str,
    branch_tip: str,
    input_root: Path,
    live_boundary: dict[str, Any],
    input_state: dict[str, Any],
    private_input_mutation_performed: bool,
    input_root_created: bool,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "gate_revision": GATE_REVISION,
        "command": command,
        "transaction_id": TRANSACTION_ID,
        "authority_commit": AUTHORITY_COMMIT,
        "authority_path": AUTHORITY_PATH,
        "authority_git_blob": AUTHORITY_BLOB,
        "authority_sha256": AUTHORITY_SHA256,
        "branch_tip": branch_tip,
        "input_root": str(input_root.absolute()),
        "input_state": input_state,
        "live_boundary": {
            "production_source_commit": live_boundary[
                "production_source_commit"
            ],
            "control_source_commit": live_boundary["control_source_commit"],
            "legacy_hub_status": live_boundary["legacy_hub"]["status"],
            "legacy_hub_transaction_id": live_boundary["legacy_hub"][
                "transaction_id"
            ],
            "selector_role": live_boundary["legacy_hub"]["selector_role"],
            "writer": live_boundary["services"]["writer"],
            "r0008_snapshot_unit": live_boundary["r0008_snapshot_unit"],
        },
        "private_input_mutation_performed": private_input_mutation_performed,
        "input_root_created": input_root_created,
        "release_publication_performed": False,
        "stage_witness_mutation_performed": False,
        "activation_performed": False,
        "legacy_hub_mutation_performed": False,
        "writer_mutation_performed": False,
        "credential_mutation_performed": False,
        "drive_mutations_performed": False,
    }


def reconcile(
    *,
    repository_root: Path,
    input_root: Path = DEFAULT_INPUT_ROOT,
) -> dict[str, Any]:
    repo = repository_root.resolve()
    branch = _verify_repository(repo)
    _resolve_issued(repo)
    live = _fresh_live_boundary()

    root = input_root.absolute()
    if not root.exists() and not root.is_symlink():
        state = _input_prestate(root, materializer=None)
    else:
        with tempfile.TemporaryDirectory(
            prefix="keelaryn-r0008-private-input-reconcile-"
        ) as td:
            _, materializer = _load_frozen_materializer(Path(td))
            state = _input_prestate(root, materializer=materializer)

    return _base_result(
        command="reconcile",
        branch_tip=branch["expected"],
        input_root=root,
        live_boundary=live,
        input_state=state,
        private_input_mutation_performed=False,
        input_root_created=False,
    )


def acquire(
    *,
    repository_root: Path,
    input_root: Path = DEFAULT_INPUT_ROOT,
) -> dict[str, Any]:
    repo = repository_root.resolve()
    branch = _verify_repository(repo)
    _resolve_issued(repo)
    live = _fresh_live_boundary()
    root = input_root.absolute()

    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0008-private-input-acquire-"
    ) as td:
        work = Path(td)
        source, materializer = _load_frozen_materializer(work)
        before = _input_prestate(root, materializer=materializer)
        if before.get("state") == "INPUT_EXACT":
            return _base_result(
                command="acquire",
                branch_tip=branch["expected"],
                input_root=root,
                live_boundary=live,
                input_state={
                    **before,
                    "acquisition_state": "ALREADY_ACQUIRED_EXACT",
                },
                private_input_mutation_performed=False,
                input_root_created=False,
            )
        if before.get("state") not in {"INPUT_ROOT_ABSENT", "INPUT_ABSENT"}:
            raise PrivateInputError(
                "PRIVATE_INPUT_CONFLICT",
                "existing private input is foreign/invalid",
            )

        raw, identity = transaction._build_exact_twice(
            source=source,
            work=work,
            materializer=materializer,
        )

        # Mutation-boundary revalidation after all failure-prone network/build work.
        branch2 = _verify_repository(repo, branch["expected"])
        _resolve_issued(repo)
        live2 = _fresh_live_boundary()
        if branch2 != branch or live2 != live:
            raise PrivateInputError(
                "MUTATION_BOUNDARY_DRIFT",
                "Git/runtime boundary changed before private input publication",
            )

        secure_root, root_created = _ensure_input_root(root)
        immediate = transaction.reconcile_private_input(
            input_root=secure_root,
            transaction_id=TRANSACTION_ID,
            materializer=materializer,
        )
        if immediate.get("state") == "INPUT_EXACT":
            return _base_result(
                command="acquire",
                branch_tip=branch["expected"],
                input_root=secure_root,
                live_boundary=live2,
                input_state={
                    **immediate,
                    "acquisition_state": "ALREADY_ACQUIRED_EXACT",
                },
                private_input_mutation_performed=root_created,
                input_root_created=root_created,
            )
        if immediate.get("state") != "INPUT_ABSENT":
            raise PrivateInputError(
                "PRIVATE_INPUT_CONFLICT",
                "private input state changed before publication",
            )

        path = transaction._input_path(secure_root, TRANSACTION_ID)
        transaction._atomic_private_bytes_new(
            path,
            raw,
            "r0008 transaction-bound private input",
        )
        after = transaction.reconcile_private_input(
            input_root=secure_root,
            transaction_id=TRANSACTION_ID,
            materializer=materializer,
        )
        if after.get("state") != "INPUT_EXACT":
            raise PrivateInputError(
                "PRIVATE_INPUT_POSTVERIFY_FAILED",
                "published private input is not exact",
            )
        if after.get("identity") != identity:
            raise PrivateInputError(
                "PRIVATE_INPUT_POSTVERIFY_FAILED",
                "published private input identity changed",
            )

    return _base_result(
        command="acquire",
        branch_tip=branch["expected"],
        input_root=root,
        live_boundary=live2,
        input_state={
            **after,
            "acquisition_state": "ACQUIRED_EXACT",
        },
        private_input_mutation_performed=True,
        input_root_created=root_created,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0008-private-input"
    )
    parser.add_argument("command", choices=("reconcile", "acquire"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "reconcile":
            value = reconcile(
                repository_root=SCRIPT_REPOSITORY_ROOT,
                input_root=DEFAULT_INPUT_ROOT,
            )
        elif args.command == "acquire":
            value = acquire(
                repository_root=SCRIPT_REPOSITORY_ROOT,
                input_root=DEFAULT_INPUT_ROOT,
            )
        else:
            raise PrivateInputError("COMMAND_INVALID", "unsupported command")
    except (
        PrivateInputError,
        transaction.RealStageTransactionError,
        authority.StageAuthorityError,
        production.ProductionStagePrepError,
        production.prep.PrepError,
        OSError,
    ) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        print(
            json.dumps(
                {
                    "schema": FAILURE_SCHEMA,
                    "command": args.command,
                    "transaction_id": TRANSACTION_ID,
                    "error_code": code,
                    "message": str(exc),
                    "release_publication_performed": False,
                    "activation_performed": False,
                    "drive_mutations_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
