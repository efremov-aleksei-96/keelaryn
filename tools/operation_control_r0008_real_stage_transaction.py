from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


execution = _load(
    "keelaryn_r0008_real_stage_execution",
    Path(__file__).with_name("operation_control_r0008_stage_execution.py"),
)
# Reuse the exact trusted module/class graph already loaded and qualified by
# the execution layer. Loading authority.py a second time would create a
# different Python class identity for IssuedStageAuthorization and must not
# be allowed at the real-stage transaction boundary.
authority = execution.authority
issuer = execution.issuer
production = execution.production
stage = execution.stage

GATE_REVISION = "operation-control-r0008-real-stage-transaction-gate-r0002"
TRANSACTION_SCHEMA = "keelaryn.operation-control-r0008-real-stage-transaction-qualification.v1"
RESULT_SCHEMA = "keelaryn.operation-control-r0008-stage-result-checkpoint.v1"

REPOSITORY_URL = "https://github.com/efremov-aleksei-96/keelaryn.git"
RESULT_ROOT = "docs/evidence/operation-control-r0008-stage-results"

SOURCE_COMMIT = authority.SOURCE_COMMIT
SOURCE_TREE = authority.SOURCE_TREE
PAYLOAD_SHA256 = authority.PAYLOAD_SHA256
PAYLOAD_SIZE = authority.PAYLOAD_SIZE
PAYLOAD_FILE_COUNT = authority.PAYLOAD_FILE_COUNT
CANDIDATE = authority.CANDIDATE


class RealStageTransactionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            args,
            cwd=None if cwd is None else str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RealStageTransactionError(
            "COMMAND_OUTCOME_UNCERTAIN",
            f"command outcome uncertain: {args[0]}",
        ) from exc
    if check and result.returncode != 0:
        raise RealStageTransactionError(
            "COMMAND_FAILED",
            result.stderr.decode("utf-8", errors="replace").strip()
            or f"command failed: {args[0]}",
        )
    return result


def _private_dir(path: Path, label: str) -> Path:
    path = path.absolute()
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RealStageTransactionError(
            "PRIVATE_INPUT_ROOT_INVALID",
            f"{label} cannot be inspected",
        ) from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise RealStageTransactionError(
            "PRIVATE_INPUT_ROOT_INVALID",
            f"{label} must be a real directory",
        )
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RealStageTransactionError(
                "PRIVATE_INPUT_ROOT_INVALID",
                f"{label} must be current-user owned mode 0700",
            )
    return path


def _private_file(path: Path, label: str) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RealStageTransactionError(
            "PRIVATE_INPUT_INVALID",
            f"{label} cannot be inspected",
        ) from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise RealStageTransactionError(
            "PRIVATE_INPUT_INVALID",
            f"{label} must be a regular file",
        )
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise RealStageTransactionError(
                "PRIVATE_INPUT_INVALID",
                f"{label} must be current-user owned mode 0600",
            )
    return path


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_private_bytes_new(path: Path, raw: bytes, label: str) -> None:
    parent = _private_dir(path.parent, f"{label} parent")
    if path.exists() or path.is_symlink():
        raise RealStageTransactionError(
            "PRIVATE_INPUT_EXISTS",
            f"{label} already exists",
        )
    staging = parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(staging, flags, 0o600)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                if written <= 0:
                    raise RealStageTransactionError(
                        "PRIVATE_INPUT_WRITE_FAILED",
                        f"{label} write made no progress",
                    )
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)

        _private_file(staging, f"{label} staging file")
        if path.exists() or path.is_symlink():
            raise RealStageTransactionError(
                "PRIVATE_INPUT_EXISTS",
                f"{label} appeared before publication",
            )
        if os.name == "posix":
            os.link(staging, path, follow_symlinks=False)
            _fsync_dir(parent)
            staging.unlink()
        else:
            staging.rename(path)
        _fsync_dir(parent)
        observed = _private_file(path, label).read_bytes()
        if observed != raw:
            raise RealStageTransactionError(
                "PRIVATE_INPUT_WRITE_FAILED",
                f"{label} publication mismatch",
            )
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


def _input_path(input_root: Path, transaction_id: str) -> Path:
    transaction_id = authority._hex(transaction_id, 32, "transaction_id")
    return _private_dir(input_root, "stage input root") / (
        f"{transaction_id}.r0008.tar.gz"
    )


