from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests" / "live" / "run_migration_disposable_read_only_finalizer.py"
LAUNCHER = ROOT / "tests" / "live" / "run_migration_disposable_read_only_finalizer.ps1"


def _load_runner():
    name = "keelaryn_test_migration_disposable_read_only_finalizer"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load migration disposable read-only finalizer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakePack:
    candidate_id = "candidate-001"
    pack_sha256 = "a" * 64
    manifest_raw = b"exact-pack-manifest\n"


class _FakeEvidence:
    def to_json_value(self):
        return {
            "schema": "keelaryn.migration-rehearsal-evidence.v1",
            "candidate_id": "candidate-001",
            "pack_sha256": "a" * 64,
            "canonical_epoch": 1,
            "canonical_file_count": 155,
            "canonical_total_bytes": 12345,
            "canonical_inventory_sha256": "b" * 64,
            "preserved_file_count": 2,
            "preserved_total_bytes": 45,
            "preservation_inventory_sha256": "c" * 64,
            "project_count": 1,
            "reconciliation_state_sha256": "d" * 64,
            "router_outcome": "COMMITTED",
            "root_index_sha256": "e" * 64,
            "reader_epoch": 1,
            "no_op_phase": "IDLE",
            "restart_state": "READY_CLEAN",
            "outcome": "PASS",
        }


