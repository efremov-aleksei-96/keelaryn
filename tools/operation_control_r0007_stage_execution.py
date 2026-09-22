from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


authority = _load(
    "keelaryn_r0007_execution_authority",
    Path(__file__).with_name("operation_control_r0007_stage_authority.py"),
)
issuer = _load(
    "keelaryn_r0007_execution_issuer",
    Path(__file__).with_name("operation_control_r0007_stage_authority_issue.py"),
)
production = _load(
    "keelaryn_r0007_execution_production_stage",
    Path(__file__).with_name("operation_control_r0007_production_stage.py"),
)
stage = production.stage

GATE_REVISION = "operation-control-r0007-stage-execution-gate-r0001"
PREPARED_SCHEMA = "keelaryn.operation-control-r0007-stage-execution-prepared.v1"
COMPLETED_SCHEMA = "keelaryn.operation-control-r0007-stage-execution-completed.v1"
WITNESS_SCHEMA = "keelaryn.operation-control-r0007-stage-execution-witness.v1"


class StageExecutionError(RuntimeError):
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


def _private_dir(path: Path, label: str) -> Path:
    path = path.absolute()
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise StageExecutionError("WITNESS_ROOT_INVALID", f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise StageExecutionError("WITNESS_ROOT_INVALID", f"{label} must be a real directory")
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise StageExecutionError(
                "WITNESS_ROOT_INVALID",
                f"{label} must be current-user owned mode 0700",
            )
    return path


def _private_file(path: Path, label: str) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise StageExecutionError("WITNESS_INVALID", f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise StageExecutionError("WITNESS_INVALID", f"{label} must be one regular file")
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise StageExecutionError(
                "WITNESS_INVALID",
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


def _write_immutable(path: Path, value: dict[str, Any], label: str) -> None:
    parent = _private_dir(path.parent, f"{label} parent")
    if path.exists() or path.is_symlink():
        raise StageExecutionError("WITNESS_EXISTS", f"{label} already exists")
    raw = _canonical(value)
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
                    raise StageExecutionError(
                        "WITNESS_WRITE_FAILED",
                        f"{label} write made no progress",
                    )
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        _private_file(staging, f"{label} staging file")
        if path.exists() or path.is_symlink():
            raise StageExecutionError("WITNESS_EXISTS", f"{label} appeared before publication")
        if os.name == "posix":
            os.link(staging, path, follow_symlinks=False)
            _fsync_dir(parent)
            staging.unlink()
        else:
            staging.rename(path)
        _fsync_dir(parent)
        observed = _private_file(path, label).read_bytes()
        if observed != raw:
            raise StageExecutionError("WITNESS_WRITE_FAILED", f"{label} publication mismatch")
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


def _read_canonical(path: Path, label: str) -> dict[str, Any]:
    raw = _private_file(path, label).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageExecutionError("WITNESS_INVALID", f"{label} is not valid JSON") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise StageExecutionError("WITNESS_INVALID", f"{label} is not canonical JSON")
    return value


def _witness_paths(root: Path, transaction_id: str) -> tuple[Path, Path]:
    transaction_id = authority._hex(transaction_id, 32, "transaction_id")
    root = _private_dir(root, "operation-stage witness root")
    return (
        root / f"{transaction_id}.PREPARED.json",
        root / f"{transaction_id}.COMPLETED.json",
    )


def _authority_evidence(
    repository_root: Path,
    issued: authority.IssuedStageAuthorization,
) -> dict[str, Any]:
    record = issued.record
    provenance = issued.provenance
    checkpoint = provenance["authority_parent_checkpoint"]
    path = record["boundary_evidence_path"]
    raw = authority._show(repository_root.resolve(), checkpoint, path)
    if _sha256(raw) != record["boundary_evidence_sha256"]:
        raise StageExecutionError(
            "BOUNDARY_EVIDENCE_MISMATCH",
            "authority-bound boundary evidence SHA mismatch",
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageExecutionError(
            "BOUNDARY_EVIDENCE_MISMATCH",
            "authority-bound boundary evidence is not JSON",
        ) from exc
    if raw != _canonical(value):
        raise StageExecutionError(
            "BOUNDARY_EVIDENCE_MISMATCH",
            "authority-bound boundary evidence is not canonical",
        )
    try:
        return authority.validate_boundary_evidence(value)
    except authority.StageAuthorityError as exc:
        raise StageExecutionError(exc.code, str(exc)) from exc


def _live_projection(boundary: dict[str, Any]) -> dict[str, Any]:
    try:
        hub = boundary["legacy_hub"]
        writer = boundary["services"]["writer"]
        credential = boundary["credential"]
        value = {
            "production_source_commit": boundary["production_source_commit"],
            "control_source_commit": boundary["control_source_commit"],
            "legacy_hub_status": hub["status"],
            "legacy_hub_transaction_id": hub["transaction_id"],
            "selector_role": hub["selector_role"],
            "writer": (
                "INACTIVE_MAINPID_0"
                if writer["active_state"] == "INACTIVE" and writer["main_pid"] == 0
                else f'{writer["active_state"]}_MAINPID_{writer["main_pid"]}'
            ),
            "mutation_inhibit_authority_matches": hub["mutation_inhibit"]["authority_matches"],
            "credential_sha256": credential["sha256"],
            "legacy_hub_authority_scope": hub["authority_scope"],
        }
    except (KeyError, TypeError) as exc:
        raise StageExecutionError(
            "LIVE_BOUNDARY_INVALID",
            "live boundary does not expose required stage projection",
        ) from exc
    return value


def _evidence_projection(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "production_source_commit": evidence["production_source_commit"],
        "control_source_commit": evidence["control_source_commit"],
        "legacy_hub_status": evidence["legacy_hub_status"],
        "legacy_hub_transaction_id": evidence["legacy_hub_transaction_id"],
        "selector_role": evidence["selector_role"],
        "writer": evidence["writer"],
        "mutation_inhibit_authority_matches": evidence[
            "mutation_inhibit_authority_matches"
        ],
        "credential_sha256": evidence["credential_sha256"],
        "legacy_hub_authority_scope": evidence["legacy_hub_authority_scope"],
    }


def _stable_live(
    boundary_probe: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    first = production._snapshot(boundary_probe)
    second = production._snapshot(boundary_probe)
    if not production._same(first, second):
        raise StageExecutionError(
            "LIVE_BOUNDARY_DRIFT",
            "live boundary changed during stage-execution precheck",
        )
    return second, _live_projection(second)


def _prepared_value(
    issued: authority.IssuedStageAuthorization,
    payload_identity: dict[str, Any],
    evidence: dict[str, Any],
    live_projection: dict[str, Any],
) -> dict[str, Any]:
    provenance = issued.provenance
    return {
        "schema": PREPARED_SCHEMA,
        "transaction_id": issued.transaction_id,
        "candidate": authority.CANDIDATE,
        "source_commit": authority.SOURCE_COMMIT,
        "source_tree": authority.SOURCE_TREE,
        "payload_sha256": authority.PAYLOAD_SHA256,
        "payload_size": authority.PAYLOAD_SIZE,
        "file_count": authority.PAYLOAD_FILE_COUNT,
        "authority_commit": provenance["authority_commit"],
        "authority_path": provenance["authority_path"],
        "authority_git_blob": provenance["authority_git_blob"],
        "authority_sha256": provenance["authority_sha256"],
        "issuer_checkpoint": provenance["authority_parent_checkpoint"],
        "boundary_evidence_path": provenance["boundary_evidence_path"],
        "boundary_evidence_git_blob": provenance["boundary_evidence_git_blob"],
        "boundary_evidence_sha256": provenance["boundary_evidence_sha256"],
        "boundary_observed_at_utc": evidence["observed_at_utc"],
        "live_projection": live_projection,
        "payload_identity": payload_identity,
        "scope": authority.SCOPE,
        "activation_authorized": False,
    }


def _completed_value(
    prepared: dict[str, Any],
    *,
    stage_state: str,
    replay: bool,
) -> dict[str, Any]:
    return {
        "schema": COMPLETED_SCHEMA,
        "transaction_id": prepared["transaction_id"],
        "prepared_sha256": _sha256(_canonical(prepared)),
        "authority_commit": prepared["authority_commit"],
        "authority_git_blob": prepared["authority_git_blob"],
        "source_commit": prepared["source_commit"],
        "payload_sha256": prepared["payload_sha256"],
        "stage_state": stage_state,
        "release_state": "STAGED_EXACT",
        "post_reconcile": "PASS",
        "activation_authorized": False,
        "release_deletion_allowed": False,
        "blind_retry_allowed": False,
        "exact_replay": replay,
    }


def _expected_prepared(
    *,
    repository_root: Path,
    issued: authority.IssuedStageAuthorization,
    payload: Path,
    materializer: Any,
    boundary_probe: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        stage_auth = authority.require_issued_authorization(issued)
    except authority.StageAuthorityError as exc:
        raise StageExecutionError(exc.code, str(exc)) from exc
    try:
        production.validate_authorization(stage_auth)
    except production.ProductionStagePrepError as exc:
        raise StageExecutionError(exc.code, str(exc)) from exc

    evidence = _authority_evidence(repository_root, issued)
    live_boundary, live_projection = _stable_live(boundary_probe)
    if _evidence_projection(evidence) != live_projection:
        raise StageExecutionError(
            "STALE_OR_MISMATCHED_BOUNDARY_EVIDENCE",
            "authority-bound evidence does not match fresh live runtime boundary",
        )

    try:
        payload_identity = stage._verify_payload(payload, materializer)
    except stage.StageError as exc:
        raise StageExecutionError("PAYLOAD_INVALID", str(exc)) from exc

    prepared = _prepared_value(
        issued,
        payload_identity,
        evidence,
        live_projection,
    )
    return prepared, live_boundary


def reconcile_execution(
    *,
    repository_root: Path,
    issued: authority.IssuedStageAuthorization,
    payload: Path,
    releases_root: Path,
    witness_root: Path,
    materializer: Any,
    boundary_probe: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    prepared_expected, _ = _expected_prepared(
        repository_root=repository_root,
        issued=issued,
        payload=payload,
        materializer=materializer,
        boundary_probe=boundary_probe,
    )
    prepared_path, completed_path = _witness_paths(
        witness_root,
        issued.transaction_id,
    )
    release = stage.reconcile_stage(releases_root, materializer)

    prepared_exists = prepared_path.exists() or prepared_path.is_symlink()
    completed_exists = completed_path.exists() or completed_path.is_symlink()

    if completed_exists and not prepared_exists:
        raise StageExecutionError(
            "COMPLETED_WITHOUT_PREPARED",
            "completed stage witness exists without PREPARED witness",
        )

    if prepared_exists:
        prepared = _read_canonical(prepared_path, "stage PREPARED witness")
        if prepared != prepared_expected:
            raise StageExecutionError(
                "PREPARED_WITNESS_CONFLICT",
                "existing PREPARED witness does not match exact authority/payload/boundary",
            )
    else:
        prepared = None

    if completed_exists:
        completed = _read_canonical(completed_path, "stage COMPLETED witness")
        allowed_states = {
            "STAGED_EXACT",
            "ALREADY_STAGED_EXACT",
            "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY",
            "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED",
            "RECOVERED_STAGED_EXACT",
        }
        if (
            completed.get("schema") != COMPLETED_SCHEMA
            or completed.get("transaction_id") != issued.transaction_id
            or prepared is None
            or completed.get("prepared_sha256") != _sha256(_canonical(prepared))
            or completed.get("authority_commit") != prepared["authority_commit"]
            or completed.get("authority_git_blob") != prepared["authority_git_blob"]
            or completed.get("source_commit") != authority.SOURCE_COMMIT
            or completed.get("payload_sha256") != authority.PAYLOAD_SHA256
            or completed.get("stage_state") not in allowed_states
            or completed.get("release_state") != "STAGED_EXACT"
            or completed.get("post_reconcile") != "PASS"
            or completed.get("activation_authorized") is not False
            or completed.get("release_deletion_allowed") is not False
            or completed.get("blind_retry_allowed") is not False
            or not isinstance(completed.get("exact_replay"), bool)
        ):
            raise StageExecutionError(
                "COMPLETED_WITNESS_CONFLICT",
                "existing COMPLETED witness conflicts with exact stage transaction",
            )
        if release["state"] != "STAGED_EXACT":
            raise StageExecutionError(
                "COMPLETED_RELEASE_CONFLICT",
                "COMPLETED witness exists but exact staged release is not present",
            )
        return {
            "schema": WITNESS_SCHEMA,
            "state": "COMPLETED_EXACT",
            "transaction_id": issued.transaction_id,
            "release_state": release["state"],
            "prepared": True,
            "completed": True,
            "production_mutations_performed": False,
            "drive_mutations_performed": False,
        }

    if prepared is None:
        if release["state"] == "STAGED_EXACT":
            raise StageExecutionError(
                "UNATTRIBUTED_STAGED_RELEASE",
                "exact staged release exists without matching PREPARED witness",
            )
        if release["state"] != "NOT_STAGED":
            raise StageExecutionError(
                release["state"],
                "release state requires reconciliation before stage execution",
            )
        return {
            "schema": WITNESS_SCHEMA,
            "state": "NEW",
            "transaction_id": issued.transaction_id,
            "release_state": release["state"],
            "prepared": False,
            "completed": False,
            "production_mutations_performed": False,
            "drive_mutations_performed": False,
        }

    if release["state"] == "STAGED_EXACT":
        return {
            "schema": WITNESS_SCHEMA,
            "state": "PUBLICATION_COMMITTED_RECEIPT_MISSING",
            "transaction_id": issued.transaction_id,
            "release_state": release["state"],
            "prepared": True,
            "completed": False,
            "production_mutations_performed": False,
            "drive_mutations_performed": False,
        }
    if release["state"] == "NOT_STAGED":
        return {
            "schema": WITNESS_SCHEMA,
            "state": "PREPARED_NOT_STAGED_RECONCILE_REQUIRED",
            "transaction_id": issued.transaction_id,
            "release_state": release["state"],
            "prepared": True,
            "completed": False,
            "production_mutations_performed": False,
            "drive_mutations_performed": False,
        }
    raise StageExecutionError(
        release["state"],
        "prepared stage transaction has a non-recoverable release state",
    )


def execute_once(
    *,
    repository_root: Path,
    issued: authority.IssuedStageAuthorization,
    payload: Path,
    releases_root: Path,
    witness_root: Path,
    materializer: Any,
    boundary_probe: Callable[[], dict[str, Any]],
    materialize_call: Callable[..., dict[str, Any]] | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    state_before = reconcile_execution(
        repository_root=repository_root,
        issued=issued,
        payload=payload,
        releases_root=releases_root,
        witness_root=witness_root,
        materializer=materializer,
        boundary_probe=boundary_probe,
    )
    prepared_expected, _ = _expected_prepared(
        repository_root=repository_root,
        issued=issued,
        payload=payload,
        materializer=materializer,
        boundary_probe=boundary_probe,
    )
    prepared_path, completed_path = _witness_paths(
        witness_root,
        issued.transaction_id,
    )

    if state_before["state"] == "COMPLETED_EXACT":
        completed = _read_canonical(completed_path, "stage COMPLETED witness")
        return {
            **completed,
            "execution_state": "IDEMPOTENT_COMPLETED_EXACT",
        }

    if state_before["state"] == "PREPARED_NOT_STAGED_RECONCILE_REQUIRED":
        raise StageExecutionError(
            "PREPARED_NOT_STAGED_RECONCILE_REQUIRED",
            "PREPARED witness exists without staged release; do not retry blindly",
        )

    if state_before["state"] == "PUBLICATION_COMMITTED_RECEIPT_MISSING":
        post = production.reconcile_production_stage(
            releases_root=releases_root,
            materializer=materializer,
            boundary_probe=boundary_probe,
        )
        if post["release"]["state"] != "STAGED_EXACT":
            raise StageExecutionError(
                "POST_STAGE_RECONCILE_FAILED",
                "recovery did not confirm exact staged release",
            )
        completed = _completed_value(
            prepared_expected,
            stage_state="RECOVERED_STAGED_EXACT",
            replay=True,
        )
        _write_immutable(
            completed_path,
            completed,
            "stage COMPLETED witness",
        )
        return {
            **completed,
            "execution_state": "RECOVERED_COMPLETED_EXACT",
        }

    if state_before["state"] != "NEW":
        raise StageExecutionError(
            "EXECUTION_STATE_INVALID",
            f"cannot execute stage from state {state_before['state']}",
        )

    _write_immutable(
        prepared_path,
        prepared_expected,
        "stage PREPARED witness",
    )
    if fault_hook is not None:
        fault_hook("after_prepared")

    stage_auth = authority.require_issued_authorization(issued)
    try:
        result = production.execute_authorized_stage(
            payload=payload,
            releases_root=releases_root,
            materializer=materializer,
            authorization=stage_auth,
            boundary_probe=boundary_probe,
            materialize_call=materialize_call,
        )
    except production.ProductionStagePrepError as exc:
        raise StageExecutionError(exc.code, str(exc)) from exc

    if fault_hook is not None:
        fault_hook("after_stage_before_completed")

    post = production.reconcile_production_stage(
        releases_root=releases_root,
        materializer=materializer,
        boundary_probe=boundary_probe,
    )
    if post["release"]["state"] != "STAGED_EXACT":
        raise StageExecutionError(
            "POST_STAGE_RECONCILE_FAILED",
            "post-stage reconcile did not confirm exact staged release",
        )
    completed = _completed_value(
        prepared_expected,
        stage_state=result["state"],
        replay=False,
    )
    _write_immutable(
        completed_path,
        completed,
        "stage COMPLETED witness",
    )
    return {
        **completed,
        "execution_state": "COMPLETED_EXACT",
    }


def _init_git_authority(work: Path) -> tuple[Path, authority.IssuedStageAuthorization]:
    repo = work / "authority-repo"
    repo.mkdir()
    authority._init_repo(repo)
    evidence_path = "docs/evidence/R0007_STAGE_EXECUTION_QUALIFICATION_BOUNDARY.json"
    evidence = authority.qualification_boundary_evidence()
    authority._write_canonical(repo, evidence_path, evidence)
    checkpoint = authority._commit_all(repo, "qualification fresh boundary evidence")
    evidence_blob = authority._blob(repo, checkpoint, evidence_path)
    evidence_raw = authority._show(repo, checkpoint, evidence_path)
    transaction_id = "70000000000000000000000000000011"
    record = issuer.render_record(
        transaction_id=transaction_id,
        issuer_checkpoint=checkpoint,
        boundary_evidence_path=evidence_path,
        boundary_evidence_git_blob=evidence_blob,
        boundary_evidence_sha256=_sha256(evidence_raw),
    )
    path = authority.authority_path(transaction_id)
    authority._write_canonical(repo, path, record)
    authority_commit = authority._commit_all(repo, "issue qualification stage authority")
    authority_blob = authority._blob(repo, authority_commit, path)
    issued = authority.resolve_git_authorization(
        repo,
        authority_commit=authority_commit,
        authority_path_value=path,
        expected_authority_blob=authority_blob,
    )
    return repo, issued


class _SequenceProbe:
    def __init__(self, values: list[dict[str, Any]]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> dict[str, Any]:
        if self.index >= len(self.values):
            return self.values[-1]
        value = self.values[self.index]
        self.index += 1
        return value


def _witness_root(path: Path) -> Path:
    path.mkdir()
    if os.name == "posix":
        os.chmod(path, 0o700)
    return path


def qualify() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0007-stage-execution-"
    ) as td:
        work = Path(td)
        repository_root, issued = _init_git_authority(work)

        source = production.prep._checkout_frozen(work)
        production.prep._rebuild_frozen(source, work)
        payload = work / "first.tar.gz"
        materializer = production._load_exact_materializer(
            source / "deploy" / "zero-based-vps" / "materialize_payload.py"
        )
        boundary = production._qualification_boundary()
        scenarios: dict[str, str] = {}

        # 1. Exact one-shot happy path.
        releases1 = work / "releases-happy"
        releases1.mkdir()
        witnesses1 = _witness_root(work / "witness-happy")
        result1 = execute_once(
            repository_root=repository_root,
            issued=issued,
            payload=payload,
            releases_root=releases1,
            witness_root=witnesses1,
            materializer=materializer,
            boundary_probe=_SequenceProbe([boundary] * 20),
        )
        if result1["execution_state"] != "COMPLETED_EXACT":
            raise StageExecutionError("QUALIFICATION_FAILED", "happy path did not complete")
        scenarios["happy_path"] = "COMPLETED_EXACT"

        # 2. Exact replay never republishes.
        def forbidden_materialize(*args, **kwargs):
            raise AssertionError("exact completed replay attempted publication")

        result2 = execute_once(
            repository_root=repository_root,
            issued=issued,
            payload=payload,
            releases_root=releases1,
            witness_root=witnesses1,
            materializer=materializer,
            boundary_probe=_SequenceProbe([boundary] * 10),
            materialize_call=forbidden_materialize,
        )
        if result2["execution_state"] != "IDEMPOTENT_COMPLETED_EXACT":
            raise StageExecutionError("QUALIFICATION_FAILED", "completed replay not idempotent")
        scenarios["exact_replay"] = "IDEMPOTENT_COMPLETED_EXACT"

        # 3. Crash after PREPARED but before publication never blind-retries.
        releases3 = work / "releases-crash-before"
        releases3.mkdir()
        witnesses3 = _witness_root(work / "witness-crash-before")

        def crash_after_prepared(point: str) -> None:
            if point == "after_prepared":
                raise RuntimeError("simulated crash after PREPARED")

        try:
            execute_once(
                repository_root=repository_root,
                issued=issued,
                payload=payload,
                releases_root=releases3,
                witness_root=witnesses3,
                materializer=materializer,
                boundary_probe=_SequenceProbe([boundary] * 10),
                fault_hook=crash_after_prepared,
            )
        except RuntimeError:
            pass
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "crash-before scenario did not crash")
        try:
            execute_once(
                repository_root=repository_root,
                issued=issued,
                payload=payload,
                releases_root=releases3,
                witness_root=witnesses3,
                materializer=materializer,
                boundary_probe=_SequenceProbe([boundary] * 10),
                materialize_call=forbidden_materialize,
            )
        except StageExecutionError as exc:
            if exc.code != "PREPARED_NOT_STAGED_RECONCILE_REQUIRED":
                raise
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "PREPARED/no-release blind retry allowed")
        scenarios["crash_before_publication"] = "RECONCILE_REQUIRED_NO_BLIND_RETRY"

        # 4. Crash after durable publication but before COMPLETED is recovered
        # without a second publication.
        releases4 = work / "releases-crash-after"
        releases4.mkdir()
        witnesses4 = _witness_root(work / "witness-crash-after")

        def crash_after_stage(point: str) -> None:
            if point == "after_stage_before_completed":
                raise RuntimeError("simulated crash after durable stage")

        try:
            execute_once(
                repository_root=repository_root,
                issued=issued,
                payload=payload,
                releases_root=releases4,
                witness_root=witnesses4,
                materializer=materializer,
                boundary_probe=_SequenceProbe([boundary] * 20),
                fault_hook=crash_after_stage,
            )
        except RuntimeError:
            pass
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "crash-after scenario did not crash")
        recovered = execute_once(
            repository_root=repository_root,
            issued=issued,
            payload=payload,
            releases_root=releases4,
            witness_root=witnesses4,
            materializer=materializer,
            boundary_probe=_SequenceProbe([boundary] * 20),
            materialize_call=forbidden_materialize,
        )
        if recovered["execution_state"] != "RECOVERED_COMPLETED_EXACT":
            raise StageExecutionError("QUALIFICATION_FAILED", "postpublication recovery failed")
        scenarios["crash_after_publication"] = "RECOVERED_WITHOUT_REPUBLICATION"

        # 5. Stale authority-bound evidence blocks before PREPARED/publication.
        releases5 = work / "releases-stale"
        releases5.mkdir()
        witnesses5 = _witness_root(work / "witness-stale")
        changed = json.loads(_canonical(boundary).decode("utf-8"))
        changed["services"]["writer"] = {"active_state": "ACTIVE", "main_pid": 999}
        try:
            execute_once(
                repository_root=repository_root,
                issued=issued,
                payload=payload,
                releases_root=releases5,
                witness_root=witnesses5,
                materializer=materializer,
                boundary_probe=_SequenceProbe([changed] * 10),
                materialize_call=forbidden_materialize,
            )
        except StageExecutionError as exc:
            if exc.code != "STALE_OR_MISMATCHED_BOUNDARY_EVIDENCE":
                raise
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "stale boundary was accepted")
        prepared5, _ = _witness_paths(witnesses5, issued.transaction_id)
        if prepared5.exists():
            raise StageExecutionError("QUALIFICATION_FAILED", "stale boundary wrote PREPARED")
        scenarios["stale_boundary"] = "FAIL_BEFORE_PREPARED"

        # 6. Wrong payload fails before PREPARED.
        releases6 = work / "releases-bad-payload"
        releases6.mkdir()
        witnesses6 = _witness_root(work / "witness-bad-payload")
        bad_payload = work / "bad-payload.tar.gz"
        bad_payload.write_bytes(b"not-r0007")
        try:
            execute_once(
                repository_root=repository_root,
                issued=issued,
                payload=bad_payload,
                releases_root=releases6,
                witness_root=witnesses6,
                materializer=materializer,
                boundary_probe=_SequenceProbe([boundary] * 10),
                materialize_call=forbidden_materialize,
            )
        except StageExecutionError as exc:
            if exc.code != "PAYLOAD_INVALID":
                raise
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "bad payload was accepted")
        prepared6, _ = _witness_paths(witnesses6, issued.transaction_id)
        if prepared6.exists():
            raise StageExecutionError("QUALIFICATION_FAILED", "bad payload wrote PREPARED")
        scenarios["payload_mismatch"] = "FAIL_BEFORE_PREPARED"

        # 7. Foreign PREPARED fails closed and remains untouched.
        releases7 = work / "releases-foreign-prepared"
        releases7.mkdir()
        witnesses7 = _witness_root(work / "witness-foreign-prepared")
        prepared7, _ = _witness_paths(witnesses7, issued.transaction_id)
        foreign = {"schema": PREPARED_SCHEMA, "transaction_id": issued.transaction_id, "foreign": True}
        _write_immutable(prepared7, foreign, "foreign PREPARED witness")
        before7 = prepared7.read_bytes()
        try:
            reconcile_execution(
                repository_root=repository_root,
                issued=issued,
                payload=payload,
                releases_root=releases7,
                witness_root=witnesses7,
                materializer=materializer,
                boundary_probe=_SequenceProbe([boundary] * 10),
            )
        except StageExecutionError as exc:
            if exc.code != "PREPARED_WITNESS_CONFLICT":
                raise
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "foreign PREPARED accepted")
        if prepared7.read_bytes() != before7:
            raise StageExecutionError("QUALIFICATION_FAILED", "foreign PREPARED mutated")
        scenarios["foreign_prepared"] = "FAIL_CLOSED_UNTOUCHED"

        # 8. Exact staged release without PREPARED cannot be attributed.
        releases8 = work / "releases-unattributed"
        releases8.mkdir()
        witnesses8 = _witness_root(work / "witness-unattributed")
        materializer.materialize_payload(
            payload,
            releases8,
            expected_source_commit=authority.SOURCE_COMMIT,
            expected_payload_sha256=authority.PAYLOAD_SHA256,
        )
        try:
            reconcile_execution(
                repository_root=repository_root,
                issued=issued,
                payload=payload,
                releases_root=releases8,
                witness_root=witnesses8,
                materializer=materializer,
                boundary_probe=_SequenceProbe([boundary] * 10),
            )
        except StageExecutionError as exc:
            if exc.code != "UNATTRIBUTED_STAGED_RELEASE":
                raise
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "unattributed release was claimed")
        scenarios["unattributed_staged_release"] = "FAIL_CLOSED_NO_CLAIM"

        # 9. COMPLETED without PREPARED is invalid.
        releases9 = work / "releases-completed-only"
        releases9.mkdir()
        witnesses9 = _witness_root(work / "witness-completed-only")
        _, completed9 = _witness_paths(witnesses9, issued.transaction_id)
        _write_immutable(
            completed9,
            {"schema": COMPLETED_SCHEMA, "transaction_id": issued.transaction_id},
            "foreign COMPLETED witness",
        )
        try:
            reconcile_execution(
                repository_root=repository_root,
                issued=issued,
                payload=payload,
                releases_root=releases9,
                witness_root=witnesses9,
                materializer=materializer,
                boundary_probe=_SequenceProbe([boundary] * 10),
            )
        except StageExecutionError as exc:
            if exc.code != "COMPLETED_WITHOUT_PREPARED":
                raise
        else:
            raise StageExecutionError("QUALIFICATION_FAILED", "COMPLETED without PREPARED accepted")
        scenarios["completed_without_prepared"] = "FAIL_CLOSED"

    expected = {
        "happy_path": "COMPLETED_EXACT",
        "exact_replay": "IDEMPOTENT_COMPLETED_EXACT",
        "crash_before_publication": "RECONCILE_REQUIRED_NO_BLIND_RETRY",
        "crash_after_publication": "RECOVERED_WITHOUT_REPUBLICATION",
        "stale_boundary": "FAIL_BEFORE_PREPARED",
        "payload_mismatch": "FAIL_BEFORE_PREPARED",
        "foreign_prepared": "FAIL_CLOSED_UNTOUCHED",
        "unattributed_staged_release": "FAIL_CLOSED_NO_CLAIM",
        "completed_without_prepared": "FAIL_CLOSED",
    }
    if scenarios != expected:
        raise StageExecutionError(
            "QUALIFICATION_FAILED",
            f"execution scenario mismatch: {scenarios}",
        )

    return {
        "schema": "keelaryn.operation-control-r0007-stage-execution-qualification.v1",
        "gate_revision": GATE_REVISION,
        "candidate": authority.CANDIDATE,
        "source_commit": authority.SOURCE_COMMIT,
        "source_tree": authority.SOURCE_TREE,
        "payload_sha256": authority.PAYLOAD_SHA256,
        "payload_size": authority.PAYLOAD_SIZE,
        "file_count": authority.PAYLOAD_FILE_COUNT,
        "authority_scope": authority.SCOPE,
        "prepared_schema": PREPARED_SCHEMA,
        "completed_schema": COMPLETED_SCHEMA,
        "physical_commit_authority": "EXACT_IMMUTABLE_RELEASE_DIRECTORY",
        "execution_attribution": "IMMUTABLE_PREPARED_COMPLETED_WITNESSES",
        "prepared_before_publication": True,
        "payload_verified_before_prepared": True,
        "fresh_live_boundary_matches_authority_evidence_before_prepared": True,
        "completed_written_only_after_exact_release_and_post_reconcile": True,
        "blind_retry_after_prepared_without_release_allowed": False,
        "republish_after_exact_staged_release_allowed": False,
        "claim_unattributed_staged_release_allowed": False,
        "activation_authorized": False,
        "real_authorization_record_issued": False,
        "real_vps_stage_performed": False,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "production_mutation_allowed": False,
        "drive_content_mutation_allowed": False,
        "production_qualified": False,
        "next_action": "DESIGN_REAL_STAGE_ISSUANCE_AND_EXECUTION_TRANSACTION",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0007-stage-execution"
    )
    parser.add_argument("command", choices=("qualify",))
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = qualify()
    except (
        StageExecutionError,
        authority.StageAuthorityError,
        production.ProductionStagePrepError,
        stage.StageError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-r0007-stage-execution-failure.v1",
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