def _payload_identity(payload: Path, materializer: Any) -> dict[str, Any]:
    try:
        return stage._verify_payload(payload, materializer)
    except stage.StageError as exc:
        raise RealStageTransactionError(
            "PAYLOAD_INVALID",
            str(exc),
        ) from exc


def reconcile_private_input(
    *,
    input_root: Path,
    transaction_id: str,
    materializer: Any,
) -> dict[str, Any]:
    path = _input_path(input_root, transaction_id)
    if not path.exists() and not path.is_symlink():
        return {
            "state": "INPUT_ABSENT",
            "path": path.name,
            "exact": False,
        }
    try:
        _private_file(path, "stage private input")
        identity = _payload_identity(path, materializer)
    except (RealStageTransactionError, OSError):
        return {
            "state": "INPUT_FOREIGN_OR_INVALID",
            "path": path.name,
            "exact": False,
        }
    return {
        "state": "INPUT_EXACT",
        "path": path.name,
        "exact": True,
        "identity": identity,
    }


def _json_command(args: list[str], *, timeout: int = 600) -> dict[str, Any]:
    result = _run(args, timeout=timeout)
    try:
        value = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RealStageTransactionError(
            "BUILDER_OUTPUT_INVALID",
            f"command returned invalid JSON: {args[0]}",
        ) from exc
    if not isinstance(value, dict):
        raise RealStageTransactionError(
            "BUILDER_OUTPUT_INVALID",
            "payload builder returned non-object JSON",
        )
    return value


def _checkout_exact_source(
    *,
    remote_url: str,
    work: Path,
) -> Path:
    repo = work / "source"
    _run(["git", "init", "-q", str(repo)])
    _run(["git", "-C", str(repo), "config", "maintenance.auto", "false"])
    _run(["git", "-C", str(repo), "config", "gc.auto", "0"])
    _run(["git", "-C", str(repo), "config", "gc.autoPackLimit", "0"])
    _run(["git", "-C", str(repo), "remote", "add", "origin", remote_url])
    _run(
        [
            "git",
            "-C",
            str(repo),
            "fetch",
            "-q",
            "--no-tags",
            "--depth",
            "1",
            "origin",
            SOURCE_COMMIT,
        ],
        timeout=300,
    )
    _run(["git", "-C", str(repo), "checkout", "-q", "--detach", "FETCH_HEAD"])
    observed_head = _run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"]
    ).stdout.decode("ascii").strip()
    observed_tree = _run(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"]
    ).stdout.decode("ascii").strip()
    dirty = _run(
        ["git", "-C", str(repo), "status", "--porcelain"]
    ).stdout
    if observed_head != SOURCE_COMMIT:
        raise RealStageTransactionError(
            "SOURCE_IDENTITY_MISMATCH",
            "fetched source commit mismatch",
        )
    if observed_tree != SOURCE_TREE:
        raise RealStageTransactionError(
            "SOURCE_IDENTITY_MISMATCH",
            "fetched source tree mismatch",
        )
    if dirty:
        raise RealStageTransactionError(
            "SOURCE_IDENTITY_MISMATCH",
            "fetched source checkout is dirty",
        )
    return repo


def _build_exact_twice(
    *,
    source: Path,
    work: Path,
    materializer: Any,
) -> tuple[bytes, dict[str, Any]]:
    builder = source / "deploy" / "zero-based-vps" / "build_payload.py"
    first = work / "first.tar.gz"
    second = work / "second.tar.gz"
    metas: list[dict[str, Any]] = []
    for output in (first, second):
        metas.append(
            _json_command(
                [
                    sys.executable,
                    "-B",
                    str(builder),
                    "--repo-root",
                    str(source),
                    "--source-commit",
                    SOURCE_COMMIT,
                    "--output",
                    str(output),
                ]
            )
        )
    first_raw = first.read_bytes()
    second_raw = second.read_bytes()
    if first_raw != second_raw:
        raise RealStageTransactionError(
            "PAYLOAD_NONDETERMINISTIC",
            "two exact-source payload rebuilds differ",
        )
    expected = {
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }
    observed = {
        "source_commit": metas[0].get("source_commit"),
        "payload_sha256": _sha256(first_raw),
        "payload_size": len(first_raw),
        "file_count": metas[0].get("file_count"),
    }
    if observed != expected:
        raise RealStageTransactionError(
            "PAYLOAD_IDENTITY_MISMATCH",
            f"rebuilt payload identity mismatch: {observed}",
        )
    for key in expected:
        if metas[1].get(key) != metas[0].get(key):
            raise RealStageTransactionError(
                "PAYLOAD_NONDETERMINISTIC",
                "second payload metadata differs",
            )
    temp_payload = work / "verified-input.tar.gz"
    temp_payload.write_bytes(first_raw)
    verified = _payload_identity(temp_payload, materializer)
    if verified != expected:
        raise RealStageTransactionError(
            "PAYLOAD_IDENTITY_MISMATCH",
            "materializer-level payload identity mismatch",
        )
    return first_raw, expected


