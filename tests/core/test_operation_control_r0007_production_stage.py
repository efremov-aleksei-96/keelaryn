from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "operation_control_r0007_production_stage.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0007_production_stage",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
prod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prod)


class _FakeMaterializer:
    def verify_payload(
        self,
        raw: bytes,
        *,
        expected_source_commit: str | None = None,
        expected_payload_sha256: str | None = None,
    ):
        return prod.SOURCE_COMMIT, [object()] * prod.PAYLOAD_FILE_COUNT

    def verify_release_directory(
        self,
        destination: Path,
        *,
        expected_source_commit: str | None = None,
        expected_payload_sha256: str | None = None,
    ):
        marker = destination / "EXACT"
        if destination.is_symlink() or not destination.is_dir() or not marker.is_file():
            raise RuntimeError("not exact")
        return {
            "payload_sha256": prod.PAYLOAD_SHA256,
            "payload_size": prod.PAYLOAD_SIZE,
            "file_count": prod.PAYLOAD_FILE_COUNT,
        }

    def materialize_payload(
        self,
        payload: Path,
        releases_root: Path,
        *,
        expected_source_commit: str | None = None,
        expected_payload_sha256: str | None = None,
    ):
        destination = releases_root / prod.SOURCE_COMMIT
        if destination.exists() or destination.is_symlink():
            raise RuntimeError("destination exists")
        destination.mkdir()
        (destination / "EXACT").write_text("exact\n", encoding="utf-8")
        return {"source_commit": prod.SOURCE_COMMIT}


class ProductionStagePrepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.materializer = _FakeMaterializer()
        self.authorization = prod.production_authorization_template()
        self.boundary = {
            "production_source_commit": prod.prep.PRODUCTION_SOURCE,
            "control_source_commit": prod.prep.PREDECESSOR_SOURCE_COMMIT,
            "services": {
                "writer": {"active_state": "INACTIVE", "main_pid": 0},
            },
            "legacy_hub": {
                "status": "PREPARED",
                "selector_role": "OLD",
                "authority_scope": "RUNTIME_SAFETY_ONLY",
            },
            "credential": {"sha256": prod.prep.CREDENTIAL_SHA256},
            "r0007_snapshot_unit": "ABSENT",
        }

    def _root(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        releases = root / "releases"
        releases.mkdir()
        payload = root / "payload.tar.gz"
        payload.write_bytes(b"payload")
        return temporary, root, releases, payload

    def _probe(self, *values):
        return prod._SequenceProbe(list(values))

    def _patch_payload(self):
        return mock.patch.object(
            prod.stage,
            "_verify_payload",
            return_value={
                "source_commit": prod.SOURCE_COMMIT,
                "payload_sha256": prod.PAYLOAD_SHA256,
                "payload_size": prod.PAYLOAD_SIZE,
                "file_count": prod.PAYLOAD_FILE_COUNT,
            },
        )

    def test_cli_exposes_only_qualification(self) -> None:
        parser = prod._parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(tuple(action.choices), ("qualify",))
        rendered = parser.format_help()
        for forbidden in (" stage", " activate", " upgrade", " delete", " rollback"):
            self.assertNotIn(forbidden, rendered)

    def test_authorization_is_exact_stage_only_and_cannot_widen(self) -> None:
        value = prod.validate_authorization(self.authorization)
        self.assertTrue(value["production_stage_authorized"])
        self.assertFalse(value["activation_authorized"])
        self.assertFalse(value["drive_content_mutation_authorized"])
        self.assertFalse(value["legacy_hub_mutation_authorized"])
        self.assertFalse(value["writer_mutation_authorized"])
        self.assertFalse(value["credential_mutation_authorized"])

        widened = dict(self.authorization)
        widened["activation_authorized"] = True
        with self.assertRaises(prod.ProductionStagePrepError) as caught:
            prod.validate_authorization(widened)
        self.assertEqual(caught.exception.code, "AUTHORIZATION_INVALID")

    def test_fresh_precheck_drift_blocks_before_stage_classification(self) -> None:
        temporary, root, releases, payload = self._root()
        self.addCleanup(temporary.cleanup)
        changed = dict(self.boundary)
        changed["r0007_snapshot_unit"] = "PRESENT"
        with mock.patch.object(
            prod.stage,
            "reconcile_stage",
            side_effect=AssertionError("stage state classified after drift"),
        ):
            with self.assertRaises(prod.ProductionStagePrepError) as caught:
                prod.execute_authorized_stage(
                    payload=payload,
                    releases_root=releases,
                    materializer=self.materializer,
                    authorization=self.authorization,
                    boundary_probe=self._probe(self.boundary, changed),
                )
        self.assertEqual(caught.exception.code, "LIVE_BOUNDARY_DRIFT_PRECHECK")

    def test_exact_stage_and_replay_preserve_activation_block(self) -> None:
        temporary, root, releases, payload = self._root()
        self.addCleanup(temporary.cleanup)
        with self._patch_payload():
            first = prod.execute_authorized_stage(
                payload=payload,
                releases_root=releases,
                materializer=self.materializer,
                authorization=self.authorization,
                boundary_probe=self._probe(*([self.boundary] * 8)),
            )
        self.assertEqual(first["state"], "STAGED_EXACT")
        self.assertTrue(first["runtime_anchors_unchanged"])
        self.assertFalse(first["activation_allowed"])
        self.assertFalse(first["release_deletion_allowed"])
        self.assertFalse(first["blind_retry_allowed"])

        def forbidden(*args, **kwargs):
            raise AssertionError("idempotent replay invoked materializer")

        with self._patch_payload():
            replay = prod.execute_authorized_stage(
                payload=payload,
                releases_root=releases,
                materializer=self.materializer,
                authorization=self.authorization,
                boundary_probe=self._probe(*([self.boundary] * 8)),
                materialize_call=forbidden,
            )
        self.assertEqual(replay["state"], "ALREADY_STAGED_EXACT")
        self.assertFalse(replay["release_publication_performed"])

    def test_foreign_and_residue_states_fail_closed_untouched(self) -> None:
        temporary, root, releases, payload = self._root()
        self.addCleanup(temporary.cleanup)
        foreign = releases / prod.SOURCE_COMMIT
        foreign.mkdir()
        marker = foreign / "foreign"
        marker.write_bytes(b"keep")
        before = marker.read_bytes()
        with self.assertRaises(prod.ProductionStagePrepError) as caught:
            prod.execute_authorized_stage(
                payload=payload,
                releases_root=releases,
                materializer=self.materializer,
                authorization=self.authorization,
                boundary_probe=self._probe(self.boundary, self.boundary),
            )
        self.assertEqual(caught.exception.code, "FOREIGN_OR_PARTIAL_DESTINATION")
        self.assertEqual(marker.read_bytes(), before)

        marker.unlink()
        foreign.rmdir()
        residue = releases / f".{prod.SOURCE_COMMIT}.stage-crash"
        residue.mkdir()
        residue_marker = residue / "partial"
        residue_marker.write_bytes(b"keep-residue")
        residue_before = residue_marker.read_bytes()
        with self.assertRaises(prod.ProductionStagePrepError) as caught:
            prod.execute_authorized_stage(
                payload=payload,
                releases_root=releases,
                materializer=self.materializer,
                authorization=self.authorization,
                boundary_probe=self._probe(self.boundary, self.boundary),
            )
        self.assertEqual(caught.exception.code, "RECOVERY_REQUIRED")
        self.assertEqual(residue_marker.read_bytes(), residue_before)

    def test_materializer_uncertainty_recognizes_durable_release(self) -> None:
        temporary, root, releases, payload = self._root()
        self.addCleanup(temporary.cleanup)

        def publish_then_raise(*args, **kwargs):
            self.materializer.materialize_payload(*args, **kwargs)
            raise RuntimeError("response lost")

        with self._patch_payload():
            value = prod.execute_authorized_stage(
                payload=payload,
                releases_root=releases,
                materializer=self.materializer,
                authorization=self.authorization,
                boundary_probe=self._probe(*([self.boundary] * 8)),
                materialize_call=publish_then_raise,
            )
        self.assertEqual(
            value["state"],
            "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY",
        )
        self.assertTrue(value["requires_reconcile"])
        self.assertFalse(value["activation_allowed"])
        self.assertEqual(
            prod.stage.reconcile_stage(releases, self.materializer)["state"],
            "STAGED_EXACT",
        )

    def test_postpublication_boundary_drift_retains_release_and_blocks_activation(self) -> None:
        temporary, root, releases, payload = self._root()
        self.addCleanup(temporary.cleanup)
        changed = {
            **self.boundary,
            "services": {
                "writer": {"active_state": "ACTIVE", "main_pid": 999},
            },
        }
        values = [
            self.boundary,
            self.boundary,
            self.boundary,
            self.boundary,
            changed,
            changed,
            changed,
        ]
        with self._patch_payload():
            value = prod.execute_authorized_stage(
                payload=payload,
                releases_root=releases,
                materializer=self.materializer,
                authorization=self.authorization,
                boundary_probe=self._probe(*values),
            )
        self.assertEqual(
            value["state"],
            "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED",
        )
        self.assertFalse(value["runtime_anchors_unchanged"])
        self.assertTrue(value["requires_reconcile"])
        self.assertFalse(value["activation_allowed"])
        self.assertEqual(
            prod.stage.reconcile_stage(releases, self.materializer)["state"],
            "STAGED_EXACT",
        )

    def test_sanitizer_rejects_raw_hub_ids_and_token_material(self) -> None:
        bad_hub = dict(self.boundary)
        bad_hub["legacy_hub"] = {
            "status": "PREPARED",
            "old_hub_root_id": "secret",
        }
        with self.assertRaises(prod.ProductionStagePrepError) as caught:
            prod._sanitize_boundary(bad_hub)
        self.assertEqual(caught.exception.code, "BOUNDARY_SECRET_LEAK")

        bad_credential = dict(self.boundary)
        bad_credential["credential"] = {
            "sha256": "x",
            "token": "secret",
        }
        with self.assertRaises(prod.ProductionStagePrepError) as caught:
            prod._sanitize_boundary(bad_credential)
        self.assertEqual(caught.exception.code, "BOUNDARY_SECRET_LEAK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
