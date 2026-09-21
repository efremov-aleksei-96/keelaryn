from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import development_state  # noqa: E402


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _state(basis: str) -> dict:
    return {
        "schema": "keelaryn.autonomous-development-state.v1",
        "revision": 2,
        "repository": "efremov-aleksei-96/keelaryn",
        "authoritative_branch": "dev/zero-based-keelaryn",
        "repository_basis_commit": basis,
        "qualification_state": "UNQUALIFIED_DEVELOPMENT",
        "head_resolution": {
            "mode": "RESOLVE_BRANCH_REF_LIVE",
            "state_file_commit_mode": "RESOLVE_LAST_CHANGE_LIVE",
            "rule": "Resolve branch HEAD live before any write.",
        },
        "capability": {
            "current_level": "D0",
            "name": "AUTONOMOUS_ENGINEERING",
            "status": "IN_PROGRESS",
            "product_level": "P0_NOT_STARTED",
        },
        "architecture": {
            "model": "CORPUS_FIRST",
            "old_hub_first_r2": "PROVENANCE_RESEARCH_ONLY",
            "old_hub_cutover": "PAUSED_PENDING_ARCHITECTURE_DISPOSITION",
            "content_authority": "PHYSICAL_CORPUS_PROVIDER",
            "chat_is_durable_state": False,
        },
        "authority": {
            "github": ["source"],
            "vps": ["controlled_runtime"],
            "google_drive": ["real_corpus"],
            "chatgpt": ["engineer"],
        },
        "last_coherent_ci": {
            "scope": "baseline",
            "run_id": 1,
            "conclusion": "PASS",
            "relevance": "HISTORICAL_PRE_D0_BASELINE",
            "note": "Resolve current HEAD CI live.",
        },
        "production_boundary": {
            "freshness": "RECORDED_NOT_LIVE_VERIFIED_IN_D0",
            "source_commit": "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f",
            "hub_cutover_status": "PREPARED",
            "hub_transaction_id": "transaction",
            "selector": "OLD",
            "writer": "INACTIVE_MAINPID_0",
            "installed_operation_control": {
                "candidate": "operation-control-r0005-20260921-01",
                "source_commit": "08f2e211f53764590f6ff0f05f86b2de62c14418",
                "state": "INSTALLED_RUNTIME_ACCEPTED",
            },
            "rule": "Fresh VPS reconciliation before mutation.",
        },
        "constrained_candidates": [
            {
                "candidate": "operation-control-r0001-20260920-01",
                "state": "REJECTED_BEFORE_BOOTSTRAP",
                "retry": "FORBIDDEN",
            },
            {
                "candidate": "operation-control-r0005-20260921-01",
                "state": "INSTALLED_RUNTIME_ACCEPTED",
                "retry": "NOT_A_RETRY_TARGET",
            },
            {
                "candidate": "operation-control-r0006-20260921-01",
                "state": "FROZEN_PRODUCT_OLD_ARCHITECTURE_LINE_PAUSED",
                "source_commit": "b371a9b9f28fe668cc8073019a3d5f352f9d9bf3",
                "retry": "FORBIDDEN_UNTIL_ARCHITECTURE_DISPOSITION",
            },
        ],
        "transaction_disposition": {
            "old_hub_cutover": {
                "state": "PAUSED_PENDING_ARCHITECTURE_DISPOSITION",
                "transaction_id": "transaction",
                "mutation_allowed": False,
            },
            "d0": {
                "state": "ACTIVE",
                "mutation_scope": "DEVELOPMENT_CONTROL_PLANE_ONLY",
            },
        },
        "checkpoint_sources": {
            "primary_human_handoff": "docs/handoffs/d0-current.md",
            "historical_handoff": "docs/handoffs/zero-based-current.md",
            "manager_legacy_state": "MANAGER_DEVELOPMENT_STATE.json",
        },
        "next_objective": {
            "id": "D0-02",
            "description": "Establish reliable read-only VPS state acquisition.",
            "production_mutation_allowed": False,
            "drive_content_mutation_allowed": False,
        },
        "forbidden_actions": ["Blind retry."],
        "resume_procedure": ["Resolve branch HEAD live."],
        "product_after_d0": {
            "target_level": "P0",
            "path": ["PHYSICAL_CORPUS", "READ_ONLY_DISCOVERY"],
            "destructive_normalization_required": False,
        },
    }


