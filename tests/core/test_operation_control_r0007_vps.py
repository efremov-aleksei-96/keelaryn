from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "operation_control_r0007_vps.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0007_vps",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
r0007 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r0007)


class R0007BootstrapPrepTests(unittest.TestCase):
    def _repo_fixture(self, root: Path) -> Path:
        state = json.loads(
            (ROOT / "DEVELOPMENT_STATE.json").read_text(encoding="utf-8")
        )
        evidence = Path(state["production_boundary"]["evidence_path"])
        for relative in (
            Path("DEVELOPMENT_STATE.json"),
            evidence,
            Path("docs/candidates/operation-control-r0007-20260921-01.json"),
        ):
            source = ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return root

    def _select_legacy_evidence(self, root: Path) -> Path:
        relative = Path(r0007.RECORDED_EVIDENCE)
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

        evidence = json.loads(target.read_text(encoding="utf-8"))
        state_path = root / "DEVELOPMENT_STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["production_boundary"]["evidence_path"] = r0007.RECORDED_EVIDENCE
        state["production_boundary"]["observed_at_utc"] = evidence["observed_at_utc"]
        state_path.write_text(
            json.dumps(state),
            encoding="utf-8",
        )
        return target

    def test_parser_exposes_only_read_only_prep_commands(self) -> None:
        parser = r0007._parser()
        command = next(
            action
            for action in parser._actions
            if action.dest == "command"
        )
        self.assertEqual(
            tuple(command.choices),
            ("reconcile", "qualify"),
        )
        rendered = parser.format_help()
        for forbidden in (
            "upgrade",
            "stage",
            "repair",
            "bootstrap",
        ):
            self.assertNotIn(forbidden + "}", rendered)

    def test_recorded_boundary_accepts_current_layered_authority(self) -> None:
        value = r0007._recorded_boundary(ROOT)
        self.assertEqual(
            value["production_source_commit"],
            r0007.PRODUCTION_SOURCE,
        )
        self.assertEqual(
            value["predecessor_source_commit"],
            r0007.PREDECESSOR_SOURCE_COMMIT,
        )
        self.assertEqual(
            value["legacy_hub"]["authority_scope"],
            "RUNTIME_SAFETY_ONLY",
        )
        self.assertEqual(
            value["r0007_transition_gate"],
            "PASS",
        )
        self.assertEqual(
            value["evidence_path"],
            json.loads(
                (ROOT / "DEVELOPMENT_STATE.json").read_text(encoding="utf-8")
            )["production_boundary"]["evidence_path"],
        )

    def test_recorded_boundary_rejects_legacy_hub_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._repo_fixture(Path(td))
            state_path = root / "DEVELOPMENT_STATE.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["architecture"]["legacy_hub_authority"] = (
                "CANONICAL_CONTENT_MODEL"
            )
            state_path.write_text(
                json.dumps(state),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                r0007.PrepError,
                "legacy Hub authority boundary",
            ):
                r0007._recorded_boundary(root)

    def test_recorded_boundary_rejects_partial_successor_residue(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._repo_fixture(Path(td))
            evidence_path = self._select_legacy_evidence(root)
            evidence = json.loads(
                evidence_path.read_text(encoding="utf-8")
            )
            evidence["observation"]["r0007_snapshot_unit"] = "PRESENT"
            evidence_path.write_text(
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                r0007.PrepError,
                "partial successor residue",
            ):
                r0007._recorded_boundary(root)

    def test_recorded_boundary_accepts_legacy_d0_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._repo_fixture(Path(td))
            self._select_legacy_evidence(root)
            value = r0007._recorded_boundary(root)
        self.assertEqual(value["evidence_path"], r0007.RECORDED_EVIDENCE)

    def test_recorded_boundary_rejects_stage_boundary_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._repo_fixture(Path(td))
            state = json.loads(
                (root / "DEVELOPMENT_STATE.json").read_text(encoding="utf-8")
            )
            evidence_path = root / state["production_boundary"]["evidence_path"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["mutation_inhibit_authority_matches"] = False
            evidence_path.write_text(
                json.dumps(evidence),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                r0007.PrepError,
                "stage boundary evidence identity mismatch",
            ):
                r0007._recorded_boundary(root)

    def test_recorded_boundary_rejects_noncanonical_stage_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._repo_fixture(Path(td))
            state = json.loads(
                (root / "DEVELOPMENT_STATE.json").read_text(encoding="utf-8")
            )
            evidence_path = root / state["production_boundary"]["evidence_path"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence_path.write_text(
                json.dumps(evidence, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                r0007.PrepError,
                "stage boundary evidence is not canonical JSON",
            ):
                r0007._recorded_boundary(root)

    def test_recorded_boundary_rejects_unsafe_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self._repo_fixture(Path(td))
            state_path = root / "DEVELOPMENT_STATE.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["production_boundary"]["evidence_path"] = "../escape.json"
            state_path.write_text(
                json.dumps(state),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                r0007.PrepError,
                "evidence path unsafe",
            ):
                r0007._recorded_boundary(root)

    def test_predecessor_materialize_import_supports_dataclass_module(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            releases = Path(td)
            module_path = (
                releases
                / r0007.PREDECESSOR_SOURCE_COMMIT
                / "deploy"
                / "zero-based-vps"
                / "materialize_payload.py"
            )
            module_path.parent.mkdir(parents=True)
            module_path.write_text(
                "from dataclasses import dataclass\n"
                "@dataclass(frozen=True)\n"
                "class Marker:\n"
                "    value: str = 'ok'\n",
                encoding="utf-8",
            )
            module_name = "keelaryn_r0005_materialize_exact"
            previous = sys.modules.pop(module_name, None)
            try:
                with mock.patch.object(r0007, "RELEASES_ROOT", releases):
                    loaded = r0007._load_predecessor_materialize()
                self.assertEqual(loaded.Marker().value, "ok")
                self.assertIs(sys.modules.get(module_name), loaded)
            finally:
                sys.modules.pop(module_name, None)
                if previous is not None:
                    sys.modules[module_name] = previous

    def test_reconcile_requires_identical_two_pass_boundary(self) -> None:
        anchor = {
            "production_source_commit": r0007.PRODUCTION_SOURCE,
            "control_source_commit": r0007.PREDECESSOR_SOURCE_COMMIT,
        }
        with mock.patch.object(
            r0007,
            "_production_anchor",
            side_effect=[anchor, dict(anchor)],
        ):
            value = r0007.reconcile()
        self.assertEqual(
            value["legacy_hub_authority_scope"],
            "RUNTIME_SAFETY_ONLY",
        )
        self.assertFalse(
            value["production_mutations_performed"],
        )
        self.assertFalse(
            value["drive_mutations_performed"],
        )
        self.assertFalse(
            value["production_authorized"],
        )

        changed = dict(anchor)
        changed["control_source_commit"] = "f" * 40
        with mock.patch.object(
            r0007,
            "_production_anchor",
            side_effect=[anchor, changed],
        ):
            with self.assertRaisesRegex(
                r0007.PrepError,
                "changed between read-only passes",
            ):
                r0007.reconcile()

    def test_qualify_is_prep_only_and_requires_future_revalidation(
        self,
    ) -> None:
        recorded = {
            "production_source_commit": r0007.PRODUCTION_SOURCE,
            "predecessor_source_commit": r0007.PREDECESSOR_SOURCE_COMMIT,
            "legacy_hub": {
                "authority_scope": "RUNTIME_SAFETY_ONLY",
            },
        }
        payload = {
            "source_commit": r0007.SOURCE_COMMIT,
            "payload_sha256": r0007.PAYLOAD_SHA256,
            "payload_size": r0007.PAYLOAD_SIZE,
            "file_count": r0007.PAYLOAD_FILE_COUNT,
        }
        release = {
            "release_path_class": "DISPOSABLE_TEMP_ONLY",
        }
        with mock.patch.object(
            r0007,
            "_recorded_boundary",
            return_value=recorded,
        ), mock.patch.object(
            r0007,
            "_checkout_frozen",
            return_value=Path("/disposable/frozen"),
        ), mock.patch.object(
            r0007,
            "_rebuild_frozen",
            return_value=payload,
        ), mock.patch.object(
            r0007,
            "_qualify_materialized_release",
            return_value=release,
        ):
            value = r0007.qualify(ROOT)

        self.assertEqual(
            value["supported_commands"],
            ["qualify", "reconcile"],
        )
        self.assertFalse(value["stage_implemented"])
        self.assertFalse(value["upgrade_implemented"])
        self.assertFalse(value["production_mutation_allowed"])
        self.assertFalse(value["drive_content_mutation_allowed"])
        self.assertFalse(value["production_qualified"])
        self.assertTrue(
            value["requires_fresh_mutation_boundary_revalidation"]
        )
        self.assertEqual(
            value["legacy_hub_authority_scope"],
            "RUNTIME_SAFETY_ONLY",
        )
        self.assertEqual(
            value["next_action"],
            "DESIGN_SEPARATE_STAGE_TRANSACTION",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