class MigrationDisposableReadOnlyFinalizerTests(unittest.TestCase):
    CURRENT = "a" * 40
    MUTATION = "b" * 40

    def _env(self):
        return {
            "KEELARYN_MIGRATION_DISPOSABLE_READ_ONLY_FINALIZE_ENABLE": "YES",
            "KEELARYN_MIGRATION_REHEARSAL_RUN_ID": "candidate-001-run-1",
            "KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID": "drive-acceptance-secret-id",
            "KEELARYN_MIGRATION_PACK_DIR": "/private/migration/candidate-001",
            "KEELARYN_SOURCE_COMMIT": self.CURRENT,
            "KEELARYN_MIGRATION_REHEARSAL_MUTATION_SOURCE_COMMIT": self.MUTATION,
        }

    @staticmethod
    def _run(module, env):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def _provenance(self):
        return {
            "mutation_source_commit": self.MUTATION,
            "current_source_commit": self.CURRENT,
            "mutation_closure_file_count": 48,
            "mutation_closure_sha256": "f" * 64,
        }

    def test_powershell_launcher_streams_final_stdout_and_live_stderr(self):
        self.assertTrue(LAUNCHER.is_file())
        raw = LAUNCHER.read_text(encoding="utf-8")
        for text in (
            "run_migration_disposable_read_only_finalizer.py",
            "RedirectStandardOutput = $true",
            "RedirectStandardError = $false",
            "StandardOutput.ReadToEnd()",
            "WaitForExit()",
            "exit $Process.ExitCode",
        ):
            with self.subTest(text=text):
                self.assertIn(text, raw)
        self.assertNotIn("2>&1", raw)

    def test_enable_blocks_before_git_pack_oauth_or_drive(self):
        module = _load_runner()
        env = self._env()
        env["KEELARYN_MIGRATION_DISPOSABLE_READ_ONLY_FINALIZE_ENABLE"] = "NO"
        with patch.object(module, "_verify_git_provenance") as provenance, patch.object(
            module, "verify_migration_pack"
        ) as pack, patch.object(
            module.GoogleOAuthRefreshTokenProvider, "from_environment"
        ) as oauth:
            code, stdout, stderr = self._run(module, env)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "preflight")
        provenance.assert_not_called()
        pack.assert_not_called()
        oauth.assert_not_called()

    def test_private_pack_inside_repo_blocks_before_git_or_oauth(self):
        module = _load_runner()
        env = self._env()
        env["KEELARYN_MIGRATION_PACK_DIR"] = str(ROOT / "private-pack")
        with patch.object(module, "_verify_git_provenance") as provenance, patch.object(
            module.GoogleOAuthRefreshTokenProvider, "from_environment"
        ) as oauth:
            code, stdout, stderr = self._run(module, env)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "preflight")
        provenance.assert_not_called()
        oauth.assert_not_called()

    def test_git_provenance_binds_clean_head_and_exact_unchanged_mutation_closure(self):
        module = _load_runner()
        env = self._env()

        def fake_git(*args):
            if args == ("rev-parse", "HEAD"):
                return self.CURRENT
            if args == ("status", "--porcelain=v1", "--untracked-files=all"):
                return ""
            if args == ("cat-file", "-e", f"{self.MUTATION}^{{commit}}"):
                return ""
            if args[0] == "rev-parse" and ":" in args[1]:
                path = args[1].split(":", 1)[1]
                return hashlib.sha1(path.encode("utf-8")).hexdigest()
            raise AssertionError(args)

        with patch.dict(os.environ, env, clear=True), patch.object(
            module, "_git", side_effect=fake_git
        ):
            value = module._verify_git_provenance()

        self.assertEqual(value["mutation_source_commit"], self.MUTATION)
        self.assertEqual(value["current_source_commit"], self.CURRENT)
        self.assertEqual(
            value["mutation_closure_file_count"],
            len(module.MUTATION_CLOSURE_PATHS),
        )
        self.assertEqual(len(value["mutation_closure_sha256"]), 64)

    def test_git_provenance_rejects_changed_mutation_closure(self):
        module = _load_runner()
        env = self._env()

        def fake_git(*args):
            if args == ("rev-parse", "HEAD"):
                return self.CURRENT
            if args == ("status", "--porcelain=v1", "--untracked-files=all"):
                return ""
            if args == ("cat-file", "-e", f"{self.MUTATION}^{{commit}}"):
                return ""
            if args[0] == "rev-parse" and ":" in args[1]:
                commit, path = args[1].split(":", 1)
                raw = path.encode("utf-8")
                if commit == self.CURRENT and path == module.MUTATION_CLOSURE_PATHS[0]:
                    raw += b"-changed"
                return hashlib.sha1(raw).hexdigest()
            raise AssertionError(args)

        with patch.dict(os.environ, env, clear=True), patch.object(
            module, "_git", side_effect=fake_git
        ), self.assertRaisesRegex(
            module.LiveMigrationDisposableReadOnlyFinalizationError,
            "closure changed",
        ):
            module._verify_git_provenance()

    def test_read_only_proxy_blocks_every_mutation_before_wrapped_backend(self):
        module = _load_runner()
        backend = Mock()
        proxy = module.ReadOnlyDriveProxy(backend)
        calls = [
            ("generate_ids", (1,)),
            ("create_folder", ()),
            ("create_blob", ()),
            ("copy_blob", ()),
            ("move_rename", ()),
            ("replace_blob_content", ()),
            ("update_content", ()),
            ("trash", ()),
            ("delete", ()),
        ]
        for name, args in calls:
            with self.subTest(name=name), self.assertRaises(
                module.ReadOnlyDriveMutationBlocked
            ):
                getattr(proxy, name)(*args)
        self.assertEqual(proxy.mutation_attempt_count, len(calls))
        for name, _ in calls:
            getattr(backend, name).assert_not_called()

    def test_exact_existing_child_replays_under_read_only_guard_and_sanitizes_pass(self):
        module = _load_runner()
        env = self._env()
        child_name = (
            f"{module.CHILD_PREFIX}Migration_{env['KEELARYN_MIGRATION_REHEARSAL_RUN_ID']}"
        )
        backend = Mock()
        backend.list_children.return_value = [
            SimpleNamespace(
                trashed=False,
                is_folder=True,
                file_id="drive-existing-secret-id",
                name=child_name,
            )
        ]
        captured = {}

        class FakeRehearsal:
            def __init__(self, drive, hub_id, *, progress=None):
                captured["drive"] = drive
                captured["hub_id"] = hub_id

            def run(self, pack_dir):
                captured["pack_dir"] = pack_dir
                return _FakeEvidence()

        with patch.object(
            module, "_verify_git_provenance", return_value=self._provenance()
        ), patch.object(
            module, "verify_migration_pack", side_effect=[_FakePack(), _FakePack()]
        ) as pack, patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(
            module, "GoogleDriveBackend", return_value=backend
        ), patch.object(
            module, "verify_acceptance_root"
        ) as root_guard, patch.object(
            module, "DriveMigrationDisposableRehearsal", FakeRehearsal
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(pack.call_count, 2)
        root_guard.assert_called_once()
        self.assertIsInstance(captured["drive"], module.ReadOnlyDriveProxy)
        self.assertIs(captured["drive"]._drive, backend)
        self.assertEqual(captured["hub_id"], "drive-existing-secret-id")
        self.assertEqual(captured["drive"].mutation_attempt_count, 0)
        public = json.loads(stdout)
        self.assertEqual(public["schema"], module.SCHEMA)
        self.assertEqual(public["rehearsal"]["outcome"], "PASS")
        self.assertTrue(public["existing_hub_reused"])
        self.assertTrue(public["read_only_guard_enforced"])
        self.assertFalse(public["drive_mutations_performed"])
        self.assertFalse(public["production_selector_mutated"])
        self.assertEqual(public["current_source_commit"], self.CURRENT)
        combined = stdout + stderr
        self.assertNotIn("drive-acceptance-secret-id", combined)
        self.assertNotIn("drive-existing-secret-id", combined)
        self.assertNotIn(env["KEELARYN_MIGRATION_PACK_DIR"], combined)
        backend.generate_ids.assert_not_called()
        backend.create_folder.assert_not_called()
        backend.create_blob.assert_not_called()

    def test_missing_exact_child_fails_without_rehearsal_or_mutation(self):
        module = _load_runner()
        env = self._env()
        backend = Mock()
        backend.list_children.return_value = []
        with patch.object(
            module, "_verify_git_provenance", return_value=self._provenance()
        ), patch.object(
            module, "verify_migration_pack", return_value=_FakePack()
        ), patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(
            module, "GoogleDriveBackend", return_value=backend
        ), patch.object(
            module, "verify_acceptance_root"
        ), patch.object(
            module, "DriveMigrationDisposableRehearsal"
        ) as rehearsal:
            code, stdout, stderr = self._run(module, env)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "acceptance-root-guard")
        rehearsal.assert_not_called()
        backend.generate_ids.assert_not_called()
        backend.create_folder.assert_not_called()

    def test_replay_mutation_attempt_is_blocked_and_never_reaches_backend(self):
        module = _load_runner()
        env = self._env()
        child_name = (
            f"{module.CHILD_PREFIX}Migration_{env['KEELARYN_MIGRATION_REHEARSAL_RUN_ID']}"
        )
        backend = Mock()
        backend.list_children.return_value = [
            SimpleNamespace(
                trashed=False,
                is_folder=True,
                file_id="drive-existing-secret-id",
                name=child_name,
            )
        ]

        class MutatingRehearsal:
            def __init__(self, drive, hub_id, *, progress=None):
                self.drive = drive

            def run(self, pack_dir):
                self.drive.generate_ids(1)
                raise AssertionError("unreachable")

        with patch.object(
            module, "_verify_git_provenance", return_value=self._provenance()
        ), patch.object(
            module, "verify_migration_pack", return_value=_FakePack()
        ), patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(
            module, "GoogleDriveBackend", return_value=backend
        ), patch.object(
            module, "verify_acceptance_root"
        ), patch.object(
            module, "DriveMigrationDisposableRehearsal", MutatingRehearsal
        ):
            code, stdout, stderr = self._run(module, env)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        failure = json.loads(stderr)
        self.assertEqual(failure["phase"], "read-only-replay")
        self.assertEqual(failure["error_class"], "ReadOnlyDriveMutationBlocked")
        backend.generate_ids.assert_not_called()

    def test_exception_text_with_private_values_is_never_emitted(self):
        module = _load_runner()
        env = self._env()
        with patch.object(
            module,
            "_verify_git_provenance",
            side_effect=RuntimeError(
                f"secret {env['KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID']} "
                f"{env['KEELARYN_MIGRATION_PACK_DIR']}"
            ),
        ):
            code, stdout, stderr = self._run(module, env)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "git-provenance")
        self.assertNotIn("secret", stderr)
        self.assertNotIn(env["KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID"], stderr)
        self.assertNotIn(env["KEELARYN_MIGRATION_PACK_DIR"], stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
