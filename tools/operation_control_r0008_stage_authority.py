from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "keelaryn.operation-control-r0008-stage-authorization.v1"
BOUNDARY_SCHEMA = "keelaryn.operation-control-r0008-stage-boundary-evidence.v1"
SCOPE = "R0008_RELEASE_STAGE_ONLY"
REPOSITORY = "efremov-aleksei-96/keelaryn"
BRANCH = "dev/zero-based-keelaryn"
AUTHORITY_ROOT = "docs/authorizations/operation-control-r0008-stage"

CANDIDATE = "operation-control-r0008-20260923-01"
SOURCE_COMMIT = "20727893662cde92998d88ecdca730b69633eaaa"
SOURCE_TREE = "c68bfe3dab53206439d1c42634f5c5ac602fb09c"
PAYLOAD_SHA256 = "bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d"
PAYLOAD_SIZE = 428403
PAYLOAD_FILE_COUNT = 217

PRODUCTION_SOURCE = "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
PREDECESSOR_SOURCE = "08f2e211f53764590f6ff0f05f86b2de62c14418"
HUB_TRANSACTION_ID = "61a2bfb65c9a47d088a76eee0df89d14"
CREDENTIAL_SHA256 = "7002ed72a223dd7fc860451c53a4ec8f264d14f7144000559a295522b7cbe928"

GATE_REVISION = "operation-control-r0008-stage-authority-gate-r0003"


class StageAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_ISSUED_TOKEN = object()


class IssuedStageAuthorization:
    __slots__ = ("_record", "_provenance")

    def __init__(
        self,
        token: object,
        record: dict[str, Any],
        provenance: dict[str, Any],
    ) -> None:
        if token is not _ISSUED_TOKEN:
            raise TypeError(
                "IssuedStageAuthorization can only be created by the Git provenance resolver"
            )
        self._record = json.loads(_canonical(record).decode("utf-8"))
        self._provenance = json.loads(_canonical(provenance).decode("utf-8"))

    @property
    def transaction_id(self) -> str:
        return self._record["transaction_id"]

    @property
    def record(self) -> dict[str, Any]:
        return json.loads(_canonical(self._record).decode("utf-8"))

    @property
    def provenance(self) -> dict[str, Any]:
        return json.loads(_canonical(self._provenance).decode("utf-8"))

    def stage_authorization(self) -> dict[str, Any]:
        record = self.record
        return {
            "schema": "keelaryn.operation-control-r0008-production-stage-authorization.v1",
            "scope": record["scope"],
            "candidate": record["candidate"],
            "source_commit": record["source_commit"],
            "source_tree": record["source_tree"],
            "payload_sha256": record["payload_sha256"],
            "payload_size": record["payload_size"],
            "file_count": record["file_count"],
            "production_stage_authorized": record["production_stage_authorized"],
            "activation_authorized": record["activation_authorized"],
            "drive_content_mutation_authorized": record[
                "drive_content_mutation_authorized"
            ],
            "legacy_hub_mutation_authorized": record[
                "legacy_hub_mutation_authorized"
            ],
            "writer_mutation_authorized": record["writer_mutation_authorized"],
            "credential_mutation_authorized": record[
                "credential_mutation_authorized"
            ],
        }


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


def _hex(value: Any, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or re.fullmatch(r"[0-9a-f]+", value) is None
    ):
        raise StageAuthorityError("AUTHORITY_INVALID", f"{label} is invalid")
    return value


def _safe_path(value: Any, *, prefix: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(prefix + "/")
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or ".." in value.split("/")
    ):
        raise StageAuthorityError("AUTHORITY_INVALID", f"{label} is unsafe")
    return value


def authority_path(transaction_id: str) -> str:
    tx = _hex(transaction_id, 32, "transaction_id")
    return f"{AUTHORITY_ROOT}/{tx}.json"


