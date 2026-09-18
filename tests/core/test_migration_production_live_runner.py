from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests" / "live" / "run_migration_production_qualification.py"


def _load_runner():
    name = "keelaryn_test_migration_production_live_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load production qualification live runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeEvidence:
    def __init__(self, value: dict):
        self.value = value

    def to_json_value(self) -> dict:
        return dict(self.value)


class MigrationProductionLiveRunnerTests(unittest.TestCase):
    def _base_env(self) -> dict[str, str]:
        return {
            "KEELARYN_PRODUCTION_TARGET_QUALIFICATION_ENABLE": "YES",
            "KEELARYN_MIGRATION_PACK_DIR": "/private/migration/pack",
            "KEELARYN_MIGRATION_FREEZE_RECEIPT": "/private/migration/freeze.json",
            "KEELARYN_MIGRATION_REPO_ROOT": "/private/source/repo",
            "KEELARYN_MIGRATION_LEGACY_SOURCE_ROOT_ID": "drive-legacy-source-secret-id",
            "KEELARYN_MIGRATION_TARGET_AUTHORITY": "/private/evidence/target-authority.json",
            "KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE": "/private/evidence/qualification.json",
            "KEELARYN_PRODUCTION_MIGRATION_STAGING_ROOT_ID": "drive-staging-secret-id",
            "KEELARYN_MUTATION_GATE_ROOT": "/private/deployment/mutation-gate",
        }

    @staticmethod
    def _run(module, env: dict[str, str], *, gate_context=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        gate = contextlib.nullcontext() if gate_context is None else gate_context
        with patch.dict(os.environ, env, clear=True), patch.object(
            module.DriveMutationGate,
            "from_environment",
            return_value=gate,
        ):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_requires_exact_explicit_enable_before_oauth_or_drive_use(self) -> None:
        module = _load_runner()
        env = self._base_env()
        env["KEELARYN_PRODUCTION_TARGET_QUALIFICATION_ENABLE"] = "NO"

        with patch.object(module.GoogleOAuthRefreshTokenProvider, "from_environment") as oauth:
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "schema": "keelaryn.migration-production-live-failure.v1",
                "phase": "preflight",
                "error_class": "LiveProductionQualificationError",
            },
        )
        oauth.assert_not_called()

    def test_success_emits_only_sanitized_non_cutover_evidence(self) -> None:
        module = _load_runner()
        env = self._base_env()
        captured: dict[str, object] = {}

        class FakeQualification:
            def __init__(self, drive, staging_root_id, legacy_source_root_id):
                captured["drive"] = drive
                captured["staging_root_id"] = staging_root_id
                captured["legacy_source_root_id"] = legacy_source_root_id

            def run_drive(self, *args):
                captured["args"] = args
                return _FakeEvidence(
                    {
                        "schema": "keelaryn.migration-production-target-qualification.v1",
                        "candidate_id": "candidate-001",
                        "pack_sha256": "a" * 64,
                        "source_commit": "b" * 40,
                        "source_tree": "c" * 40,
                        "target_identity_sha256": "d" * 64,
                        "staging_identity_sha256": "e" * 64,
                        "outcome": "TARGET_QUALIFICATION_PASS",
                        "cutover_authorized": False,
                    }
                )

        fake_provider = object()
        fake_drive = object()
        with patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=fake_provider,
        ), patch.object(module, "GoogleDriveBackend", return_value=fake_drive), patch.object(
            module,
            "DriveAuthoritativeMigrationProductionTargetQualification",
            FakeQualification,
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        public = json.loads(stdout)
        self.assertEqual(public["schema"], "keelaryn.migration-production-live-run.v1")
        self.assertFalse(public["production_selector_mutated"])
        self.assertFalse(public["cutover_authorized"])
        self.assertEqual(public["qualification"]["outcome"], "TARGET_QUALIFICATION_PASS")
        self.assertFalse(public["qualification"]["cutover_authorized"])
        self.assertIs(captured["drive"], fake_drive)
        self.assertEqual(
            captured["staging_root_id"],
            env["KEELARYN_PRODUCTION_MIGRATION_STAGING_ROOT_ID"],
        )
        self.assertEqual(
            captured["legacy_source_root_id"],
            env["KEELARYN_MIGRATION_LEGACY_SOURCE_ROOT_ID"],
        )

        combined = stdout + stderr
        for secret in (
            env["KEELARYN_MIGRATION_LEGACY_SOURCE_ROOT_ID"],
            env["KEELARYN_PRODUCTION_MIGRATION_STAGING_ROOT_ID"],
            env["KEELARYN_MIGRATION_PACK_DIR"],
            env["KEELARYN_MIGRATION_FREEZE_RECEIPT"],
            env["KEELARYN_MIGRATION_REPO_ROOT"],
            env["KEELARYN_MIGRATION_TARGET_AUTHORITY"],
            env["KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE"],
            env["KEELARYN_MUTATION_GATE_ROOT"],
        ):
            self.assertNotIn(secret, combined)

    def test_mutation_gate_blocks_before_oauth_or_drive_use(self) -> None:
        module = _load_runner()
        env = self._base_env()

        class BlockingGate:
            def __enter__(self):
                raise RuntimeError("mutation gate blocked")

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
        ) as oauth:
            code, stdout, stderr = self._run(
                module,
                env,
                gate_context=BlockingGate(),
            )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(
            json.loads(stderr),
            {
                "schema": "keelaryn.migration-production-live-failure.v1",
                "phase": "mutation-gate",
                "error_class": "RuntimeError",
            },
        )
        oauth.assert_not_called()

    def test_failure_never_echoes_exception_text_drive_id_or_private_path(self) -> None:
        module = _load_runner()
        env = self._base_env()

        class FailingQualification:
            def __init__(self, drive, staging_root_id, legacy_source_root_id):
                pass

            def run_drive(self, *args):
                raise RuntimeError(
                    "transport failed for drive-legacy-source-secret-id and drive-staging-secret-id"
                )

        with patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=object()), patch.object(
            module,
            "DriveAuthoritativeMigrationProductionTargetQualification",
            FailingQualification,
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        failure = json.loads(stderr)
        self.assertEqual(failure["schema"], "keelaryn.migration-production-live-failure.v1")
        self.assertEqual(failure["phase"], "production-target-qualification")
        self.assertEqual(failure["error_class"], "RuntimeError")
        self.assertNotIn("drive-legacy-source-secret-id", stderr)
        self.assertNotIn("drive-staging-secret-id", stderr)
        self.assertNotIn("transport failed", stderr)

    def test_wrapper_detects_private_identity_leak_before_printing_success(self) -> None:
        module = _load_runner()
        env = self._base_env()

        class LeakingQualification:
            def __init__(self, drive, staging_root_id, legacy_source_root_id):
                pass

            def run_drive(self, *args):
                return _FakeEvidence(
                    {
                        "outcome": "TARGET_QUALIFICATION_PASS",
                        "cutover_authorized": False,
                        "unexpected": env["KEELARYN_MIGRATION_LEGACY_SOURCE_ROOT_ID"],
                    }
                )

        with patch.object(
            module.GoogleOAuthRefreshTokenProvider,
            "from_environment",
            return_value=object(),
        ), patch.object(module, "GoogleDriveBackend", return_value=object()), patch.object(
            module,
            "DriveAuthoritativeMigrationProductionTargetQualification",
            LeakingQualification,
        ):
            code, stdout, stderr = self._run(module, env)

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        failure = json.loads(stderr)
        self.assertEqual(failure["phase"], "evidence")
        self.assertEqual(failure["error_class"], "LiveProductionQualificationError")
        self.assertNotIn(env["KEELARYN_MIGRATION_LEGACY_SOURCE_ROOT_ID"], stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
