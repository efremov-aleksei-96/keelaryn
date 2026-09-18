from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402

RUNNER = ROOT / "tests" / "live" / "run_migration_candidate_freeze.py"
LAUNCHER = ROOT / "tests" / "live" / "run_migration_candidate_freeze.ps1"


def _load_runner():
    name = "keelaryn_test_migration_candidate_freeze_live_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load migration candidate-freeze runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MigrationCandidateFreezeLiveRunnerTests(unittest.TestCase):
    SOURCE = "a" * 40
    TREE = "b" * 40
    PACK_SHA = "c" * 64
    CANDIDATE = "candidate-001"

    @staticmethod
    def _run(module, env):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def _rehearsal(self, *, source_commit: str | None = None):
        return {
            "schema": "keelaryn.migration-disposable-read-only-finalization.v1",
            "run_id": "private-run-id",
            "construction_source_commit": "d" * 40,
            "current_source_commit": source_commit or self.SOURCE,
            "mutation_closure_file_count": 49,
            "mutation_closure_sha256": "e" * 64,
            "rehearsal": {
                "schema": "keelaryn.migration-rehearsal-evidence.v1",
                "candidate_id": self.CANDIDATE,
                "pack_sha256": self.PACK_SHA,
                "canonical_epoch": 1,
                "canonical_file_count": 155,
                "canonical_total_bytes": 12345,
                "canonical_inventory_sha256": "f" * 64,
                "preserved_file_count": 2,
                "preserved_total_bytes": 45,
                "preservation_inventory_sha256": "1" * 64,
                "project_count": 1,
                "reconciliation_state_sha256": "2" * 64,
                "router_outcome": "COMMITTED",
                "root_index_sha256": "3" * 64,
                "reader_epoch": 1,
                "no_op_phase": "IDLE",
                "restart_state": "READY_CLEAN",
                "outcome": "PASS",
            },
            "existing_hub_reused": True,
            "read_only_guard_enforced": True,
            "drive_mutations_performed": False,
            "production_selector_mutated": False,
        }

    def _freeze_value(self):
        return {
            "status": "FROZEN_UNQUALIFIED",
            "source_commit": self.SOURCE,
            "source_tree": self.TREE,
            "candidate_id": self.CANDIDATE,
            "pack_sha256": self.PACK_SHA,
        }

    def _fixture(self, root: Path, *, source_commit: str | None = None):
        pack = root / "private-pack"
        pack.mkdir()
        receipt = root / "freeze.json"
        evidence = root / "rehearsal.json"
        evidence.write_bytes(
            canonical_json_bytes(self._rehearsal(source_commit=source_commit))
        )
        env = {
            "KEELARYN_MIGRATION_CANDIDATE_FREEZE_ENABLE": "YES",
            "KEELARYN_MIGRATION_PACK_DIR": str(pack),
            "KEELARYN_MIGRATION_FREEZE_RECEIPT": str(receipt),
            "KEELARYN_MIGRATION_REHEARSAL_EVIDENCE": str(evidence),
            "KEELARYN_SOURCE_COMMIT": self.SOURCE,
        }
        fake_pack = SimpleNamespace(
            root=pack,
            candidate_id=self.CANDIDATE,
            pack_sha256=self.PACK_SHA,
        )
        return env, pack, receipt, evidence, fake_pack

    def test_powershell_launcher_streams_final_stdout_and_live_stderr(self):
        self.assertTrue(LAUNCHER.is_file())
        raw = LAUNCHER.read_text(encoding="utf-8")
        for text in (
            "run_migration_candidate_freeze.py",
            "RedirectStandardOutput = $true",
            "RedirectStandardError = $false",
            "StandardOutput.ReadToEnd()",
            "WaitForExit()",
            "exit $Process.ExitCode",
        ):
            with self.subTest(text=text):
                self.assertIn(text, raw)
        self.assertNotIn("2>&1", raw)

    def test_enable_blocks_before_git_pack_or_freeze(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            env, _, _, _, _ = self._fixture(Path(tmp))
            env["KEELARYN_MIGRATION_CANDIDATE_FREEZE_ENABLE"] = "NO"
            with patch.object(module, "_git_identity") as git_identity, patch.object(
                module, "verify_migration_pack"
            ) as pack, patch.object(module, "freeze_migration_candidate") as freeze:
                code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "preflight")
        git_identity.assert_not_called()
        pack.assert_not_called()
        freeze.assert_not_called()

    def test_rehearsal_evidence_must_bind_current_source_before_freeze(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            env, _, _, _, fake_pack = self._fixture(
                Path(tmp),
                source_commit="9" * 40,
            )
            with patch.object(
                module,
                "_git_identity",
                return_value=(ROOT, self.SOURCE, self.TREE),
            ), patch.object(
                module, "verify_migration_pack", return_value=fake_pack
            ), patch.object(module, "freeze_migration_candidate") as freeze:
                code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "rehearsal-evidence")
        freeze.assert_not_called()

    def test_success_publishes_only_sanitized_frozen_unqualified_evidence(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            env, pack, receipt, evidence, fake_pack = self._fixture(Path(tmp))
            freeze_value = self._freeze_value()

            def freeze_side_effect(*args):
                receipt.write_bytes(b'{"status":"FROZEN_UNQUALIFIED"}\n')
                return freeze_value

            with patch.object(
                module,
                "_git_identity",
                return_value=(ROOT, self.SOURCE, self.TREE),
            ), patch.object(
                module, "verify_migration_pack", return_value=fake_pack
            ), patch.object(
                module,
                "freeze_migration_candidate",
                side_effect=freeze_side_effect,
            ) as freeze, patch.object(
                module,
                "verify_migration_candidate_freeze",
                return_value=freeze_value,
            ) as verify:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            public = json.loads(stdout)
            self.assertEqual(public["schema"], module.SCHEMA)
            self.assertEqual(public["status"], "FROZEN_UNQUALIFIED")
            self.assertEqual(public["source_commit"], self.SOURCE)
            self.assertEqual(public["source_tree"], self.TREE)
            self.assertEqual(public["candidate_id"], self.CANDIDATE)
            self.assertEqual(public["pack_sha256"], self.PACK_SHA)
            self.assertEqual(len(public["freeze_receipt_sha256"]), 64)
            self.assertEqual(len(public["rehearsal_evidence_sha256"]), 64)
            self.assertTrue(public["durable_receipt_published"])
            self.assertFalse(public["production_selector_mutated"])
            self.assertFalse(public["cutover_authorized"])
            freeze.assert_called_once_with(
                pack,
                ROOT,
                self.SOURCE,
                self.TREE,
                receipt,
            )
            verify.assert_called_once_with(pack, receipt, ROOT)

            combined = stdout + stderr
            for secret in (
                str(pack),
                str(receipt),
                str(evidence),
                str(ROOT),
                "private-run-id",
            ):
                self.assertNotIn(secret, combined)

    def test_post_commit_failure_explicitly_reports_durable_receipt(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            env, _, _, _, fake_pack = self._fixture(Path(tmp))
            with patch.object(
                module,
                "_git_identity",
                return_value=(ROOT, self.SOURCE, self.TREE),
            ), patch.object(
                module, "verify_migration_pack", return_value=fake_pack
            ), patch.object(
                module,
                "freeze_migration_candidate",
                side_effect=module.MigrationFreezePostCommitBlocked(
                    "private path /secret must never appear"
                ),
            ):
                code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        failure = json.loads(stderr)
        self.assertEqual(failure["phase"], "freeze-post-commit")
        self.assertEqual(
            failure["error_class"],
            "MigrationFreezePostCommitBlocked",
        )
        self.assertTrue(failure["durable_receipt_published"])
        self.assertNotIn("/secret", stderr)

    def test_failure_after_successful_freeze_retains_durable_commit_distinction(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            env, _, receipt, _, fake_pack = self._fixture(Path(tmp))

            def freeze_side_effect(*args):
                receipt.write_bytes(b'{"status":"FROZEN_UNQUALIFIED"}\n')
                return self._freeze_value()

            with patch.object(
                module,
                "_git_identity",
                return_value=(ROOT, self.SOURCE, self.TREE),
            ), patch.object(
                module, "verify_migration_pack", return_value=fake_pack
            ), patch.object(
                module,
                "freeze_migration_candidate",
                side_effect=freeze_side_effect,
            ), patch.object(
                module,
                "verify_migration_candidate_freeze",
                side_effect=RuntimeError("private /secret/path"),
            ):
                code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        failure = json.loads(stderr)
        self.assertEqual(failure["phase"], "post-freeze-verify")
        self.assertTrue(failure["durable_receipt_published"])
        self.assertNotIn("/secret/path", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
