#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

STATE_SCHEMA = "keelaryn.autonomous-development-state.v1"
SNAPSHOT_SCHEMA = "keelaryn.autonomous-development-snapshot.v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TOKEN_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,127}$")
OBJECTIVE_RE = re.compile(r"^D[0-9]+-[0-9]+[A-Z]?(?:_[A-Z0-9_-]+)?$")


class DevelopmentStateError(RuntimeError):
    """The durable development state cannot be trusted or resolved safely."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise DevelopmentStateError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DevelopmentStateError(f"{label}: must be object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DevelopmentStateError(
            f"{label}: keys mismatch missing={missing} extra={extra}"
        )
    return value


def _string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise DevelopmentStateError(f"{label}: invalid string")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise DevelopmentStateError(f"{label}: invalid boolean")
    return value


def _int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DevelopmentStateError(f"{label}: invalid integer")
    return value


def _sha(value: Any, label: str) -> str:
    value = _string(value, label)
    if SHA_RE.fullmatch(value) is None:
        raise DevelopmentStateError(f"{label}: invalid git sha")
    return value


def _token(value: Any, label: str) -> str:
    value = _string(value, label)
    if TOKEN_RE.fullmatch(value) is None:
        raise DevelopmentStateError(f"{label}: invalid token")
    return value


def _string_list(value: Any, label: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise DevelopmentStateError(f"{label}: invalid list")
    out: list[str] = []
    for index, item in enumerate(value):
        out.append(_string(item, f"{label}[{index}]"))
    return out


def parse_state_bytes(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DevelopmentStateError("DEVELOPMENT_STATE: invalid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_strict_object)
    except DevelopmentStateError:
        raise
    except json.JSONDecodeError as exc:
        raise DevelopmentStateError("DEVELOPMENT_STATE: invalid JSON") from exc
    return validate_state(value)


def validate_state(value: Any) -> dict[str, Any]:
    top = _exact_keys(
        value,
        {
            "schema",
            "revision",
            "repository",
            "authoritative_branch",
            "repository_basis_commit",
            "qualification_state",
            "head_resolution",
            "capability",
            "architecture",
            "authority",
            "last_coherent_ci",
            "production_boundary",
            "constrained_candidates",
            "transaction_disposition",
            "checkpoint_sources",
            "next_objective",
            "forbidden_actions",
            "resume_procedure",
            "product_after_d0",
        },
        "DEVELOPMENT_STATE",
    )
    if top["schema"] != STATE_SCHEMA:
        raise DevelopmentStateError("DEVELOPMENT_STATE: unsupported schema")
    _int(top["revision"], "DEVELOPMENT_STATE.revision", minimum=1)
    _string(top["repository"], "DEVELOPMENT_STATE.repository")
    _string(top["authoritative_branch"], "DEVELOPMENT_STATE.authoritative_branch")
    _sha(top["repository_basis_commit"], "DEVELOPMENT_STATE.repository_basis_commit")
    if top["qualification_state"] != "UNQUALIFIED_DEVELOPMENT":
        raise DevelopmentStateError("DEVELOPMENT_STATE: development branch must be unqualified")

    head = _exact_keys(
        top["head_resolution"],
        {"mode", "state_file_commit_mode", "rule"},
        "DEVELOPMENT_STATE.head_resolution",
    )
    if head["mode"] != "RESOLVE_BRANCH_REF_LIVE":
        raise DevelopmentStateError("DEVELOPMENT_STATE.head_resolution.mode: invalid")
    if head["state_file_commit_mode"] != "RESOLVE_LAST_CHANGE_LIVE":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.head_resolution.state_file_commit_mode: invalid"
        )
    _string(head["rule"], "DEVELOPMENT_STATE.head_resolution.rule")

    capability = _exact_keys(
        top["capability"],
        {"current_level", "name", "status", "product_level"},
        "DEVELOPMENT_STATE.capability",
    )
    if capability != {
        "current_level": "D0",
        "name": "AUTONOMOUS_ENGINEERING",
        "status": "IN_PROGRESS",
        "product_level": "P0_NOT_STARTED",
    }:
        raise DevelopmentStateError("DEVELOPMENT_STATE.capability: invalid D0 boundary")

    architecture = _exact_keys(
        top["architecture"],
        {
            "model",
            "old_hub_first_r2",
            "old_hub_cutover",
            "authority_model",
            "object_authority",
            "operational_state_authority",
            "lifeos_authority",
            "control_semantic_plane",
            "semantic_rule",
            "legacy_hub_authority",
            "chat_is_durable_state",
        },
        "DEVELOPMENT_STATE.architecture",
    )
    expected_architecture = {
        "model": "CORPUS_FIRST",
        "old_hub_first_r2": "PROVENANCE_RESEARCH_ONLY",
        "old_hub_cutover": "PAUSED_LEGACY_RUNTIME_ONLY",
        "authority_model": "LAYERED_CORPUS_FIRST",
        "object_authority": (
            "PHYSICAL_CORPUS_OBJECT_EXISTENCE_BYTES_IDENTITY_LOCATION"
        ),
        "operational_state_authority": "EXPLICIT_PROJECT_WORKSPACE_STATE",
        "lifeos_authority": "CROSS_LIFE_ORCHESTRATION_SEMANTICS_ONLY",
        "control_semantic_plane": (
            "INDEXES_FINGERPRINTS_RELATIONS_CLASSIFICATIONS_DERIVED_"
            "TRANSACTION_RECOVERY_METADATA"
        ),
        "semantic_rule": (
            "SEMANTICS_DO_NOT_OVERRIDE_OBJECT_AND_LOCATION_DOES_NOT_"
            "DEFINE_COMPLETE_MEANING"
        ),
        "legacy_hub_authority": (
            "PROVENANCE_AND_TEMPORARY_PRE_CUTOVER_RUNTIME_BOUNDARY_ONLY"
        ),
        "chat_is_durable_state": False,
    }
    if architecture != expected_architecture:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.architecture: invalid layered Corpus-first boundary"
        )

    authority = _exact_keys(
        top["authority"],
        {"github", "vps", "google_drive", "chatgpt"},
        "DEVELOPMENT_STATE.authority",
    )
    for key in ("github", "vps", "google_drive", "chatgpt"):
        _string_list(authority[key], f"DEVELOPMENT_STATE.authority.{key}", minimum=1)

    ci = _exact_keys(
        top["last_coherent_ci"],
        {"scope", "run_id", "conclusion", "relevance", "note"},
        "DEVELOPMENT_STATE.last_coherent_ci",
    )
    _string(ci["scope"], "DEVELOPMENT_STATE.last_coherent_ci.scope")
    _int(ci["run_id"], "DEVELOPMENT_STATE.last_coherent_ci.run_id", minimum=1)
    if ci["conclusion"] != "PASS":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.last_coherent_ci.conclusion: invalid"
        )
    _token(ci["relevance"], "DEVELOPMENT_STATE.last_coherent_ci.relevance")
    _string(ci["note"], "DEVELOPMENT_STATE.last_coherent_ci.note")

    production = _exact_keys(
        top["production_boundary"],
        {
            "freshness",
            "observed_at_utc",
            "evidence_path",
            "source_commit",
            "hub_cutover_status",
            "hub_transaction_id",
            "selector",
            "writer",
            "installed_operation_control",
            "read_only_selftest",
            "rule",
        },
        "DEVELOPMENT_STATE.production_boundary",
    )
    if production["freshness"] != "LIVE_VERIFIED_READ_ONLY_D0":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.freshness: invalid"
        )
    observed_at = _string(
        production["observed_at_utc"],
        "DEVELOPMENT_STATE.production_boundary.observed_at_utc",
    )
    if re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
        observed_at,
    ) is None:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.observed_at_utc: invalid"
        )
    evidence_path = _string(
        production["evidence_path"],
        "DEVELOPMENT_STATE.production_boundary.evidence_path",
    )
    if (
        not evidence_path.startswith("docs/evidence/")
        or evidence_path.startswith("/")
        or "\\" in evidence_path
        or ".." in evidence_path.split("/")
    ):
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.evidence_path: unsafe"
        )
    _sha(
        production["source_commit"],
        "DEVELOPMENT_STATE.production_boundary.source_commit",
    )
    if production["hub_cutover_status"] != "PREPARED":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.hub_cutover_status: invalid"
        )
    _string(
        production["hub_transaction_id"],
        "DEVELOPMENT_STATE.production_boundary.hub_transaction_id",
    )
    if production["selector"] != "OLD" or production["writer"] != "INACTIVE_MAINPID_0":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary: unsafe recorded boundary"
        )
    installed = _exact_keys(
        production["installed_operation_control"],
        {"candidate", "source_commit", "state"},
        "DEVELOPMENT_STATE.production_boundary.installed_operation_control",
    )
    _string(
        installed["candidate"],
        "DEVELOPMENT_STATE.production_boundary.installed_operation_control.candidate",
    )
    installed_source = _sha(
        installed["source_commit"],
        "DEVELOPMENT_STATE.production_boundary.installed_operation_control.source_commit",
    )
    if installed["state"] != "INSTALLED_RUNTIME_ACCEPTED":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.installed_operation_control.state: invalid"
        )
    selftest = _exact_keys(
        production["read_only_selftest"],
        {
            "request_id",
            "request_comment_id",
            "status_comment_id",
            "source_commit",
            "status",
            "timestamp_utc",
        },
        "DEVELOPMENT_STATE.production_boundary.read_only_selftest",
    )
    request_id = _string(
        selftest["request_id"],
        "DEVELOPMENT_STATE.production_boundary.read_only_selftest.request_id",
    )
    if re.fullmatch(r"[0-9a-f]{32}", request_id) is None:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.read_only_selftest.request_id: invalid"
        )
    _int(
        selftest["request_comment_id"],
        "DEVELOPMENT_STATE.production_boundary.read_only_selftest.request_comment_id",
        minimum=1,
    )
    _int(
        selftest["status_comment_id"],
        "DEVELOPMENT_STATE.production_boundary.read_only_selftest.status_comment_id",
        minimum=1,
    )
    if _sha(
        selftest["source_commit"],
        "DEVELOPMENT_STATE.production_boundary.read_only_selftest.source_commit",
    ) != installed_source:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.read_only_selftest: source mismatch"
        )
    if selftest["status"] != "PASS":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.read_only_selftest.status: invalid"
        )
    selftest_timestamp = _string(
        selftest["timestamp_utc"],
        "DEVELOPMENT_STATE.production_boundary.read_only_selftest.timestamp_utc",
    )
    if re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
        selftest_timestamp,
    ) is None:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.production_boundary.read_only_selftest.timestamp_utc: invalid"
        )
    _string(production["rule"], "DEVELOPMENT_STATE.production_boundary.rule")

    candidates = top["constrained_candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.constrained_candidates: invalid"
        )
    seen: set[str] = set()
    for index, item in enumerate(candidates):
        label = f"DEVELOPMENT_STATE.constrained_candidates[{index}]"
        if not isinstance(item, dict):
            raise DevelopmentStateError(f"{label}: must be object")
        expected = {"candidate", "state", "retry"}
        if "source_commit" in item:
            expected.add("source_commit")
        _exact_keys(item, expected, label)
        candidate = _string(item["candidate"], f"{label}.candidate")
        if candidate in seen:
            raise DevelopmentStateError(
                "DEVELOPMENT_STATE.constrained_candidates: duplicate candidate"
            )
        seen.add(candidate)
        _token(item["state"], f"{label}.state")
        retry = _token(item["retry"], f"{label}.retry")
        if retry not in {
            "FORBIDDEN",
            "NOT_A_RETRY_TARGET",
            "FORBIDDEN_UNTIL_ARCHITECTURE_DISPOSITION",
            "FORBIDDEN_LEGACY_HUB_LINE",
        }:
            raise DevelopmentStateError(f"{label}.retry: invalid")
        if "source_commit" in item:
            _sha(item["source_commit"], f"{label}.source_commit")

    transactions = _exact_keys(
        top["transaction_disposition"],
        {"old_hub_cutover", "d0"},
        "DEVELOPMENT_STATE.transaction_disposition",
    )
    old_hub = _exact_keys(
        transactions["old_hub_cutover"],
        {"state", "transaction_id", "mutation_allowed"},
        "DEVELOPMENT_STATE.transaction_disposition.old_hub_cutover",
    )
    if old_hub["state"] != "PAUSED_LEGACY_RUNTIME_ONLY":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.transaction_disposition.old_hub_cutover.state: invalid"
        )
    _string(
        old_hub["transaction_id"],
        "DEVELOPMENT_STATE.transaction_disposition.old_hub_cutover.transaction_id",
    )
    if _bool(
        old_hub["mutation_allowed"],
        "DEVELOPMENT_STATE.transaction_disposition.old_hub_cutover.mutation_allowed",
    ):
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE: old Hub mutation must remain forbidden"
        )
    d0 = _exact_keys(
        transactions["d0"],
        {"state", "mutation_scope"},
        "DEVELOPMENT_STATE.transaction_disposition.d0",
    )
    if d0 != {
        "state": "ACTIVE",
        "mutation_scope": "DEVELOPMENT_CONTROL_PLANE_ONLY",
    }:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.transaction_disposition.d0: invalid"
        )

    checkpoints = _exact_keys(
        top["checkpoint_sources"],
        {"primary_human_handoff", "historical_handoff", "manager_legacy_state"},
        "DEVELOPMENT_STATE.checkpoint_sources",
    )
    for key, path in checkpoints.items():
        value = _string(path, f"DEVELOPMENT_STATE.checkpoint_sources.{key}")
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise DevelopmentStateError(
                f"DEVELOPMENT_STATE.checkpoint_sources.{key}: unsafe repository path"
            )

    objective = _exact_keys(
        top["next_objective"],
        {
            "id",
            "description",
            "production_mutation_allowed",
            "drive_content_mutation_allowed",
        },
        "DEVELOPMENT_STATE.next_objective",
    )
    objective_id = _string(
        objective["id"], "DEVELOPMENT_STATE.next_objective.id"
    )
    if OBJECTIVE_RE.fullmatch(objective_id) is None:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.next_objective.id: invalid"
        )
    _string(
        objective["description"],
        "DEVELOPMENT_STATE.next_objective.description",
    )
    if _bool(
        objective["production_mutation_allowed"],
        "DEVELOPMENT_STATE.next_objective.production_mutation_allowed",
    ):
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE: D0 objective cannot authorize production mutation"
        )
    if _bool(
        objective["drive_content_mutation_allowed"],
        "DEVELOPMENT_STATE.next_objective.drive_content_mutation_allowed",
    ):
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE: D0 objective cannot authorize Drive content mutation"
        )

    _string_list(
        top["forbidden_actions"],
        "DEVELOPMENT_STATE.forbidden_actions",
        minimum=1,
    )
    _string_list(
        top["resume_procedure"],
        "DEVELOPMENT_STATE.resume_procedure",
        minimum=1,
    )

    product = _exact_keys(
        top["product_after_d0"],
        {"target_level", "path", "destructive_normalization_required"},
        "DEVELOPMENT_STATE.product_after_d0",
    )
    if product["target_level"] != "P0":
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.product_after_d0.target_level: invalid"
        )
    _string_list(
        product["path"],
        "DEVELOPMENT_STATE.product_after_d0.path",
        minimum=1,
    )
    if _bool(
        product["destructive_normalization_required"],
        "DEVELOPMENT_STATE.product_after_d0.destructive_normalization_required",
    ):
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE: P0 cannot require destructive normalization"
        )
    return top


def _git(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise DevelopmentStateError("git executable unavailable") from exc
    if check and result.returncode != 0:
        raise DevelopmentStateError(f"git {' '.join(args)} failed")
    return result


def _git_text(root: Path, *args: str) -> str:
    return _git(root, *args).stdout.strip()


def _commit_exists(root: Path, commit: str) -> bool:
    return (
        _git(
            root,
            "cat-file",
            "-e",
            f"{commit}^{{commit}}",
            check=False,
        ).returncode
        == 0
    )


def build_snapshot(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    state_path = root / "DEVELOPMENT_STATE.json"
    try:
        raw = state_path.read_bytes()
    except OSError as exc:
        raise DevelopmentStateError(
            "DEVELOPMENT_STATE.json cannot be read"
        ) from exc
    state = parse_state_bytes(raw)

    git_root = Path(
        _git_text(root, "rev-parse", "--show-toplevel")
    ).resolve()
    if git_root != root:
        raise DevelopmentStateError(
            "repository root does not match git top level"
        )

    current_head = _sha(
        _git_text(root, "rev-parse", "HEAD"), "git.HEAD"
    )
    branch_result = _git(
        root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        check=False,
    )
    current_branch = (
        branch_result.stdout.strip()
        if branch_result.returncode == 0
        else "DETACHED"
    )
    tracked_clean = (
        _git_text(
            root,
            "status",
            "--porcelain",
            "--untracked-files=no",
        )
        == ""
    )

    basis = state["repository_basis_commit"]
    if _commit_exists(root, basis):
        ancestor = _git(
            root,
            "merge-base",
            "--is-ancestor",
            basis,
            current_head,
            check=False,
        )
        if ancestor.returncode == 0:
            basis_relation = "ANCESTOR"
            commits_since_basis: int | None = int(
                _git_text(
                    root,
                    "rev-list",
                    "--count",
                    f"{basis}..{current_head}",
                )
            )
        elif ancestor.returncode == 1:
            basis_relation = "NOT_ANCESTOR"
            commits_since_basis = None
        else:
            raise DevelopmentStateError(
                "git merge-base failed unexpectedly"
            )
    else:
        basis_relation = "UNKNOWN_SHALLOW_HISTORY"
        commits_since_basis = None

    last_change_result = _git(
        root,
        "log",
        "-1",
        "--format=%H",
        "--",
        "DEVELOPMENT_STATE.json",
        check=False,
    )
    last_change = last_change_result.stdout.strip()
    if last_change and SHA_RE.fullmatch(last_change):
        state_file_commit: str | None = last_change
        state_freshness = (
            "CURRENT_HEAD"
            if last_change == current_head
            else "OLDER_THAN_HEAD"
        )
    else:
        state_file_commit = None
        state_freshness = "UNKNOWN_SHALLOW_HISTORY"

    parent_result = _git(
        root,
        "rev-parse",
        f"{current_head}^",
        check=False,
    )
    first_parent = parent_result.stdout.strip()
    if first_parent and SHA_RE.fullmatch(first_parent):
        basis_is_first_parent: bool | None = basis == first_parent
    else:
        basis_is_first_parent = None

    return {
        "schema": SNAPSHOT_SCHEMA,
        "repository": state["repository"],
        "authoritative_branch": state["authoritative_branch"],
        "current_head": current_head,
        "current_branch": current_branch,
        "tracked_worktree_clean": tracked_clean,
        "state_revision": state["revision"],
        "state_file_sha256": hashlib.sha256(raw).hexdigest(),
        "state_file_commit": state_file_commit,
        "state_freshness": state_freshness,
        "repository_basis_commit": basis,
        "basis_relation": basis_relation,
        "basis_is_first_parent": basis_is_first_parent,
        "commits_since_basis": commits_since_basis,
        "qualification_state": state["qualification_state"],
        "capability": state["capability"],
        "architecture": state["architecture"],
        "recorded_last_coherent_ci": state["last_coherent_ci"],
        "current_head_ci": "RESOLVE_FROM_GITHUB_LIVE",
        "production_boundary": state["production_boundary"],
        "transaction_disposition": state["transaction_disposition"],
        "next_objective": state["next_objective"],
        "forbidden_actions": state["forbidden_actions"],
        "resume_procedure": state["resume_procedure"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and validate Keelaryn autonomous development state."
    )
    parser.add_argument(
        "--repository-root",
        default=".",
        help="Repository root containing DEVELOPMENT_STATE.json.",
    )
    parser.add_argument(
        "--require-state-current",
        action="store_true",
        help="Fail unless DEVELOPMENT_STATE.json was changed by current HEAD.",
    )
    parser.add_argument(
        "--require-basis-parent",
        action="store_true",
        help="Fail unless repository_basis_commit is current HEAD first parent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        snapshot = build_snapshot(args.repository_root)
        if (
            args.require_state_current
            and snapshot["state_freshness"] != "CURRENT_HEAD"
        ):
            raise DevelopmentStateError(
                "development state is not current at HEAD"
            )
        if (
            args.require_basis_parent
            and snapshot["basis_is_first_parent"] is not True
        ):
            raise DevelopmentStateError(
                "repository_basis_commit is not current HEAD first parent"
            )
    except DevelopmentStateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