def validate_boundary_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "boundary evidence must be an object",
        )
    expected_keys = {
        "schema",
        "observed_at_utc",
        "conclusion",
        "production_source_commit",
        "control_source_commit",
        "legacy_hub_status",
        "legacy_hub_transaction_id",
        "selector_role",
        "writer",
        "mutation_inhibit_authority_matches",
        "credential_sha256",
        "legacy_hub_authority_scope",
        "production_mutations_performed",
        "drive_mutations_performed",
    }
    if set(value) != expected_keys:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "boundary evidence keys mismatch",
        )
    if value["schema"] != BOUNDARY_SCHEMA or value["conclusion"] != "PASS":
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "boundary evidence schema/conclusion mismatch",
        )
    observed = value["observed_at_utc"]
    if (
        not isinstance(observed, str)
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            observed,
        )
        is None
    ):
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "boundary evidence timestamp invalid",
        )
    if value["production_source_commit"] != PRODUCTION_SOURCE:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "production source mismatch",
        )
    if value["control_source_commit"] != PREDECESSOR_SOURCE:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "predecessor source mismatch",
        )
    if value["legacy_hub_status"] != "PREPARED":
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "legacy Hub status mismatch",
        )
    if value["legacy_hub_transaction_id"] != HUB_TRANSACTION_ID:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "legacy Hub transaction mismatch",
        )
    if value["selector_role"] != "OLD":
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "legacy selector role mismatch",
        )
    if value["writer"] != "INACTIVE_MAINPID_0":
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "writer boundary mismatch",
        )
    if value["mutation_inhibit_authority_matches"] is not True:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "mutation inhibit authority mismatch",
        )
    if value["credential_sha256"] != CREDENTIAL_SHA256:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "credential identity mismatch",
        )
    if value["legacy_hub_authority_scope"] != "RUNTIME_SAFETY_ONLY":
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "legacy Hub authority widened",
        )
    if value["production_mutations_performed"] is not False:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "boundary evidence claims production mutation",
        )
    if value["drive_mutations_performed"] is not False:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_INVALID",
            "boundary evidence claims Drive mutation",
        )
    return json.loads(_canonical(value).decode("utf-8"))


def validate_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StageAuthorityError("AUTHORITY_INVALID", "authorization must be an object")
    expected_keys = {
        "schema",
        "transaction_id",
        "scope",
        "candidate",
        "source_commit",
        "source_tree",
        "payload_sha256",
        "payload_size",
        "file_count",
        "issuer_repository",
        "issuer_branch",
        "issuer_checkpoint",
        "boundary_evidence_commit",
        "boundary_evidence_path",
        "boundary_evidence_git_blob",
        "boundary_evidence_sha256",
        "production_stage_authorized",
        "activation_authorized",
        "drive_content_mutation_authorized",
        "legacy_hub_mutation_authorized",
        "writer_mutation_authorized",
        "credential_mutation_authorized",
    }
    if set(value) != expected_keys:
        raise StageAuthorityError("AUTHORITY_INVALID", "authorization keys mismatch")

    _hex(value["transaction_id"], 32, "transaction_id")
    _hex(value["issuer_checkpoint"], 40, "issuer_checkpoint")
    _hex(value["boundary_evidence_commit"], 40, "boundary_evidence_commit")
    _hex(value["boundary_evidence_git_blob"], 40, "boundary_evidence_git_blob")
    _hex(value["boundary_evidence_sha256"], 64, "boundary_evidence_sha256")
    _safe_path(
        value["boundary_evidence_path"],
        prefix="docs/evidence",
        label="boundary_evidence_path",
    )

    exact = {
        "schema": SCHEMA,
        "scope": SCOPE,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "issuer_repository": REPOSITORY,
        "issuer_branch": BRANCH,
        "production_stage_authorized": True,
        "activation_authorized": False,
        "drive_content_mutation_authorized": False,
        "legacy_hub_mutation_authorized": False,
        "writer_mutation_authorized": False,
        "credential_mutation_authorized": False,
    }
    for key, expected in exact.items():
        if value[key] != expected:
            raise StageAuthorityError(
                "AUTHORITY_INVALID",
                f"authorization field mismatch: {key}",
            )
    if value["boundary_evidence_commit"] != value["issuer_checkpoint"]:
        raise StageAuthorityError(
            "AUTHORITY_INVALID",
            "boundary evidence must be committed in issuer checkpoint",
        )
    return json.loads(_canonical(value).decode("utf-8"))


