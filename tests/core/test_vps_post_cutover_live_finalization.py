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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "zero-based-vps"
RUNNER = ROOT / "tests" / "live" / "run_migration_post_cutover_acceptance.py"
sys.path.insert(0, str(DEPLOY))

import hub_cutover  # noqa: E402


def _load_runner():
    name = "keelaryn_test_post_cutover_live_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load post-cutover live runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeEvidence:
    def __init__(self, value: dict):
        self.value = value

    def to_json_value(self) -> dict:
        return dict(self.value)


class MigrationPostCutoverLiveFinalizationTests(unittest.TestCase):
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
            mutation_gate_root=root / "mutation-gate",
            executing_tool=DEPLOY / "hub_cutover.py",
        )
        switch.prepare(self.NEW)
        switch.apply()
        return selector, state

    def _env(self, root: Path, selector: Path, state: Path) -> dict[str, str]:
        private = root / "private"
        private.mkdir(mode=0o700)
        active_raw = (state / hub_cutover.ACTIVE_NAME).read_bytes()
        active = json.loads(active_raw.decode("utf-8"))
        acceptance_value = self._acceptance_value(self.NEW)
        pre_apply = {
            "schema": "keelaryn.migration-pre-apply-private-receipt.v2",
            "transaction_id": active["transaction_id"],
            "active_transaction_sha256": hashlib.sha256(active_raw).hexdigest(),
            "source_commit": self.SOURCE,
            "source_tree": acceptance_value["source_tree"],
            "pack_sha256": acceptance_value["pack_sha256"],
            "old_selector_identity_sha256": hashlib.sha256(
                self.OLD.encode("utf-8")
            ).hexdigest(),
            "new_selector_identity_sha256": hashlib.sha256(
                self.NEW.encode("utf-8")
            ).hexdigest(),
            "qualification_evidence_sha256": "7" * 64,
            "target_acceptance_evidence_sha256": hashlib.sha256(
                (
                    json.dumps(
                        acceptance_value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
            ).hexdigest(),
            "pre_apply_finalizer_sha256": active["finalizers"]["pre_apply_sha256"],
            "outcome": "PRE_APPLY_VERIFIED",
        }
        pre_apply_path = private / "pre-apply.json"
        pre_apply_path.write_text(
            json.dumps(
                pre_apply,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(pre_apply_path, 0o600)
        return {
            "KEELARYN_POST_CUTOVER_ACCEPTANCE_ENABLE": "YES",
            "KEELARYN_HUB_SELECTOR_PATH": str(selector),
            "KEELARYN_DEPLOYMENT_STATE_ROOT": str(state),
            "KEELARYN_MUTATION_GATE_ROOT": str(root / "mutation-gate"),
            "KEELARYN_SOURCE_COMMIT": self.SOURCE,
            "KEELARYN_POST_CUTOVER_FINALIZATION_RECEIPT": str(
                private / "finalization-receipt.json"
            ),
            "KEELARYN_PRE_APPLY_CUTOVER_RECEIPT": str(pre_apply_path),
            "KEELARYN_MIGRATION_PACK_DIR": str(private / "pack"),
            "KEELARYN_MIGRATION_FREEZE_RECEIPT": str(private / "freeze.json"),
            "KEELARYN_MIGRATION_TARGET_AUTHORITY": str(
                private / "target-authority.json"
            ),
            "KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE": str(
                private / "qualification.json"
            ),
        }

    @staticmethod
    def _run(module, env: dict[str, str]):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(
            module.hub_cutover,
            "_infer_install_root",
            return_value=None,
        ):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def _acceptance_value(self, selected: str) -> dict:
        selected_sha = hashlib.sha256(selected.encode("utf-8")).hexdigest()
        return {
            "schema": "keelaryn.migration-post-cutover-read-only-acceptance.v1",
            "candidate_id": "candidate",
            "pack_sha256": "1" * 64,
            "source_commit": self.SOURCE,
            "source_tree": "b" * 40,
            "selector_identity_sha256": selected_sha,
            "target_identity_sha256": selected_sha,
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

    def _acceptance_factory(self, *, mutate=None, overrides=None):
        outer = self
        overrides = dict(overrides or {})

        class Acceptance:
            def __init__(self, drive, selected_hub_root_id):
                self.selected = selected_hub_root_id

            def run_qualified_identity(self, *args):
                if mutate is not None:
                    mutate()
                value = outer._acceptance_value(self.selected)
                value.update(overrides)
                return _FakeEvidence(value)

        return Acceptance

    def _patch_success_dependencies(self, module, acceptance):
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
                acceptance,
            ),
            patch.object(
                module,
                "verify_migration_source_against_drive",
                return_value=object(),
            ),
        )

    def test_exact_live_acceptance_binds_transaction_and_terminal_accepts(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)
            acceptance = self._acceptance_factory()
            patches = self._patch_success_dependencies(module, acceptance)
            with patches[0], patches[1], patches[2], patches[3]:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            public = json.loads(stdout)
            self.assertEqual(public["outcome"], "PRODUCTION_CUTOVER_ACCEPTED")
            self.assertEqual(public["hub_cutover_terminal_outcome"], "ACCEPTED")
            self.assertFalse(public["drive_mutations_performed"])
            self.assertEqual(public["source_commit"], self.SOURCE)
            self.assertEqual(len(public["active_transaction_sha256"]), 64)
            self.assertEqual(len(public["acceptance_evidence_sha256"]), 64)
            self.assertEqual(len(public["pre_apply_receipt_sha256"]), 64)
            self.assertEqual(len(public["post_cutover_finalizer_sha256"]), 64)
            self.assertEqual(len(public["selector_identity_sha256"]), 64)
            rendered = json.dumps(public, sort_keys=True)
            self.assertNotIn(self.OLD, rendered)
            self.assertNotIn(self.NEW, rendered)
            self.assertNotIn(str(root), rendered)

            switch = hub_cutover.HubSelectorCutover(
                selector,
                state,
                self.SOURCE,
                mutation_gate_root=root / "mutation-gate",
                executing_tool=DEPLOY / "hub_cutover.py",
            )
            self.assertEqual(switch.status(), {"status": "IDLE"})
            receipt = json.loads(
                Path(env["KEELARYN_POST_CUTOVER_FINALIZATION_RECEIPT"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                receipt["pre_apply_receipt_sha256"],
                public["pre_apply_receipt_sha256"],
            )
            txid = receipt["transaction_id"]
            terminal = json.loads(
                (state / "terminal" / f"{txid}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(terminal["outcome"], "ACCEPTED")

    def test_explicit_enable_is_required_before_oauth_or_transaction_finalization(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)
            env["KEELARYN_POST_CUTOVER_ACCEPTANCE_ENABLE"] = "NO"
            with patch.object(
                module.GoogleOAuthRefreshTokenProvider, "from_environment"
            ) as oauth:
                code, stdout, stderr = self._run(module, env)
            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            failure = json.loads(stderr)
            self.assertEqual(failure["phase"], "preflight")
            oauth.assert_not_called()
            switch = hub_cutover.HubSelectorCutover(
                selector,
                state,
                self.SOURCE,
                mutation_gate_root=root / "mutation-gate",
                executing_tool=DEPLOY / "hub_cutover.py",
            )
            self.assertEqual(switch.status()["status"], "APPLIED")

    def test_post_finalizer_identity_mismatch_blocks_before_oauth(self) -> None:
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
            pre.write_bytes(
                (ROOT / "tests/live/run_migration_pre_apply_cutover.py").read_bytes()
            )
            post.write_bytes(b"altered post-cutover finalizer\n")

            switch = hub_cutover.HubSelectorCutover(
                selector,
                state,
                self.SOURCE,
                mutation_gate_root=gate,
                executing_tool=DEPLOY / "hub_cutover.py",
                finalizer_root=finalizer_root,
            )
            switch.prepare(self.NEW)
            switch.apply()
            env = self._env(root, selector, state)

            with patch.object(
                module.GoogleOAuthRefreshTokenProvider,
                "from_environment",
            ) as oauth:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(stderr)["phase"], "transaction-binding")
            oauth.assert_not_called()
            self.assertEqual(switch.status()["status"], "APPLIED")
            self.assertEqual(switch.rollback(), {"status": "IDLE"})

    def test_acceptance_identity_mismatch_never_creates_terminal_or_receipt(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)
            acceptance = self._acceptance_factory(
                overrides={"selector_identity_sha256": "0" * 64}
            )
            patches = self._patch_success_dependencies(module, acceptance)
            with patches[0], patches[1], patches[2], patches[3]:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            failure = json.loads(stderr)
            self.assertEqual(failure["phase"], "read-only-acceptance")
            receipt = Path(env["KEELARYN_POST_CUTOVER_FINALIZATION_RECEIPT"])
            self.assertFalse(receipt.exists())
            self.assertEqual(list((state / "terminal").glob("*.json")), [])
            switch = hub_cutover.HubSelectorCutover(
                selector,
                state,
                self.SOURCE,
                mutation_gate_root=root / "mutation-gate",
                executing_tool=DEPLOY / "hub_cutover.py",
            )
            self.assertEqual(switch.status()["status"], "APPLIED")

    def test_commit_boundary_selector_change_blocks_after_private_receipt(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)

            def mutate_selector():
                selector.write_bytes(
                    hub_cutover._selector_bytes("OtherHubRoot_0123456789abcdef")
                )
                os.chmod(selector, 0o600)

            acceptance = self._acceptance_factory(mutate=mutate_selector)
            patches = self._patch_success_dependencies(module, acceptance)
            with patches[0], patches[1], patches[2], patches[3]:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            failure = json.loads(stderr)
            self.assertIn(
                failure["phase"],
                {"private-receipt", "commit-boundary-revalidation"},
            )
            self.assertEqual(list((state / "terminal").glob("*.json")), [])

    def test_legacy_source_drift_blocks_before_terminal_acceptance(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)
            acceptance = self._acceptance_factory()
            patches = self._patch_success_dependencies(module, acceptance)
            with patches[0], patches[1], patches[2], patch.object(
                module,
                "verify_migration_source_against_drive",
                side_effect=RuntimeError("legacy source drift"),
            ):
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(stderr)["phase"], "legacy-source-revalidation")
            self.assertEqual(list((state / "terminal").glob("*.json")), [])
            switch = hub_cutover.HubSelectorCutover(
                selector,
                state,
                self.SOURCE,
                mutation_gate_root=root / "mutation-gate",
                executing_tool=DEPLOY / "hub_cutover.py",
            )
            self.assertEqual(switch.status()["status"], "APPLIED")

    def test_exception_text_with_private_values_is_never_emitted(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)

            class FailingAcceptance:
                def __init__(self, drive, selected_hub_root_id):
                    self.selected = selected_hub_root_id

                def run_qualified_identity(self, *args):
                    raise RuntimeError(
                        f"secret {self.selected} {env['KEELARYN_MIGRATION_PACK_DIR']}"
                    )

            patches = self._patch_success_dependencies(module, FailingAcceptance)
            with patches[0], patches[1], patches[2], patches[3]:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            failure = json.loads(stderr)
            self.assertEqual(failure["phase"], "read-only-acceptance")
            self.assertEqual(failure["error_class"], "RuntimeError")
            self.assertNotIn(self.NEW, stderr)
            self.assertNotIn(env["KEELARYN_MIGRATION_PACK_DIR"], stderr)

    def test_second_run_recovers_accepted_terminal_without_oauth(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)
            acceptance = self._acceptance_factory()
            patches = self._patch_success_dependencies(module, acceptance)
            with patches[0], patches[1], patches[2], patches[3]:
                first_code, first_stdout, first_stderr = self._run(module, env)
            self.assertEqual(first_code, 0)
            self.assertEqual(first_stderr, "")

            with patch.object(
                module.GoogleOAuthRefreshTokenProvider,
                "from_environment",
                side_effect=AssertionError("OAuth must not run during terminal recovery"),
            ):
                second_code, second_stdout, second_stderr = self._run(module, env)

            self.assertEqual(second_code, 0)
            self.assertEqual(second_stderr, "")
            self.assertEqual(json.loads(second_stdout), json.loads(first_stdout))

    def test_terminal_recovery_rejects_different_current_cutover_tool_bytes(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)
            acceptance = self._acceptance_factory()
            patches = self._patch_success_dependencies(module, acceptance)
            with patches[0], patches[1], patches[2], patches[3]:
                code, _, stderr = self._run(module, env)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")

            receipt = module._strict_receipt(
                Path(env["KEELARYN_POST_CUTOVER_FINALIZATION_RECEIPT"])
            )
            altered_tool = root / "altered-hub-cutover.py"
            altered_tool.write_bytes(
                (DEPLOY / "hub_cutover.py").read_bytes() + b"\n# altered recovery tool bytes\n"
            )
            wrong_switch = hub_cutover.HubSelectorCutover(
                selector,
                state,
                self.SOURCE,
                mutation_gate_root=root / "mutation-gate",
                executing_tool=altered_tool,
            )
            with self.assertRaisesRegex(
                module.LivePostCutoverFinalizationError,
                "tool identity",
            ):
                module._verify_terminal_recovery(wrong_switch, receipt)

    def test_conflicting_private_receipt_blocks_terminal_acceptance(self) -> None:
        module = _load_runner()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selector, state = self._layout(root)
            env = self._env(root, selector, state)
            receipt = Path(env["KEELARYN_POST_CUTOVER_FINALIZATION_RECEIPT"])
            receipt.write_text('{"conflict":true}\n', encoding="utf-8")
            os.chmod(receipt, 0o600)

            acceptance = self._acceptance_factory()
            patches = self._patch_success_dependencies(module, acceptance)
            with patches[0], patches[1], patches[2], patches[3]:
                code, stdout, stderr = self._run(module, env)

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(stderr)["phase"], "private-receipt")
            self.assertEqual(list((state / "terminal").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
