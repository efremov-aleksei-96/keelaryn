from __future__ import annotations

import contextlib
import hashlib
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
DEPLOY = ROOT / "deploy" / "zero-based-vps"
RUNNER = ROOT / "tests" / "live" / "run_migration_pre_apply_cutover.py"
if os.name == "posix":
    sys.path.insert(0, str(DEPLOY))
    import hub_cutover  # noqa: E402
else:
    hub_cutover = None


def _load_runner():
    name = "keelaryn_test_migration_pre_apply_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load migration pre-apply runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Evidence:
    def __init__(self, value):
        self.value = value

    def to_json_value(self):
        return dict(self.value)


@unittest.skipUnless(os.name == "posix", "production selector finalizer is POSIX-only")
class MigrationPreApplyCutoverTests(unittest.TestCase):
    SOURCE = "a" * 40
    OLD = "OLDHubRoot_0123456789abcdef"
    NEW = "NEWHubRoot_0123456789abcdef"

    def _layout(self, root: Path):
        selector_parent = root / "etc"
        selector_parent.mkdir(mode=0o700)
        selector = selector_parent / "hub.env"
        selector.write_bytes(hub_cutover._selector_bytes(self.OLD))
        os.chmod(selector, 0o600)
        state = root / "deployment"
        gate = root / "mutation-gate"
        gate.mkdir(mode=0o2750)
        os.chmod(gate, 0o2750)
        lock = gate / "LOCK"
        lock.write_bytes(b"")
        os.chmod(lock, 0o640)
        switch = hub_cutover.HubSelectorCutover(
            selector,
            state,
            self.SOURCE,
            mutation_gate_root=gate,
            executing_tool=DEPLOY / "hub_cutover.py",
        )
        switch.prepare(self.NEW)
        return selector, state, gate

    def _env(self, root, selector, state, gate):
        private = root / "private"
        private.mkdir(mode=0o700)
        qualification = private / "qualification.json"
        qualification.write_bytes(b'{"qualified":true}\n')
        os.chmod(qualification, 0o600)
        return {
            "KEELARYN_PRODUCTION_CUTOVER_ENABLE": "YES",
            "KEELARYN_HUB_SELECTOR_PATH": str(selector),
            "KEELARYN_DEPLOYMENT_STATE_ROOT": str(state),
            "KEELARYN_MUTATION_GATE_ROOT": str(gate),
            "KEELARYN_SOURCE_COMMIT": self.SOURCE,
            "KEELARYN_PRE_APPLY_CUTOVER_RECEIPT": str(private / "pre-apply.json"),
            "KEELARYN_MIGRATION_PACK_DIR": str(private / "pack"),
            "KEELARYN_MIGRATION_FREEZE_RECEIPT": str(private / "freeze.json"),
            "KEELARYN_MIGRATION_TARGET_AUTHORITY": str(private / "target.json"),
            "KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE": str(qualification),
        }

    def _acceptance(self):
        source = self.SOURCE
        new = self.NEW

        class Acceptance:
            def __init__(self, drive, selected):
                if selected != new:
                    raise AssertionError("wrong NEW target")

            def run_qualified_identity(self, *args):
                digest = hashlib.sha256(new.encode("utf-8")).hexdigest()
                return _Evidence(
                    {
                        "schema": "keelaryn.migration-post-cutover-read-only-acceptance.v1",
                        "candidate_id": "candidate",
                        "pack_sha256": "1" * 64,
                        "source_commit": source,
                        "source_tree": "b" * 40,
                        "selector_identity_sha256": digest,
                        "target_identity_sha256": digest,
                        "staging_identity_sha256": "2" * 64,
                        "canonical_epoch": 1,
                        "canonical_file_count": 1,
                        "canonical_total_bytes": 1,
                        "canonical_inventory_sha256": "3" * 64,
                        "preserved_file_count": 0,
                        "preserved_total_bytes": 0,
                        "preservation_inventory_sha256": "4" * 64,
                        "project_count": 0,
                        "reconciliation_state_sha256": "5" * 64,
                        "router_outcome": "NOT_REQUIRED",
                        "root_index_sha256": "6" * 64,
                        "restart_state": "READY_CLEAN",
                        "outcome": "POST_CUTOVER_READ_ONLY_PASS",
                        "drive_mutations_performed": False,
                        "hub_cutover_accept_allowed": True,
                    }
                )

        return Acceptance

    @staticmethod
    def _run(module, env):
        out = io.StringIO()
        err = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(
            module.hub_cutover,
            "_infer_install_root",
            return_value=None,
        ):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = module.main()
        return code, out.getvalue(), err.getvalue()

    def _success_patches(self, module):
        return (
            patch.object(
                module.GoogleOAuthRefreshTokenProvider,
                "from_environment",
                return_value=object(),
            ),
            patch.object(module, "GoogleDriveBackend", return_value=object()),
            patch.object(
                module,
                "DriveMigrationPostCutoverReadOnlyAcceptance",
                self._acceptance(),
            ),
            patch.object(
                module,
                "verify_migration_source_against_drive",
                return_value=object(),
            ),
            patch.object(
                module,
                "verify_migration_pack",
                return_value=SimpleNamespace(
                    pack_sha256="1" * 64,
                    root=Path("/private/frozen-pack"),
                ),
            ),
            patch.object(
                module,
                "verify_migration_candidate_freeze_identity",
                return_value={
                    "source_commit": self.SOURCE,
                    "source_tree": "b" * 40,
                },
            ),
        )

    def test_exact_pre_apply_verification_applies_bound_transaction(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state, gate = self._layout(root)
            env = self._env(root, selector, state, gate)
            patches = self._success_patches(module)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                code, stdout, stderr = self._run(module, env)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(
                hub_cutover._parse_selector(selector.read_bytes()),
                self.NEW,
            )
            public = json.loads(stdout)
            self.assertEqual(public["outcome"], "PRODUCTION_CUTOVER_APPLIED")
            self.assertTrue(public["production_selector_mutated"])
            receipt = module.strict_pre_apply_receipt(
                Path(env["KEELARYN_PRE_APPLY_CUTOVER_RECEIPT"])
            )
            self.assertEqual(receipt["source_commit"], self.SOURCE)
            self.assertEqual(len(receipt["active_transaction_sha256"]), 64)
            self.assertNotIn(self.OLD, stdout)
            self.assertNotIn(self.NEW, stdout)
            self.assertNotIn(str(root), stdout)

    def test_response_loss_recovery_does_not_repeat_oauth_or_apply(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state, gate = self._layout(root)
            env = self._env(root, selector, state, gate)
            patches = self._success_patches(module)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                first = self._run(module, env)
            self.assertEqual(first[0], 0)
            with patch.object(
                module.GoogleOAuthRefreshTokenProvider,
                "from_environment",
                side_effect=AssertionError("OAuth must not repeat after durable apply"),
            ), patch.object(
                module,
                "verify_migration_pack",
                return_value=SimpleNamespace(
                    pack_sha256="1" * 64,
                    root=Path("/private/frozen-pack"),
                ),
            ), patch.object(
                module,
                "verify_migration_candidate_freeze_identity",
                return_value={
                    "source_commit": self.SOURCE,
                    "source_tree": "b" * 40,
                },
            ):
                second = self._run(module, env)
            self.assertEqual(second[0], 0)
            self.assertEqual(json.loads(second[1]), json.loads(first[1]))

    def test_finalizer_identity_mismatch_blocks_before_oauth(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector_parent = root / "etc"
            selector_parent.mkdir(mode=0o700)
            selector = selector_parent / "hub.env"
            selector.write_bytes(hub_cutover._selector_bytes(self.OLD))
            os.chmod(selector, 0o600)
            state = root / "deployment"
            gate = root / "mutation-gate"
            gate.mkdir(mode=0o2750)
            os.chmod(gate, 0o2750)
            lock = gate / "LOCK"
            lock.write_bytes(b"")
            os.chmod(lock, 0o640)

            finalizer_root = root / "release"
            pre = finalizer_root / "tests/live/run_migration_pre_apply_cutover.py"
            post = finalizer_root / "tests/live/run_migration_post_cutover_acceptance.py"
            pre.parent.mkdir(parents=True)
            pre.write_bytes(b"altered pre-apply finalizer\n")
            post.write_bytes(RUNNER.with_name("run_migration_post_cutover_acceptance.py").read_bytes())

            switch = hub_cutover.HubSelectorCutover(
                selector,
                state,
                self.SOURCE,
                mutation_gate_root=gate,
                executing_tool=DEPLOY / "hub_cutover.py",
                finalizer_root=finalizer_root,
            )
            switch.prepare(self.NEW)
            env = self._env(root, selector, state, gate)

            with patch.object(
                module.GoogleOAuthRefreshTokenProvider,
                "from_environment",
            ) as oauth:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(stderr)["phase"], "transaction-binding")
            oauth.assert_not_called()
            self.assertEqual(
                hub_cutover._parse_selector(selector.read_bytes()),
                self.OLD,
            )
            self.assertEqual(switch.rollback(), {"status": "IDLE"})

    def test_source_drift_blocks_before_receipt_or_apply(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state, gate = self._layout(root)
            env = self._env(root, selector, state, gate)
            patches = self._success_patches(module)
            with patches[0], patches[1], patches[2], patch.object(
                module,
                "verify_migration_source_against_drive",
                side_effect=RuntimeError("secret drift"),
            ), patches[4], patches[5]:
                code, stdout, stderr = self._run(module, env)
            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(stderr)["phase"], "legacy-source-verification")
            self.assertEqual(hub_cutover._parse_selector(selector.read_bytes()), self.OLD)
            self.assertFalse(
                Path(env["KEELARYN_PRE_APPLY_CUTOVER_RECEIPT"]).exists()
            )

    def test_explicit_enable_is_required_before_oauth(self):
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state, gate = self._layout(root)
            env = self._env(root, selector, state, gate)
            env["KEELARYN_PRODUCTION_CUTOVER_ENABLE"] = "NO"
            with patch.object(
                module.GoogleOAuthRefreshTokenProvider,
                "from_environment",
            ) as oauth:
                code, stdout, stderr = self._run(module, env)
            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(stderr)["phase"], "preflight")
            oauth.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