def acquire_exact_private_input(
    *,
    remote_url: str,
    input_root: Path,
    transaction_id: str,
    materializer: Any,
) -> dict[str, Any]:
    before = reconcile_private_input(
        input_root=input_root,
        transaction_id=transaction_id,
        materializer=materializer,
    )
    if before["state"] == "INPUT_EXACT":
        return {
            "state": "ALREADY_ACQUIRED_EXACT",
            "publication_performed": False,
            "identity": before["identity"],
            "source_commit": SOURCE_COMMIT,
            "source_tree": SOURCE_TREE,
        }
    if before["state"] != "INPUT_ABSENT":
        raise RealStageTransactionError(
            "PRIVATE_INPUT_CONFLICT",
            "existing private stage input is foreign/invalid",
        )

    input_path = _input_path(input_root, transaction_id)
    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0008-source-acquisition-"
    ) as td:
        work = Path(td)
        source = _checkout_exact_source(remote_url=remote_url, work=work)
        raw, identity = _build_exact_twice(
            source=source,
            work=work,
            materializer=materializer,
        )
        immediate = reconcile_private_input(
            input_root=input_root,
            transaction_id=transaction_id,
            materializer=materializer,
        )
        if immediate["state"] != "INPUT_ABSENT":
            raise RealStageTransactionError(
                "PRIVATE_INPUT_CONFLICT",
                "private input state changed before publication",
            )
        _atomic_private_bytes_new(
            input_path,
            raw,
            "stage private input",
        )

    after = reconcile_private_input(
        input_root=input_root,
        transaction_id=transaction_id,
        materializer=materializer,
    )
    if after["state"] != "INPUT_EXACT" or after["identity"] != identity:
        raise RealStageTransactionError(
            "PRIVATE_INPUT_POSTVERIFY_FAILED",
            "published private input failed exact verification",
        )
    return {
        "state": "ACQUIRED_EXACT",
        "publication_performed": True,
        "identity": identity,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
    }


def boundary_evidence_from_live(
    boundary: dict[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    projection = execution._live_projection(boundary)
    value = {
        "schema": authority.BOUNDARY_SCHEMA,
        "observed_at_utc": observed_at_utc,
        "conclusion": "PASS",
        **projection,
        "production_mutations_performed": False,
        "drive_mutations_performed": False,
    }
    try:
        return authority.validate_boundary_evidence(value)
    except authority.StageAuthorityError as exc:
        raise RealStageTransactionError(exc.code, str(exc)) from exc


def _result_path(transaction_id: str) -> str:
    transaction_id = authority._hex(transaction_id, 32, "transaction_id")
    return f"{RESULT_ROOT}/{transaction_id}.json"


def render_result_checkpoint(
    *,
    issued: authority.IssuedStageAuthorization,
    input_identity: dict[str, Any],
    completed: dict[str, Any],
) -> dict[str, Any]:
    if completed.get("release_state") != "STAGED_EXACT":
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "completed execution does not prove STAGED_EXACT",
        )
    if completed.get("transaction_id") != issued.transaction_id:
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "completed execution transaction mismatch",
        )
    if completed.get("activation_authorized") is not False:
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "completed execution widened activation authority",
        )
    provenance = issued.provenance
    if completed.get("authority_commit") != provenance["authority_commit"]:
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "completed execution authority commit mismatch",
        )
    if completed.get("authority_git_blob") != provenance["authority_git_blob"]:
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "completed execution authority blob mismatch",
        )
    if completed.get("source_commit") != SOURCE_COMMIT:
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "completed execution source mismatch",
        )
    if completed.get("payload_sha256") != PAYLOAD_SHA256:
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "completed execution payload mismatch",
        )
    expected_input = {
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }
    if input_identity != expected_input:
        raise RealStageTransactionError(
            "RESULT_INVALID",
            "private input identity mismatch",
        )
    return {
        "schema": RESULT_SCHEMA,
        "transaction_id": issued.transaction_id,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "authority_commit": provenance["authority_commit"],
        "authority_path": provenance["authority_path"],
        "authority_git_blob": provenance["authority_git_blob"],
        "authority_sha256": provenance["authority_sha256"],
        "issuer_checkpoint": provenance["authority_parent_checkpoint"],
        "boundary_evidence_path": provenance["boundary_evidence_path"],
        "boundary_evidence_git_blob": provenance["boundary_evidence_git_blob"],
        "boundary_evidence_sha256": provenance["boundary_evidence_sha256"],
        "prepared_sha256": completed["prepared_sha256"],
        "stage_state": completed["stage_state"],
        "release_state": "STAGED_EXACT",
        "post_reconcile": "PASS",
        "activation_authorized": False,
        "drive_content_mutation_performed": False,
        "legacy_hub_mutation_performed": False,
    }