def _git(
    root: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageAuthorityError("GIT_FAILURE", "Git command failed to execute") from exc
    if check and completed.returncode != 0:
        raise StageAuthorityError(
            "GIT_FAILURE",
            completed.stderr.decode("utf-8", errors="replace").strip()
            or "Git command failed",
        )
    return completed


def _commit(root: Path, rev: str) -> str:
    value = _git(root, ["rev-parse", "--verify", f"{rev}^{{commit}}"]).stdout.decode(
        "ascii"
    ).strip()
    return _hex(value, 40, "commit")


def _blob(root: Path, commit: str, path: str) -> str:
    value = _git(root, ["rev-parse", f"{commit}:{path}"]).stdout.decode("ascii").strip()
    return _hex(value, 40, "Git blob")


def _show(root: Path, commit: str, path: str) -> bytes:
    return _git(root, ["show", f"{commit}:{path}"]).stdout


def _decode_canonical(raw: bytes, label: str) -> Any:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageAuthorityError(
            "AUTHORITY_INVALID",
            f"{label} is not valid UTF-8 JSON",
        ) from exc
    if raw != _canonical(value):
        raise StageAuthorityError(
            "AUTHORITY_INVALID",
            f"{label} is not canonical JSON",
        )
    return value


def resolve_git_authorization(
    repository_root: Path,
    *,
    authority_commit: str,
    authority_path_value: str,
    expected_authority_blob: str,
    authoritative_branch: str = BRANCH,
) -> IssuedStageAuthorization:
    root = repository_root.resolve()
    commit = _commit(root, authority_commit)
    blob_expected = _hex(expected_authority_blob, 40, "expected_authority_blob")

    if not re.fullmatch(
        re.escape(AUTHORITY_ROOT) + r"/[0-9a-f]{32}\.json",
        authority_path_value,
    ):
        raise StageAuthorityError(
            "AUTHORITY_PATH_INVALID",
            "authorization path is not canonical transaction path",
        )

    branch_ref = f"refs/heads/{authoritative_branch}"
    branch_commit = _commit(root, branch_ref)
    ancestor = _git(
        root,
        ["merge-base", "--is-ancestor", commit, branch_commit],
        check=False,
    )
    if ancestor.returncode != 0:
        raise StageAuthorityError(
            "AUTHORITY_NOT_ON_BRANCH",
            "authorization commit is not on authoritative branch",
        )

    parent = _commit(root, f"{commit}^1")
    diff = _git(
        root,
        [
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            parent,
            commit,
        ],
    ).stdout.decode("utf-8").splitlines()
    if diff != [f"A\t{authority_path_value}"]:
        raise StageAuthorityError(
            "AUTHORITY_COMMIT_NOT_ISOLATED",
            "authorization commit must add exactly one new authority path",
        )

    parent_lookup = _git(
        root,
        ["cat-file", "-e", f"{parent}:{authority_path_value}"],
        check=False,
    )
    if parent_lookup.returncode == 0:
        raise StageAuthorityError(
            "AUTHORITY_TRANSACTION_COLLISION",
            "authorization path already existed in issuer checkpoint",
        )

    observed_blob = _blob(root, commit, authority_path_value)
    if observed_blob != blob_expected:
        raise StageAuthorityError(
            "AUTHORITY_BLOB_MISMATCH",
            "authorization Git blob differs from expected immutable identity",
        )

    raw = _show(root, commit, authority_path_value)
    record = validate_record(_decode_canonical(raw, "authorization"))
    if record["issuer_checkpoint"] != parent:
        raise StageAuthorityError(
            "AUTHORITY_CHECKPOINT_MISMATCH",
            "authorization issuer checkpoint is not commit parent",
        )
    if authority_path(record["transaction_id"]) != authority_path_value:
        raise StageAuthorityError(
            "AUTHORITY_TRANSACTION_COLLISION",
            "authorization path does not match transaction id",
        )

    evidence_path = record["boundary_evidence_path"]
    evidence_blob = _blob(root, parent, evidence_path)
    if evidence_blob != record["boundary_evidence_git_blob"]:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_BLOB_MISMATCH",
            "boundary evidence Git blob mismatch",
        )
    evidence_raw = _show(root, parent, evidence_path)
    if _sha256(evidence_raw) != record["boundary_evidence_sha256"]:
        raise StageAuthorityError(
            "BOUNDARY_EVIDENCE_SHA_MISMATCH",
            "boundary evidence SHA-256 mismatch",
        )
    evidence = validate_boundary_evidence(
        _decode_canonical(evidence_raw, "boundary evidence")
    )

    provenance = {
        "repository": REPOSITORY,
        "branch": authoritative_branch,
        "authority_commit": commit,
        "authority_parent_checkpoint": parent,
        "authority_path": authority_path_value,
        "authority_git_blob": observed_blob,
        "authority_sha256": _sha256(raw),
        "boundary_evidence_path": evidence_path,
        "boundary_evidence_git_blob": evidence_blob,
        "boundary_evidence_sha256": _sha256(evidence_raw),
        "boundary_observed_at_utc": evidence["observed_at_utc"],
    }
    return IssuedStageAuthorization(_ISSUED_TOKEN, record, provenance)