class DevelopmentStateValidationTests(unittest.TestCase):
    def test_repository_state_file_validates(self) -> None:
        value = development_state.parse_state_bytes(
            (ROOT / "DEVELOPMENT_STATE.json").read_bytes()
        )
        self.assertEqual(value["schema"], development_state.STATE_SCHEMA)
        self.assertEqual(value["capability"]["current_level"], "D0")

    def test_duplicate_json_key_is_rejected(self) -> None:
        with self.assertRaises(development_state.DevelopmentStateError):
            development_state.parse_state_bytes(
                b'{"schema":"x","schema":"y"}\n'
            )

    def test_extra_top_level_key_is_rejected(self) -> None:
        value = _state("0" * 40)
        value["unexpected"] = True
        with self.assertRaises(development_state.DevelopmentStateError):
            development_state.validate_state(value)

    def test_old_hub_mutation_cannot_be_authorized(self) -> None:
        value = _state("0" * 40)
        value["transaction_disposition"]["old_hub_cutover"][
            "mutation_allowed"
        ] = True
        with self.assertRaises(development_state.DevelopmentStateError):
            development_state.validate_state(value)

    def test_chat_cannot_become_durable_authority(self) -> None:
        value = _state("0" * 40)
        value["architecture"]["chat_is_durable_state"] = True
        with self.assertRaises(development_state.DevelopmentStateError):
            development_state.validate_state(value)


class DevelopmentStateGitTests(unittest.TestCase):
    def _repo_with_current_state(
        self,
    ) -> tuple[tempfile.TemporaryDirectory, Path, str, str]:
        holder = tempfile.TemporaryDirectory()
        root = Path(holder.name)
        _git(root, "init", "-q")
        _git(root, "config", "user.name", "D0 Test")
        _git(root, "config", "user.email", "d0@example.invalid")
        _git(
            root,
            "checkout",
            "-q",
            "-b",
            "dev/zero-based-keelaryn",
        )

        (root / "initial.txt").write_text("base\n", encoding="utf-8")
        _git(root, "add", "initial.txt")
        _git(root, "commit", "-q", "-m", "base")
        basis = _git(root, "rev-parse", "HEAD")

        state = _state(basis)
        (root / "DEVELOPMENT_STATE.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _git(root, "add", "DEVELOPMENT_STATE.json")
        _git(root, "commit", "-q", "-m", "state")
        head = _git(root, "rev-parse", "HEAD")
        return holder, root, basis, head

    def test_snapshot_binds_current_state_to_first_parent(self) -> None:
        holder, root, basis, head = self._repo_with_current_state()
        with holder:
            snapshot = development_state.build_snapshot(root)
            self.assertEqual(snapshot["current_head"], head)
            self.assertEqual(
                snapshot["current_branch"],
                "dev/zero-based-keelaryn",
            )
            self.assertEqual(
                snapshot["state_freshness"], "CURRENT_HEAD"
            )
            self.assertEqual(
                snapshot["repository_basis_commit"], basis
            )
            self.assertEqual(snapshot["basis_relation"], "ANCESTOR")
            self.assertTrue(snapshot["basis_is_first_parent"])
            self.assertEqual(snapshot["commits_since_basis"], 1)
            self.assertTrue(snapshot["tracked_worktree_clean"])

    def test_snapshot_reports_state_older_than_head(self) -> None:
        holder, root, basis, state_head = self._repo_with_current_state()
        with holder:
            (root / "later.txt").write_text(
                "later\n", encoding="utf-8"
            )
            _git(root, "add", "later.txt")
            _git(root, "commit", "-q", "-m", "later")
            snapshot = development_state.build_snapshot(root)
            self.assertEqual(
                snapshot["state_file_commit"], state_head
            )
            self.assertEqual(
                snapshot["state_freshness"], "OLDER_THAN_HEAD"
            )
            self.assertEqual(snapshot["basis_relation"], "ANCESTOR")
            self.assertEqual(snapshot["commits_since_basis"], 2)
            self.assertFalse(snapshot["basis_is_first_parent"])

    def test_cli_requirements_pass_for_current_checkpoint(self) -> None:
        holder, root, _basis, head = self._repo_with_current_state()
        with holder:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = development_state.main(
                    [
                        "--repository-root",
                        str(root),
                        "--require-state-current",
                        "--require-basis-parent",
                    ]
                )
            self.assertEqual(rc, 0, stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["current_head"], head)
            self.assertEqual(
                result["state_freshness"], "CURRENT_HEAD"
            )

    def test_cli_fails_when_checkpoint_is_stale(self) -> None:
        holder, root, _basis, _head = self._repo_with_current_state()
        with holder:
            (root / "later.txt").write_text(
                "later\n", encoding="utf-8"
            )
            _git(root, "add", "later.txt")
            _git(root, "commit", "-q", "-m", "later")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = development_state.main(
                    [
                        "--repository-root",
                        str(root),
                        "--require-state-current",
                        "--require-basis-parent",
                    ]
                )
            self.assertEqual(rc, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("not current", stderr.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