def commit_result_checkpoint(
    repository_root: Path,
    *,
    issued: authority.IssuedStageAuthorization,
    result: dict[str, Any],
) -> dict[str, Any]:
    root = repository_root.resolve()
    authority_commit = issued.provenance["authority_commit"]
    branch_head = authority._commit(root, f"refs/heads/{authority.BRANCH}")
    ancestor = authority._git(
        root,
        ["merge-base", "--is-ancestor", authority_commit, branch_head],
        check=False,
    )
    if ancestor.returncode != 0:
        raise RealStageTransactionError(
            "AUTHORITY_BRANCH_DRIFT",
            "authority commit is no longer on authoritative branch",
        )

    path = _result_path(issued.transaction_id)
    exists = authority._git(
        root,
        ["cat-file", "-e", f"{branch_head}:{path}"],
        check=False,
    )
    if exists.returncode == 0:
        raw = authority._show(root, branch_head, path)
        try:
            existing = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RealStageTransactionError(
                "RESULT_CHECKPOINT_CONFLICT",
                "existing result checkpoint is invalid JSON",
            ) from exc
        if raw != _canonical(existing) or existing != result:
            raise RealStageTransactionError(
                "RESULT_CHECKPOINT_CONFLICT",
                "existing result checkpoint conflicts with exact transaction result",
            )
        return {
            "state": "RESULT_ALREADY_CHECKPOINTED_EXACT",
            "commit": branch_head,
            "path": path,
            "blob": authority._blob(root, branch_head, path),
            "sha256": _sha256(raw),
            "write_performed": False,
        }

    authority._write_canonical(root, path, result)
    result_commit = authority._commit_all(
        root,
        f"record r0008 stage result {issued.transaction_id}",
    )
    parent = authority._commit(root, f"{result_commit}^1")
    if parent != branch_head:
        raise RealStageTransactionError(
            "RESULT_COMMIT_INVALID",
            "result checkpoint parent changed unexpectedly",
        )
    diff = authority._git(
        root,
        [
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            parent,
            result_commit,
        ],
    ).stdout.decode("utf-8").splitlines()
    if diff != [f"A\t{path}"]:
        raise RealStageTransactionError(
            "RESULT_COMMIT_INVALID",
            "result checkpoint commit must add exactly one result path",
        )
    raw = authority._show(root, result_commit, path)
    if raw != _canonical(result):
        raise RealStageTransactionError(
            "RESULT_COMMIT_INVALID",
            "result checkpoint bytes mismatch",
        )
    return {
        "state": "RESULT_CHECKPOINTED_EXACT",
        "commit": result_commit,
        "path": path,
        "blob": authority._blob(root, result_commit, path),
        "sha256": _sha256(raw),
        "write_performed": True,
    }