def require_issued_authorization(value: Any) -> dict[str, Any]:
    if not isinstance(value, IssuedStageAuthorization):
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_REQUIRED",
            "production stage requires Git-resolved IssuedStageAuthorization",
        )
    record = validate_record(value.record)
    provenance = value.provenance
    required = {
        "repository",
        "branch",
        "authority_commit",
        "authority_parent_checkpoint",
        "authority_path",
        "authority_git_blob",
        "authority_sha256",
        "boundary_evidence_path",
        "boundary_evidence_git_blob",
        "boundary_evidence_sha256",
        "boundary_observed_at_utc",
    }
    if set(provenance) != required:
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_INVALID",
            "resolved authorization provenance keys mismatch",
        )
    if provenance["repository"] != REPOSITORY or provenance["branch"] != BRANCH:
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_INVALID",
            "resolved authorization repository/branch mismatch",
        )
    if provenance["authority_parent_checkpoint"] != record["issuer_checkpoint"]:
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_INVALID",
            "resolved authorization checkpoint mismatch",
        )
    if provenance["authority_path"] != authority_path(record["transaction_id"]):
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_INVALID",
            "resolved authorization path mismatch",
        )
    if provenance["boundary_evidence_path"] != record["boundary_evidence_path"]:
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_INVALID",
            "resolved boundary evidence path mismatch",
        )
    if provenance["boundary_evidence_git_blob"] != record["boundary_evidence_git_blob"]:
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_INVALID",
            "resolved boundary evidence blob mismatch",
        )
    if provenance["boundary_evidence_sha256"] != record["boundary_evidence_sha256"]:
        raise StageAuthorityError(
            "AUTHORITY_PROVENANCE_INVALID",
            "resolved boundary evidence SHA mismatch",
        )
    return value.stage_authorization()


def qualification_boundary_evidence() -> dict[str, Any]:
    return {
        "schema": BOUNDARY_SCHEMA,
        "observed_at_utc": "2026-09-22T00:00:00Z",
        "conclusion": "PASS",
        "production_source_commit": PRODUCTION_SOURCE,
        "control_source_commit": PREDECESSOR_SOURCE,
        "legacy_hub_status": "PREPARED",
        "legacy_hub_transaction_id": HUB_TRANSACTION_ID,
        "selector_role": "OLD",
        "writer": "INACTIVE_MAINPID_0",
        "mutation_inhibit_authority_matches": True,
        "credential_sha256": CREDENTIAL_SHA256,
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
        "production_mutations_performed": False,
        "drive_mutations_performed": False,
    }


def _init_repo(root: Path) -> None:
    _git(root, ["init", "-q", "-b", BRANCH])
    _git(root, ["config", "user.name", "Keelaryn CI"])
    _git(root, ["config", "user.email", "ci@keelaryn.invalid"])
    # Disposable qualification repositories must not start asynchronous
    # maintenance/GC that can race TemporaryDirectory cleanup.
    _git(root, ["config", "maintenance.auto", "false"])
    _git(root, ["config", "gc.auto", "0"])
    _git(root, ["config", "gc.autoPackLimit", "0"])


def _write_canonical(root: Path, relative: str, value: Any) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


def _commit_all(root: Path, message: str) -> str:
    _git(root, ["add", "--all"])
    _git(root, ["commit", "-q", "-m", message])
    return _commit(root, "HEAD")


