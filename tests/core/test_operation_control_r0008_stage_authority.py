from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


authority = _load(
    "operation_control_r0008_stage_authority",
    ROOT / "tools" / "operation_control_r0008_stage_authority.py",
)
issuer = _load(
    "operation_control_r0008_stage_authority_issue",
    ROOT / "tools" / "operation_control_r0008_stage_authority_issue.py",
)


class StageAuthorityTests(unittest.TestCase):
    def test_authority_path_is_transaction_bound(self) -> None:
        tx = "7" * 32
        self.assertEqual(
            authority.authority_path(tx),
            f"{authority.AUTHORITY_ROOT}/{tx}.json",
        )
        with self.assertRaises(authority.StageAuthorityError):
            authority.authority_path("not-a-transaction")

    def test_issuer_renders_only_narrow_stage_authority(self) -> None:
        record = issuer.render_record(
            transaction_id="7" * 32,
            issuer_checkpoint="a" * 40,
            boundary_evidence_path="docs/evidence/fresh.json",
            boundary_evidence_git_blob="b" * 40,
            boundary_evidence_sha256="c" * 64,
        )
        self.assertEqual(record["scope"], authority.SCOPE)
        self.assertTrue(record["production_stage_authorized"])
        self.assertFalse(record["activation_authorized"])
        self.assertFalse(record["drive_content_mutation_authorized"])
        self.assertFalse(record["legacy_hub_mutation_authorized"])
        self.assertFalse(record["writer_mutation_authorized"])
        self.assertFalse(record["credential_mutation_authorized"])
        self.assertEqual(
            record["boundary_evidence_commit"],
            record["issuer_checkpoint"],
        )

    def test_issued_authorization_cannot_be_directly_constructed(self) -> None:
        with self.assertRaises(TypeError):
            authority.IssuedStageAuthorization(
                object(),
                {},
                {},
            )

    def test_production_consumer_rejects_unresolved_dict(self) -> None:
        record = issuer.render_record(
            transaction_id="7" * 32,
            issuer_checkpoint="a" * 40,
            boundary_evidence_path="docs/evidence/fresh.json",
            boundary_evidence_git_blob="b" * 40,
            boundary_evidence_sha256="c" * 64,
        )
        with self.assertRaises(authority.StageAuthorityError) as caught:
            authority.require_issued_authorization(record)
        self.assertEqual(
            caught.exception.code,
            "AUTHORITY_PROVENANCE_REQUIRED",
        )

    def test_boundary_evidence_rejects_semantic_widening(self) -> None:
        evidence = authority.qualification_boundary_evidence()
        authority.validate_boundary_evidence(evidence)

        widened = dict(evidence)
        widened["legacy_hub_authority_scope"] = "CANONICAL_CONTENT_MODEL"
        with self.assertRaises(authority.StageAuthorityError):
            authority.validate_boundary_evidence(widened)

        mutated = dict(evidence)
        mutated["drive_mutations_performed"] = True
        with self.assertRaises(authority.StageAuthorityError):
            authority.validate_boundary_evidence(mutated)

    def test_disposable_git_repo_disables_background_maintenance(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority._init_repo(root)

            def config(name: str) -> str:
                return authority._git(
                    root,
                    ["config", "--local", "--get", name],
                ).stdout.decode("utf-8").strip()

            self.assertEqual(config("maintenance.auto"), "false")
            self.assertEqual(config("gc.auto"), "0")
            self.assertEqual(config("gc.autoPackLimit"), "0")

    def test_disposable_git_provenance_qualification(self) -> None:
        value = authority.qualify(render_record=issuer.render_record)
        self.assertEqual(
            value["schema"],
            "keelaryn.operation-control-r0008-stage-authority-qualification.v1",
        )
        self.assertEqual(value["scenario_count"], 7)
        self.assertFalse(value["consumer_can_mint_authority"])
        self.assertFalse(value["real_authorization_record_issued"])
        self.assertFalse(value["real_vps_stage_performed"])
        self.assertFalse(value["production_mutation_allowed"])
        self.assertFalse(value["drive_content_mutation_allowed"])
        self.assertEqual(
            value["scenarios"],
            {
                "exact_issue_resolve": "PASS",
                "exact_replay": "PASS",
                "same_transaction_substitution": "FAIL_CLOSED",
                "wrong_blob_identity": "FAIL_CLOSED",
                "permission_widening": "FAIL_CLOSED",
                "non_isolated_authority_commit": "FAIL_CLOSED",
                "boundary_binding_substitution": "FAIL_CLOSED",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