def _init_transaction_authority(
    work: Path,
    *,
    boundary: dict[str, Any],
    transaction_id: str,
) -> tuple[Path, authority.IssuedStageAuthorization, dict[str, Any]]:
    repo = work / f"transaction-authority-{transaction_id}"
    repo.mkdir()
    authority._init_repo(repo)

    evidence_path = (
        "docs/evidence/operation-control-r0008-stage-boundary/"
        f"{transaction_id}.json"
    )
    evidence = boundary_evidence_from_live(
        boundary,
        observed_at_utc="2026-09-22T00:00:00Z",
    )
    authority._write_canonical(repo, evidence_path, evidence)
    checkpoint = authority._commit_all(
        repo,
        "checkpoint fresh r0008 stage boundary evidence",
    )
    evidence_blob = authority._blob(repo, checkpoint, evidence_path)
    evidence_raw = authority._show(repo, checkpoint, evidence_path)

    record = issuer.render_record(
        transaction_id=transaction_id,
        issuer_checkpoint=checkpoint,
        boundary_evidence_path=evidence_path,
        boundary_evidence_git_blob=evidence_blob,
        boundary_evidence_sha256=_sha256(evidence_raw),
    )
    path = authority.authority_path(transaction_id)
    authority._write_canonical(repo, path, record)
    authority_commit = authority._commit_all(
        repo,
        "issue one-shot r0008 stage authority",
    )
    authority_blob = authority._blob(repo, authority_commit, path)
    issued = authority.resolve_git_authorization(
        repo,
        authority_commit=authority_commit,
        authority_path_value=path,
        expected_authority_blob=authority_blob,
    )
    return repo, issued, {
        "evidence_checkpoint": checkpoint,
        "evidence_path": evidence_path,
        "evidence_blob": evidence_blob,
        "evidence_sha256": _sha256(evidence_raw),
        "authority_commit": authority_commit,
        "authority_path": path,
        "authority_blob": authority_blob,
    }