def qualify(
    *,
    render_record,
) -> dict[str, Any]:
    transaction_id = "70000000000000000000000000000001"
    evidence_path = "docs/evidence/R0008_STAGE_BOUNDARY_QUALIFICATION.json"

    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0008-stage-authority-"
    ) as td:
        root = Path(td)
        _init_repo(root)

        evidence = qualification_boundary_evidence()
        _write_canonical(root, evidence_path, evidence)
        checkpoint = _commit_all(root, "qualification boundary evidence")
        evidence_blob = _blob(root, checkpoint, evidence_path)
        evidence_raw = _show(root, checkpoint, evidence_path)

        record = render_record(
            transaction_id=transaction_id,
            issuer_checkpoint=checkpoint,
            boundary_evidence_path=evidence_path,
            boundary_evidence_git_blob=evidence_blob,
            boundary_evidence_sha256=_sha256(evidence_raw),
        )
        path = authority_path(transaction_id)
        _write_canonical(root, path, record)
        authority_commit = _commit_all(root, "issue one-shot stage authority")
        authority_blob = _blob(root, authority_commit, path)

        issued = resolve_git_authorization(
            root,
            authority_commit=authority_commit,
            authority_path_value=path,
            expected_authority_blob=authority_blob,
        )
        replay = resolve_git_authorization(
            root,
            authority_commit=authority_commit,
            authority_path_value=path,
            expected_authority_blob=authority_blob,
        )
        if issued.record != replay.record or issued.provenance != replay.provenance:
            raise StageAuthorityError(
                "QUALIFICATION_FAILED",
                "exact authority replay is not deterministic",
            )

        scenarios: dict[str, str] = {
            "exact_issue_resolve": "PASS",
            "exact_replay": "PASS",
        }

        # Content substitution under the same transaction path is rejected even
        # when a caller supplies the newer blob identity: the commit is not an
        # isolated path addition and the transaction already existed.
        tampered = issued.record
        tampered["activation_authorized"] = True
        _write_canonical(root, path, tampered)
        tampered_commit = _commit_all(root, "tamper existing authority")
        tampered_blob = _blob(root, tampered_commit, path)
        try:
            resolve_git_authorization(
                root,
                authority_commit=tampered_commit,
                authority_path_value=path,
                expected_authority_blob=tampered_blob,
            )
        except StageAuthorityError as exc:
            if exc.code not in {
                "AUTHORITY_COMMIT_NOT_ISOLATED",
                "AUTHORITY_TRANSACTION_COLLISION",
                "AUTHORITY_INVALID",
            }:
                raise
        else:
            raise StageAuthorityError(
                "QUALIFICATION_FAILED",
                "tampered authority was accepted",
            )
        scenarios["same_transaction_substitution"] = "FAIL_CLOSED"

        # Reset branch to issued authority for independent scenarios.
        _git(root, ["reset", "--hard", "-q", authority_commit])

        try:
            resolve_git_authorization(
                root,
                authority_commit=authority_commit,
                authority_path_value=path,
                expected_authority_blob="0" * 40,
            )
        except StageAuthorityError as exc:
            if exc.code != "AUTHORITY_BLOB_MISMATCH":
                raise
        else:
            raise StageAuthorityError(
                "QUALIFICATION_FAILED",
                "wrong expected authorization blob was accepted",
            )
        scenarios["wrong_blob_identity"] = "FAIL_CLOSED"

        widened_id = "70000000000000000000000000000002"
        widened = render_record(
            transaction_id=widened_id,
            issuer_checkpoint=authority_commit,
            boundary_evidence_path=evidence_path,
            boundary_evidence_git_blob=evidence_blob,
            boundary_evidence_sha256=_sha256(evidence_raw),
        )
        widened["activation_authorized"] = True
        widened_path = authority_path(widened_id)
        _write_canonical(root, widened_path, widened)
        widened_commit = _commit_all(root, "widened authorization")
        widened_blob = _blob(root, widened_commit, widened_path)
        try:
            resolve_git_authorization(
                root,
                authority_commit=widened_commit,
                authority_path_value=widened_path,
                expected_authority_blob=widened_blob,
            )
        except StageAuthorityError:
            pass
        else:
            raise StageAuthorityError(
                "QUALIFICATION_FAILED",
                "permission widening was accepted",
            )
        scenarios["permission_widening"] = "FAIL_CLOSED"

        _git(root, ["reset", "--hard", "-q", authority_commit])

        extra_id = "70000000000000000000000000000003"
        extra = render_record(
            transaction_id=extra_id,
            issuer_checkpoint=authority_commit,
            boundary_evidence_path=evidence_path,
            boundary_evidence_git_blob=evidence_blob,
            boundary_evidence_sha256=_sha256(evidence_raw),
        )
        extra_path = authority_path(extra_id)
        _write_canonical(root, extra_path, extra)
        (root / "EXTRA").write_text("unexpected\n", encoding="utf-8")
        extra_commit = _commit_all(root, "authority plus unrelated mutation")
        extra_blob = _blob(root, extra_commit, extra_path)
        try:
            resolve_git_authorization(
                root,
                authority_commit=extra_commit,
                authority_path_value=extra_path,
                expected_authority_blob=extra_blob,
            )
        except StageAuthorityError as exc:
            if exc.code != "AUTHORITY_COMMIT_NOT_ISOLATED":
                raise
        else:
            raise StageAuthorityError(
                "QUALIFICATION_FAILED",
                "non-isolated authority commit was accepted",
            )
        scenarios["non_isolated_authority_commit"] = "FAIL_CLOSED"

        _git(root, ["reset", "--hard", "-q", authority_commit])

        bad_evidence_id = "70000000000000000000000000000004"
        bad = render_record(
            transaction_id=bad_evidence_id,
            issuer_checkpoint=authority_commit,
            boundary_evidence_path=evidence_path,
            boundary_evidence_git_blob="f" * 40,
            boundary_evidence_sha256=_sha256(evidence_raw),
        )
        bad_path = authority_path(bad_evidence_id)
        _write_canonical(root, bad_path, bad)
        bad_commit = _commit_all(root, "bad boundary binding")
        bad_blob = _blob(root, bad_commit, bad_path)
        try:
            resolve_git_authorization(
                root,
                authority_commit=bad_commit,
                authority_path_value=bad_path,
                expected_authority_blob=bad_blob,
            )
        except StageAuthorityError as exc:
            if exc.code not in {
                "BOUNDARY_EVIDENCE_BLOB_MISMATCH",
                "GIT_FAILURE",
            }:
                raise
        else:
            raise StageAuthorityError(
                "QUALIFICATION_FAILED",
                "bad boundary evidence binding was accepted",
            )
        scenarios["boundary_binding_substitution"] = "FAIL_CLOSED"

        stage_shape = issued.stage_authorization()
        if stage_shape["activation_authorized"] is not False:
            raise StageAuthorityError(
                "QUALIFICATION_FAILED",
                "resolved stage authority widened to activation",
            )

    expected = {
        "exact_issue_resolve": "PASS",
        "exact_replay": "PASS",
        "same_transaction_substitution": "FAIL_CLOSED",
        "wrong_blob_identity": "FAIL_CLOSED",
        "permission_widening": "FAIL_CLOSED",
        "non_isolated_authority_commit": "FAIL_CLOSED",
        "boundary_binding_substitution": "FAIL_CLOSED",
    }
    if scenarios != expected:
        raise StageAuthorityError(
            "QUALIFICATION_FAILED",
            f"scenario evidence mismatch: {scenarios}",
        )

    return {
        "schema": "keelaryn.operation-control-r0008-stage-authority-qualification.v1",
        "gate_revision": GATE_REVISION,
        "authority_schema": SCHEMA,
        "boundary_schema": BOUNDARY_SCHEMA,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "scope": SCOPE,
        "authority_path_template": f"{AUTHORITY_ROOT}/<transaction_id>.json",
        "authority_commit_parent_is_issuer_checkpoint": True,
        "authority_commit_adds_exactly_one_path": True,
        "boundary_evidence_must_exist_in_issuer_checkpoint": True,
        "consumer_can_mint_authority": False,
        "exact_replay_allowed": True,
        "authority_replacement_allowed": False,
        "permission_widening_allowed": False,
        "activation_authorized": False,
        "drive_content_mutation_authorized": False,
        "legacy_hub_mutation_authorized": False,
        "writer_mutation_authorized": False,
        "credential_mutation_authorized": False,
        "real_authorization_record_issued": False,
        "real_vps_stage_performed": False,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "production_mutation_allowed": False,
        "drive_content_mutation_allowed": False,
        "production_qualified": False,
        "next_action": "DESIGN_REAL_AUTHORITY_ISSUANCE_AND_STAGE_EXECUTION_BOUNDARY",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0008-stage-authority"
    )
    parser.add_argument("command", choices=("qualify",))
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    print(
        json.dumps(
            {
                "schema": "keelaryn.operation-control-r0008-stage-authority-error.v1",
                "error": "qualification requires the separate issuer module",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
