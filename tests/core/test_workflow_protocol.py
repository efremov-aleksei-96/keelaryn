from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.protocol import ProtocolError
from keelaryn_core.workflow_protocol import (
    validate_drive_result_claim,
    validate_drive_result_claim_plan,
    validate_result_marker,
)


def present(raw: bytes):
    return {"state": "PRESENT", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


class WorkflowProtocolTests(unittest.TestCase):
    def result(self):
        return {
            "schema": "keelaryn.result.v1",
            "state": "READY_FOR_RECONCILIATION",
            "project_id": "project-1",
            "result_id": "result-1",
            "base_canonical_epoch": 7,
            "result_markdown": present(b"# result\n"),
            "canonical_inputs": [
                {"path": "profile/user.md", "observed": present(b"old\n")},
                {"path": "notes/new.md", "observed": {"state": "ABSENT"}},
            ],
            "expected_canonical_targets": ["profile/user.md", "notes/new.md"],
        }

    def plan(self):
        return {
            "schema": "keelaryn.drive-result-claim-plan.v1",
            "state": "PREPARED",
            "project_id": "project-1",
            "result_id": "result-1",
            "base_canonical_epoch": 7,
            "source": {
                "folder_id": "src-folder",
                "result_markdown_id": "src-md",
                "result_marker_id": "src-json",
                "result_markdown": present(b"# result\n"),
                "result_marker": present(b"marker\n"),
            },
            "claimed": {
                "folder_id": "claim-folder",
                "result_markdown_id": "claim-md",
                "result_marker_id": "claim-json",
                "claim_marker_id": "claim-authority",
            },
        }

    def claim(self):
        plan = self.plan()
        return {
            "schema": "keelaryn.drive-result-claim.v1",
            "state": "CLAIMED",
            "project_id": plan["project_id"],
            "result_id": plan["result_id"],
            "base_canonical_epoch": plan["base_canonical_epoch"],
            "claim_plan_id": "claim-plan",
            "claim_plan_sha256": "a" * 64,
            "claim_plan_size": 123,
            "source": copy.deepcopy(plan["source"]),
            "claimed": {
                "folder_id": plan["claimed"]["folder_id"],
                "result_markdown_id": plan["claimed"]["result_markdown_id"],
                "result_marker_id": plan["claimed"]["result_marker_id"],
                "result_markdown": copy.deepcopy(plan["source"]["result_markdown"]),
                "result_marker": copy.deepcopy(plan["source"]["result_marker"]),
            },
        }

    def test_valid_result_plan_and_claim(self) -> None:
        self.assertEqual(validate_result_marker(self.result())["result_id"], "result-1")
        self.assertEqual(validate_drive_result_claim_plan(self.plan())["state"], "PREPARED")
        self.assertEqual(validate_drive_result_claim(self.claim())["state"], "CLAIMED")

    def test_result_rejects_duplicate_inputs_targets_and_absent_markdown(self) -> None:
        cases = []
        duplicate_input = self.result()
        duplicate_input["canonical_inputs"].append(copy.deepcopy(duplicate_input["canonical_inputs"][0]))
        cases.append(duplicate_input)

        duplicate_target = self.result()
        duplicate_target["expected_canonical_targets"].append("profile/user.md")
        cases.append(duplicate_target)

        absent_markdown = self.result()
        absent_markdown["result_markdown"] = {"state": "ABSENT"}
        cases.append(absent_markdown)

        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ProtocolError):
                    validate_result_marker(value)

    def test_plan_rejects_invalid_drive_id_and_identity_reuse(self) -> None:
        invalid = self.plan()
        invalid["source"]["folder_id"] = "bad/id"
        with self.assertRaises(ProtocolError):
            validate_drive_result_claim_plan(invalid)

        reused = self.plan()
        reused["claimed"]["result_marker_id"] = reused["source"]["result_marker_id"]
        with self.assertRaises(ProtocolError):
            validate_drive_result_claim_plan(reused)

        duplicate_reserved = self.plan()
        duplicate_reserved["claimed"]["claim_marker_id"] = duplicate_reserved["claimed"]["result_marker_id"]
        with self.assertRaises(ProtocolError):
            validate_drive_result_claim_plan(duplicate_reserved)

    def test_claim_rejects_copy_fingerprint_divergence_and_same_object_copy(self) -> None:
        changed = self.claim()
        changed["claimed"]["result_markdown"] = present(b"changed\n")
        with self.assertRaises(ProtocolError):
            validate_drive_result_claim(changed)

        same_id = self.claim()
        same_id["claimed"]["result_markdown_id"] = same_id["source"]["result_markdown_id"]
        with self.assertRaises(ProtocolError):
            validate_drive_result_claim(same_id)

    def test_claim_rejects_extra_or_missing_keys(self) -> None:
        extra = self.claim()
        extra["extra"] = True
        with self.assertRaises(ProtocolError):
            validate_drive_result_claim(extra)

        missing = self.claim()
        del missing["claim_plan_size"]
        with self.assertRaises(ProtocolError):
            validate_drive_result_claim(missing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