def qualify(repository_root: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    source_commit = authority._commit(repository_root, SOURCE_COMMIT)
    if source_commit != SOURCE_COMMIT:
        raise RealStageTransactionError(
            "QUALIFICATION_SOURCE_MISSING",
            "frozen r0008 source is not available in qualification repository",
        )

    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0008-real-stage-transaction-"
    ) as td:
        work = Path(td)
        frozen_source = production.prep._checkout_frozen(work)
        production.prep._rebuild_frozen(frozen_source, work)
        materializer = production._load_exact_materializer(
            frozen_source / "deploy" / "zero-based-vps" / "materialize_payload.py"
        )
        boundary = production._qualification_boundary()
        transaction_id = "70000000000000000000000000000021"

        auth_repo, issued, auth_meta = _init_transaction_authority(
            work,
            boundary=boundary,
            transaction_id=transaction_id,
        )

        scenarios: dict[str, str] = {}

        # Evidence checkpoint exists before authority; authority commit is isolated.
        if issued.provenance["authority_parent_checkpoint"] != auth_meta["evidence_checkpoint"]:
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "authority is not bound to evidence checkpoint",
            )
        scenarios["evidence_then_authority"] = "PASS"

        # Branch drift invalidates authority resolution.
        authority._git(
            auth_repo,
            ["branch", "qualification-authority-tip", auth_meta["authority_commit"]],
        )
        authority._git(
            auth_repo,
            ["reset", "--hard", "-q", auth_meta["evidence_checkpoint"]],
        )
        try:
            authority.resolve_git_authorization(
                auth_repo,
                authority_commit=auth_meta["authority_commit"],
                authority_path_value=auth_meta["authority_path"],
                expected_authority_blob=auth_meta["authority_blob"],
            )
        except authority.StageAuthorityError as exc:
            if exc.code != "AUTHORITY_NOT_ON_BRANCH":
                raise
        else:
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "authority branch drift was accepted",
            )
        scenarios["authority_branch_drift"] = "FAIL_CLOSED"
        authority._git(
            auth_repo,
            ["reset", "--hard", "-q", "qualification-authority-tip"],
        )
        issued = authority.resolve_git_authorization(
            auth_repo,
            authority_commit=auth_meta["authority_commit"],
            authority_path_value=auth_meta["authority_path"],
            expected_authority_blob=auth_meta["authority_blob"],
        )

        # Autonomous exact-source acquisition into private input.
        input_root = work / "private-input"
        input_root.mkdir()
        if os.name == "posix":
            os.chmod(input_root, 0o700)
        acquired = acquire_exact_private_input(
            remote_url=str(repository_root),
            input_root=input_root,
            transaction_id=transaction_id,
            materializer=materializer,
        )
        if acquired["state"] != "ACQUIRED_EXACT":
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "exact private input was not acquired",
            )
        scenarios["autonomous_exact_acquisition"] = "ACQUIRED_EXACT"

        replay_acquire = acquire_exact_private_input(
            remote_url=str(repository_root),
            input_root=input_root,
            transaction_id=transaction_id,
            materializer=materializer,
        )
        if replay_acquire["state"] != "ALREADY_ACQUIRED_EXACT":
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "exact input replay rebuilt/replaced input",
            )
        scenarios["acquisition_replay"] = "ALREADY_ACQUIRED_EXACT"

        # Foreign private input is fail-closed and untouched.
        foreign_root = work / "foreign-input"
        foreign_root.mkdir()
        if os.name == "posix":
            os.chmod(foreign_root, 0o700)
        foreign_path = _input_path(foreign_root, transaction_id)
        _atomic_private_bytes_new(
            foreign_path,
            b"FOREIGN\n",
            "foreign stage input",
        )
        before_foreign = foreign_path.read_bytes()
        try:
            acquire_exact_private_input(
                remote_url=str(repository_root),
                input_root=foreign_root,
                transaction_id=transaction_id,
                materializer=materializer,
            )
        except RealStageTransactionError as exc:
            if exc.code != "PRIVATE_INPUT_CONFLICT":
                raise
        else:
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "foreign private input was accepted",
            )
        if foreign_path.read_bytes() != before_foreign:
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "foreign private input was modified",
            )
        scenarios["foreign_private_input"] = "FAIL_CLOSED_UNTOUCHED"

        # Execute the already-qualified one-shot protocol using the exact private input.
        releases = work / "releases"
        releases.mkdir()
        witness_root = work / "witness"
        witness_root.mkdir()
        if os.name == "posix":
            os.chmod(witness_root, 0o700)
        payload_path = _input_path(input_root, transaction_id)
        completed = execution.execute_once(
            repository_root=auth_repo,
            issued=issued,
            payload=payload_path,
            releases_root=releases,
            witness_root=witness_root,
            materializer=materializer,
            boundary_probe=execution._SequenceProbe([boundary] * 24),
        )
        if completed.get("execution_state") != "COMPLETED_EXACT":
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "qualified execution did not complete exactly",
            )
        scenarios["one_shot_execution"] = "COMPLETED_EXACT"

        # Durable result checkpoint is a new isolated path after authority lineage.
        result = render_result_checkpoint(
            issued=issued,
            input_identity=acquired["identity"],
            completed=completed,
        )
        checkpointed = commit_result_checkpoint(
            auth_repo,
            issued=issued,
            result=result,
        )
        if checkpointed["state"] != "RESULT_CHECKPOINTED_EXACT":
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "result checkpoint was not committed",
            )
        scenarios["result_checkpoint"] = "RESULT_CHECKPOINTED_EXACT"

        checkpoint_replay = commit_result_checkpoint(
            auth_repo,
            issued=issued,
            result=result,
        )
        if checkpoint_replay["state"] != "RESULT_ALREADY_CHECKPOINTED_EXACT":
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "result checkpoint replay is not idempotent",
            )
        scenarios["result_replay"] = "RESULT_ALREADY_CHECKPOINTED_EXACT"

        # Foreign result path conflicts instead of being overwritten.
        conflict_id = "70000000000000000000000000000022"
        conflict_repo, conflict_issued, _ = _init_transaction_authority(
            work,
            boundary=boundary,
            transaction_id=conflict_id,
        )
        conflict_completed = {
            **completed,
            "transaction_id": conflict_id,
            "authority_commit": conflict_issued.provenance["authority_commit"],
            "authority_git_blob": conflict_issued.provenance["authority_git_blob"],
        }
        conflict_result = render_result_checkpoint(
            issued=conflict_issued,
            input_identity=acquired["identity"],
            completed=conflict_completed,
        )
        conflict_path = _result_path(conflict_id)
        authority._write_canonical(
            conflict_repo,
            conflict_path,
            {"schema": RESULT_SCHEMA, "foreign": True},
        )
        authority._commit_all(conflict_repo, "foreign result checkpoint")
        try:
            commit_result_checkpoint(
                conflict_repo,
                issued=conflict_issued,
                result=conflict_result,
            )
        except RealStageTransactionError as exc:
            if exc.code != "RESULT_CHECKPOINT_CONFLICT":
                raise
        else:
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "foreign result checkpoint was accepted",
            )
        scenarios["foreign_result_checkpoint"] = "FAIL_CLOSED"

        # Stale live boundary cannot reach PREPARED even with valid authority/input.
        stale_releases = work / "stale-releases"
        stale_releases.mkdir()
        stale_witness = work / "stale-witness"
        stale_witness.mkdir()
        if os.name == "posix":
            os.chmod(stale_witness, 0o700)
        changed = json.loads(_canonical(boundary).decode("utf-8"))
        changed["services"]["writer"] = {
            "active_state": "ACTIVE",
            "main_pid": 999,
        }
        try:
            execution.execute_once(
                repository_root=auth_repo,
                issued=issued,
                payload=payload_path,
                releases_root=stale_releases,
                witness_root=stale_witness,
                materializer=materializer,
                boundary_probe=execution._SequenceProbe([changed] * 12),
            )
        except execution.StageExecutionError as exc:
            if exc.code != "STALE_OR_MISMATCHED_BOUNDARY_EVIDENCE":
                raise
        else:
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "stale boundary reached execution",
            )
        prepared_path, _ = execution._witness_paths(
            stale_witness,
            transaction_id,
        )
        if prepared_path.exists():
            raise RealStageTransactionError(
                "QUALIFICATION_FAILED",
                "stale boundary wrote PREPARED",
            )
        scenarios["stale_boundary"] = "FAIL_BEFORE_PREPARED"

    expected = {
        "evidence_then_authority": "PASS",
        "authority_branch_drift": "FAIL_CLOSED",
        "autonomous_exact_acquisition": "ACQUIRED_EXACT",
        "acquisition_replay": "ALREADY_ACQUIRED_EXACT",
        "foreign_private_input": "FAIL_CLOSED_UNTOUCHED",
        "one_shot_execution": "COMPLETED_EXACT",
        "result_checkpoint": "RESULT_CHECKPOINTED_EXACT",
        "result_replay": "RESULT_ALREADY_CHECKPOINTED_EXACT",
        "foreign_result_checkpoint": "FAIL_CLOSED",
        "stale_boundary": "FAIL_BEFORE_PREPARED",
    }
    if scenarios != expected:
        raise RealStageTransactionError(
            "QUALIFICATION_FAILED",
            f"real-stage transaction scenario mismatch: {scenarios}",
        )

    return {
        "schema": TRANSACTION_SCHEMA,
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "production_repository_url": REPOSITORY_URL,
        "acquisition_model": "VPS_GIT_FETCH_EXACT_COMMIT_VERIFY_TREE_REBUILD_TWICE",
        "maintainer_workstation_transport_required": False,
        "private_input_model": "TRANSACTION_BOUND_0600_IMMUTABLE_INPUT",
        "boundary_evidence_checkpoint_before_authority": True,
        "authority_commit_isolated": True,
        "authority_git_blob_captured": True,
        "payload_verified_before_prepared": True,
        "result_checkpoint_after_completed": True,
        "result_checkpoint_isolated": True,
        "physical_commit_authority": "EXACT_IMMUTABLE_RELEASE_DIRECTORY",
        "activation_separate_transaction": True,
        "real_authorization_record_issued": False,
        "real_vps_input_acquired": False,
        "real_vps_stage_performed": False,
        "production_mutation_allowed": False,
        "drive_content_mutation_allowed": False,
        "production_qualified": False,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "next_action": "FRESH_REAL_VPS_PRE_APPLY_RECONCILE_BEFORE_STAGE_AUTHORIZATION",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0008-real-stage-transaction"
    )
    parser.add_argument("command", choices=("qualify",))
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = qualify(args.repository_root)
    except (
        RealStageTransactionError,
        authority.StageAuthorityError,
        execution.StageExecutionError,
        production.ProductionStagePrepError,
        stage.StageError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-r0008-real-stage-transaction-failure.v1",
                    "error_class": type(exc).__name__,
                    "error_code": getattr(exc, "code", "OS_ERROR"),
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    raw = _canonical(value)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
