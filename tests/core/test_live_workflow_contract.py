from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))


class LiveWorkflowContractTests(unittest.TestCase):
    @staticmethod
    def workflow() -> str:
        return (REPO / ".github" / "workflows" / "development-validation.yml").read_text(encoding="utf-8")

    def test_disposable_drive_job_requires_all_independent_guards(self) -> None:
        raw = self.workflow()
        required = (
            "confirm_disposable_drive:",
            "default: 'NO'",
            "inputs.confirm_disposable_drive == 'YES'",
            "github.event_name == 'workflow_dispatch'",
            "github.ref == 'refs/heads/dev/zero-based-keelaryn'",
            "github.actor == github.repository_owner",
            "KEELARYN_DRIVE_ACCEPT_DISPOSABLE: ${{ secrets.KEELARYN_DISPOSABLE_ENABLE }}",
            "KEELARYN_GOOGLE_CLIENT_ID: ${{ secrets.KEELARYN_DISPOSABLE_GOOGLE_CLIENT_ID }}",
            "KEELARYN_GOOGLE_CLIENT_SECRET: ${{ secrets.KEELARYN_DISPOSABLE_GOOGLE_CLIENT_SECRET }}",
            "KEELARYN_GOOGLE_REFRESH_TOKEN: ${{ secrets.KEELARYN_DISPOSABLE_GOOGLE_REFRESH_TOKEN }}",
            "KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID: ${{ secrets.KEELARYN_DISPOSABLE_ACCEPTANCE_ROOT_ID }}",
            "test '${{ inputs.confirm_disposable_drive }}' = 'YES'",
            "test \"$KEELARYN_DRIVE_ACCEPT_DISPOSABLE\" = 'YES'",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, raw)

    def test_zero_based_live_runs_are_not_cancelled_mid_mutation(self) -> None:
        raw = self.workflow()
        self.assertIn(
            "cancel-in-progress: ${{ github.ref != 'refs/heads/dev/zero-based-keelaryn' }}",
            raw,
        )

    def test_zero_based_branch_remains_isolated_from_legacy_manager_job(self) -> None:
        raw = self.workflow()
        self.assertIn(
            "development-validation:\n    if: ${{ github.ref != 'refs/heads/dev/zero-based-keelaryn' }}",
            raw,
        )
        self.assertIn("zero-based-drive-disposable-acceptance:", raw)

    def test_live_evidence_path_uses_runner_environment_not_job_expression_context(self) -> None:
        raw = self.workflow()
        self.assertNotIn("KEELARYN_LIVE_EVIDENCE: ${{ runner.temp }}", raw)
        self.assertIn("Prepare compact live evidence path", raw)
        self.assertIn(
            'echo "KEELARYN_LIVE_EVIDENCE=$RUNNER_TEMP/ZERO_BASED_DRIVE_LIVE_ACCEPTANCE.json" >> "$GITHUB_ENV"',
            raw,
        )

    def test_live_evidence_is_sanitized_commit_bound_and_short_lived(self) -> None:
        raw = self.workflow()
        required = (
            '"schema": "keelaryn.live-drive-acceptance-evidence.v1"',
            '"source_commit": os.environ["GITHUB_SHA"]',
            '"github_run_id": os.environ["GITHUB_RUN_ID"]',
            '"github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"]',
            'expected_case_keys = {"outcome", "canonical_epoch", "human_surface_verified", "workspace_verified"}',
            "Upload compact disposable Drive evidence",
            "name: zero-based-drive-live-${{ github.sha }}-${{ github.run_attempt }}",
            "if-no-files-found: error",
            "retention-days: 3",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, raw)

    def test_live_job_has_realistic_bounded_execution_budget(self) -> None:
        raw = self.workflow()
        live = raw.split("zero-based-drive-disposable-acceptance:", 1)[1]
        self.assertIn("timeout-minutes: 45", live)
        self.assertNotIn("timeout-minutes: 15", live)

        contract = (REPO / "tests" / "live" / "README.md").read_text(encoding="utf-8")
        self.assertIn("45-minute", contract)
        self.assertIn("must not reuse the same run ID", contract)


if __name__ == "__main__":
    unittest.main(verbosity=2)
