from __future__ import annotations

import contextlib
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
RUNNER = ROOT / "tests" / "live" / "run_migration_disposable_rehearsal.py"


def _load_runner():
    name = "keelaryn_test_migration_disposable_live_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load disposable migration rehearsal runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakePack:
    candidate_id = "candidate-001"
    pack_sha256 = "a" * 64
    manifest_raw = b"exact-pack-manifest\n"


class _FakeEvidence:
    def to_json_value(self) -> dict:
        return {
            "schema": "keelaryn.migration-rehearsal-evidence.v1",
            "candidate_id": "candidate-001",
            "pack_sha256": "a" * 64,
            "canonical_epoch": 1,
            "canonical_file_count": 2,
            "canonical_total_bytes": 123,
            "canonical_inventory_sha256": "b" * 64,
            "preserved_file_count": 1,
            "preserved_total_bytes": 45,
            "preservation_inventory_sha256": "c" * 64,
            "project_count": 1,
            "reconciliation_state_sha256": "d" * 64,
            "router_outcome": "PUBLISHED",
            "root_index_sha256": "e" * 64,
            "reader_epoch": 1,
            "no_op_phase": "IDLE",
            "restart_state": "READY_CLEAN",
            "outcome": "PASS",
        }


class MigrationDisposableLiveRunnerTests(unittest.TestCase):
    def _base_env(self) -> dict[str, str]:
        return {
            "KEELARYN_MIGRATION_DISPOSABLE_REHEARSAL_ENABLE": "YES",
            "KEELARYN_MIGRATION_REHEARSAL_RUN_ID": "candidate-001-run-1",
            "KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID": "drive-acceptance-secret-id",
            "KEELARYN_MIGRATION_PACK_DIR": "/private/migration/candidate-001",
        }

    def _resume_env(self) -> dict[str, str]:
        env = self._base_env()
        env["KEELARYN_MIGRATION_DISPOSABLE_REHEARSAL_RESUME"] = "YES"
        return env

    @staticmethod
    def _run(module, env: dict[str, str]):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_requires_exact_enable_before_pack_oauth_or_drive_use(self) -> None:
        module = _load_runner()
        env = self._base_env()
        env["KEELARYN_MIGRATION_DISPOSABLE_REHEARSAL_ENABLE"] = "NO"

        with patch.object(module, "verify_migration_pack") as pack, patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
        ) as oauth:
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "schema": "keelaryn.migration-disposable-live-failure.v1",
                "phase": "preflight",
                "error_class": "LiveMigrationDisposableRehearsalError",
            },
        )
        pack.assert_not_called()
        oauth.assert_not_called()

    def test_private_pack_inside_repo_blocks_before_oauth(self) -> None:
        module = _load_runner()
        env = self._base_env()
        env["KEELARYN_MIGRATION_PACK_DIR"] = str(ROOT / "private-pack")

        with patch.object(module, "verify_migration_pack") as pack, patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
        ) as oauth:
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "preflight")
        pack.assert_not_called()
        oauth.assert_not_called()

    def test_existing_run_id_blocks_before_child_creation(self) -> None:
        module = _load_runner()
        env = self._base_env()
        fake_drive = Mock()
        fake_drive.list_children.return_value = [
            SimpleNamespace(trashed=False, is_folder=True, file_id="existing", name="existing")
        ]

        with patch.object(module, "verify_migration_pack", return_value=_FakePack()), patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=fake_drive), patch.object(
            module,
            "verify_acceptance_root",
        ), patch.object(module, "DriveMigrationDisposableRehearsal") as rehearsal:
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "acceptance-root-guard")
        fake_drive.generate_ids.assert_not_called()
        fake_drive.create_folder.assert_not_called()
        rehearsal.assert_not_called()

    def test_resume_requires_existing_exact_child_and_never_creates_a_new_one(self) -> None:
        module = _load_runner()
        env = self._resume_env()
        child_name = f"{module.CHILD_PREFIX}Migration_{env['KEELARYN_MIGRATION_REHEARSAL_RUN_ID']}"
        fake_drive = Mock()
        fake_drive.list_children.return_value = [
            SimpleNamespace(
                trashed=False,
                is_folder=True,
                file_id="drive-existing-secret-id",
                name=child_name,
            )
        ]
        captured: dict[str, object] = {}

        class FakeRehearsal:
            def __init__(self, drive, hub_id, *, progress=None):
                captured["drive"] = drive
                captured["hub_id"] = hub_id

            def run(self, pack_dir):
                captured["pack_dir"] = pack_dir
                return _FakeEvidence()

        with patch.object(module, "verify_migration_pack", return_value=_FakePack()) as pack, patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=fake_drive), patch.object(
            module,
            "verify_acceptance_root",
        ) as root_guard, patch.object(
            module,
            "DriveMigrationDisposableRehearsal",
            FakeRehearsal,
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertGreaterEqual(pack.call_count, 2)
        root_guard.assert_called_once_with(fake_drive, env["KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID"])
        fake_drive.generate_ids.assert_not_called()
        fake_drive.create_folder.assert_not_called()
        public = json.loads(stdout)
        self.assertEqual(public["schema"], "keelaryn.migration-disposable-live-run.v1")
        self.assertEqual(public["run_id"], env["KEELARYN_MIGRATION_REHEARSAL_RUN_ID"])
        self.assertEqual(public["rehearsal"]["outcome"], "PASS")
        self.assertTrue(public["existing_hub_reused"])
        self.assertFalse(public["production_selector_mutated"])
        self.assertIs(captured["drive"], fake_drive)
        self.assertEqual(captured["hub_id"], "drive-existing-secret-id")

        combined = stdout + stderr
        self.assertNotIn("drive-acceptance-secret-id", combined)
        self.assertNotIn("drive-existing-secret-id", combined)
        self.assertNotIn(env["KEELARYN_MIGRATION_PACK_DIR"], combined)

    def test_resume_streams_sanitized_progress_json_to_stderr(self) -> None:
        module = _load_runner()
        env = self._resume_env()
        child_name = f"{module.CHILD_PREFIX}Migration_{env['KEELARYN_MIGRATION_REHEARSAL_RUN_ID']}"
        fake_drive = Mock()
        fake_drive.list_children.return_value = [
            SimpleNamespace(
                trashed=False,
                is_folder=True,
                file_id="drive-existing-secret-id",
                name=child_name,
            )
        ]
        captured: dict[str, object] = {}

        class ProgressRehearsal:
            def __init__(self, drive, hub_id, *, progress=None):
                captured["progress"] = progress

            def run(self, pack_dir):
                progress = captured["progress"]
                if callable(progress):
                    progress("topology")
                    progress("ready-change-prepared", 1, 2)
                return _FakeEvidence()

        with patch.object(module, "verify_migration_pack", return_value=_FakePack()), patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=fake_drive), patch.object(
            module,
            "verify_acceptance_root",
        ), patch.object(
            module,
            "DriveMigrationDisposableRehearsal",
            ProgressRehearsal,
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 0)
        self.assertTrue(callable(captured.get("progress")))
        public = json.loads(stdout)
        self.assertEqual(public["schema"], "keelaryn.migration-disposable-live-run.v1")

        progress_lines = [json.loads(line) for line in stderr.splitlines() if line]
        self.assertEqual(
            progress_lines,
            [
                {
                    "schema": "keelaryn.migration-disposable-live-progress.v1",
                    "phase": "topology",
                },
                {
                    "schema": "keelaryn.migration-disposable-live-progress.v1",
                    "phase": "ready-change-prepared",
                    "current": 1,
                    "total": 2,
                },
            ],
        )

        combined = stdout + stderr
        self.assertNotIn("drive-acceptance-secret-id", combined)
        self.assertNotIn("drive-existing-secret-id", combined)
        self.assertNotIn(env["KEELARYN_MIGRATION_PACK_DIR"], combined)

    def test_resume_missing_exact_child_fails_closed_without_creation(self) -> None:
        module = _load_runner()
        env = self._resume_env()
        fake_drive = Mock()
        fake_drive.list_children.return_value = []

        with patch.object(module, "verify_migration_pack", return_value=_FakePack()), patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=fake_drive), patch.object(
            module,
            "verify_acceptance_root",
        ), patch.object(module, "DriveMigrationDisposableRehearsal") as rehearsal:
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["phase"], "acceptance-root-guard")
        fake_drive.generate_ids.assert_not_called()
        fake_drive.create_folder.assert_not_called()
        rehearsal.assert_not_called()

    def test_success_uses_fresh_disposable_child_and_sanitizes_output(self) -> None:
        module = _load_runner()
        env = self._base_env()
        fake_drive = Mock()
        fake_drive.list_children.return_value = []
        fake_drive.generate_ids.return_value = ["drive-child-secret-id"]
        fake_drive.create_folder.return_value = SimpleNamespace(
            file_id="drive-child-secret-id",
            name=f"{module.CHILD_PREFIX}Migration_{env['KEELARYN_MIGRATION_REHEARSAL_RUN_ID']}",
            is_folder=True,
        )
        captured: dict[str, object] = {}

        class FakeRehearsal:
            def __init__(self, drive, hub_id, *, progress=None):
                captured["drive"] = drive
                captured["hub_id"] = hub_id

            def run(self, pack_dir):
                captured["pack_dir"] = pack_dir
                return _FakeEvidence()

        with patch.object(module, "verify_migration_pack", return_value=_FakePack()) as pack, patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=fake_drive), patch.object(
            module,
            "verify_acceptance_root",
        ) as root_guard, patch.object(
            module,
            "DriveMigrationDisposableRehearsal",
            FakeRehearsal,
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertGreaterEqual(pack.call_count, 2)
        root_guard.assert_called_once_with(fake_drive, env["KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID"])
        fake_drive.create_folder.assert_called_once()
        public = json.loads(stdout)
        self.assertEqual(public["schema"], "keelaryn.migration-disposable-live-run.v1")
        self.assertEqual(public["run_id"], env["KEELARYN_MIGRATION_REHEARSAL_RUN_ID"])
        self.assertEqual(public["rehearsal"]["outcome"], "PASS")
        self.assertEqual(public["rehearsal"]["restart_state"], "READY_CLEAN")
        self.assertFalse(public["existing_hub_reused"])
        self.assertFalse(public["production_selector_mutated"])
        self.assertIs(captured["drive"], fake_drive)
        self.assertEqual(captured["hub_id"], "drive-child-secret-id")

        combined = stdout + stderr
        self.assertNotIn("drive-acceptance-secret-id", combined)
        self.assertNotIn("drive-child-secret-id", combined)
        self.assertNotIn(env["KEELARYN_MIGRATION_PACK_DIR"], combined)

    def test_failure_does_not_echo_exception_text_or_private_identity(self) -> None:
        module = _load_runner()
        env = self._base_env()
        fake_drive = Mock()
        fake_drive.list_children.return_value = []
        fake_drive.generate_ids.return_value = ["drive-child-secret-id"]
        fake_drive.create_folder.return_value = SimpleNamespace(
            file_id="drive-child-secret-id",
            name=f"{module.CHILD_PREFIX}Migration_{env['KEELARYN_MIGRATION_REHEARSAL_RUN_ID']}",
            is_folder=True,
        )

        class FailingRehearsal:
            def __init__(self, drive, hub_id, *, progress=None):
                pass

            def run(self, pack_dir):
                raise RuntimeError(
                    "failed at drive-child-secret-id /private/migration/candidate-001"
                )

        with patch.object(module, "verify_migration_pack", return_value=_FakePack()), patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=fake_drive), patch.object(
            module,
            "verify_acceptance_root",
        ), patch.object(
            module,
            "DriveMigrationDisposableRehearsal",
            FailingRehearsal,
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        failure = json.loads(stderr)
        self.assertEqual(failure["phase"], "migration-rehearsal")
        self.assertEqual(failure["error_class"], "RuntimeError")
        self.assertNotIn("drive-child-secret-id", stderr)
        self.assertNotIn("/private/migration/candidate-001", stderr)
        self.assertNotIn("failed at", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
