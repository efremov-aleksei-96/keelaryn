from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "operation_control_r0008_stage.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_r0008_stage",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


class _FakeMaterializer:
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
            "payload_sha256": stage.PAYLOAD_SHA256,
            "payload_size": stage.PAYLOAD_SIZE,
            "file_count": stage.PAYLOAD_FILE_COUNT,
        }

    def materialize_payload(
        self,
        payload: Path,
        releases_root: Path,
        *,
        expected_source_commit: str | None = None,
        expected_payload_sha256: str | None = None,
    ):
        destination = releases_root / stage.SOURCE_COMMIT
        if destination.exists() or destination.is_symlink():
            raise RuntimeError("destination exists")
        destination.mkdir()
        (destination / "EXACT").write_text("exact\n", encoding="utf-8")
        return {
            "source_commit": stage.SOURCE_COMMIT,
            "payload_sha256": stage.PAYLOAD_SHA256,
        }


class R0008StageQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.materializer = _FakeMaterializer()
        self.payload_identity = {
            "source_commit": stage.SOURCE_COMMIT,
            "payload_sha256": stage.PAYLOAD_SHA256,
            "payload_size": stage.PAYLOAD_SIZE,
            "file_count": stage.PAYLOAD_FILE_COUNT,
        }
        self.boundary = {
            "production": stage.prep.PRODUCTION_SOURCE,
            "control": stage.prep.PREDECESSOR_SOURCE_COMMIT,
            "writer": "INACTIVE_MAINPID_0",
            "legacy_hub": "PREPARED_OLD_RUNTIME_SAFETY_ONLY",
        }

    def _payload(self, root: Path) -> Path:
        path = root / "payload.tar.gz"
        path.write_bytes(b"test")
        return path

    def _probe(self, *values):
        return stage._SequenceProbe(list(values))

    def test_cli_exposes_only_disposable_qualification(self) -> None:
        parser = stage._parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(tuple(action.choices), ("qualify",))
        rendered = parser.format_help()
        for forbidden in (" stage", " activate", " upgrade", " delete", " rollback"):
            self.assertNotIn(forbidden, rendered)

    def test_reconcile_distinguishes_absent_residue_foreign_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            releases = Path(td) / "releases"
            releases.mkdir()
            self.assertEqual(
                stage.reconcile_stage(releases, self.materializer)["state"],
                "NOT_STAGED",
            )

            residue = releases / f".{stage.SOURCE_COMMIT}.stage-crash"
            residue.mkdir()
            self.assertEqual(
                stage.reconcile_stage(releases, self.materializer)["state"],
                "RECOVERY_REQUIRED",
            )
            residue.rmdir()

            foreign = releases / stage.SOURCE_COMMIT
            foreign.mkdir()
            self.assertEqual(
                stage.reconcile_stage(releases, self.materializer)["state"],
                "FOREIGN_OR_PARTIAL_DESTINATION",
            )
            foreign.rmdir()

            self.materializer.materialize_payload(
                self._payload(Path(td)),
                releases,
                expected_source_commit=stage.SOURCE_COMMIT,
                expected_payload_sha256=stage.PAYLOAD_SHA256,
            )
            self.assertEqual(
                stage.reconcile_stage(releases, self.materializer)["state"],
                "STAGED_EXACT",
            )
            orphan = releases / f".{stage.SOURCE_COMMIT}.stage-orphan"
            orphan.mkdir()
            self.assertEqual(
                stage.reconcile_stage(releases, self.materializer)["state"],
                "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED",
            )

    def test_absent_stage_and_exact_replay_are_monotonic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            releases = root / "releases"
            releases.mkdir()
            payload = self._payload(root)
            with mock.patch.object(stage, "_verify_payload", return_value=self.payload_identity):
                first = stage.stage_release(
                    payload=payload,
                    releases_root=releases,
                    materializer=self.materializer,
                    boundary_probe=self._probe(self.boundary, self.boundary, self.boundary),
                )
                self.assertEqual(first["state"], "STAGED_EXACT")
                self.assertFalse(first["release_deletion_performed"])
                self.assertFalse(first["activation_allowed"])

                def forbidden(*args, **kwargs):
                    raise AssertionError("exact replay attempted publication")

                second = stage.stage_release(
                    payload=payload,
                    releases_root=releases,
                    materializer=self.materializer,
                    boundary_probe=self._probe(self.boundary, self.boundary),
                    materialize_call=forbidden,
                )
                self.assertEqual(second["state"], "ALREADY_STAGED_EXACT")
                self.assertFalse(second["release_publication_performed"])

    def test_foreign_destination_and_residue_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            releases = root / "releases"
            releases.mkdir()
            payload = self._payload(root)
            foreign = releases / stage.SOURCE_COMMIT
            foreign.mkdir()
            marker = foreign / "foreign"
            marker.write_bytes(b"do-not-touch")
            with mock.patch.object(stage, "_verify_payload", return_value=self.payload_identity):
                with self.assertRaises(stage.StageError) as caught:
                    stage.stage_release(
                        payload=payload,
                        releases_root=releases,
                        materializer=self.materializer,
                        boundary_probe=self._probe(self.boundary, self.boundary),
                    )
            self.assertEqual(caught.exception.code, "FOREIGN_OR_PARTIAL_DESTINATION")
            self.assertEqual(marker.read_bytes(), b"do-not-touch")

            marker.unlink()
            foreign.rmdir()
            residue = releases / f".{stage.SOURCE_COMMIT}.stage-interrupted"
            residue.mkdir()
            residue_marker = residue / "partial"
            residue_marker.write_bytes(b"keep")
            with mock.patch.object(stage, "_verify_payload", return_value=self.payload_identity):
                with self.assertRaises(stage.StageError) as caught:
                    stage.stage_release(
                        payload=payload,
                        releases_root=releases,
                        materializer=self.materializer,
                        boundary_probe=self._probe(self.boundary, self.boundary),
                    )
            self.assertEqual(caught.exception.code, "RECOVERY_REQUIRED")
            self.assertEqual(residue_marker.read_bytes(), b"keep")

    def test_boundary_drift_before_publication_aborts_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            releases = root / "releases"
            releases.mkdir()
            payload = self._payload(root)
            changed = dict(self.boundary)
            changed["writer"] = "ACTIVE:999"

            def forbidden(*args, **kwargs):
                raise AssertionError("materializer ran after boundary drift")

            with mock.patch.object(stage, "_verify_payload", return_value=self.payload_identity):
                with self.assertRaises(stage.StageError) as caught:
                    stage.stage_release(
                        payload=payload,
                        releases_root=releases,
                        materializer=self.materializer,
                        boundary_probe=self._probe(self.boundary, changed),
                        materialize_call=forbidden,
                    )
            self.assertEqual(caught.exception.code, "BOUNDARY_DRIFT_BEFORE_MUTATION")
            self.assertFalse((releases / stage.SOURCE_COMMIT).exists())

    def test_postpublication_uncertainty_recognizes_durable_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            releases = root / "releases"
            releases.mkdir()
            payload = self._payload(root)

            def publish_then_raise(*args, **kwargs):
                self.materializer.materialize_payload(*args, **kwargs)
                raise RuntimeError("lost response")

            with mock.patch.object(stage, "_verify_payload", return_value=self.payload_identity):
                value = stage.stage_release(
                    payload=payload,
                    releases_root=releases,
                    materializer=self.materializer,
                    boundary_probe=self._probe(self.boundary, self.boundary, self.boundary),
                    materialize_call=publish_then_raise,
                )
            self.assertEqual(
                value["state"],
                "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY",
            )
            self.assertTrue(value["requires_reconcile"])
            self.assertEqual(
                stage.reconcile_stage(releases, self.materializer)["state"],
                "STAGED_EXACT",
            )

    def test_postpublication_boundary_drift_keeps_release_and_blocks_activation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            releases = root / "releases"
            releases.mkdir()
            payload = self._payload(root)
            changed = dict(self.boundary)
            changed["writer"] = "ACTIVE:999"
            with mock.patch.object(stage, "_verify_payload", return_value=self.payload_identity):
                value = stage.stage_release(
                    payload=payload,
                    releases_root=releases,
                    materializer=self.materializer,
                    boundary_probe=self._probe(self.boundary, self.boundary, changed),
                )
            self.assertEqual(
                value["state"],
                "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED",
            )
            self.assertTrue(value["requires_reconcile"])
            self.assertFalse(value["activation_allowed"])
            self.assertEqual(
                stage.reconcile_stage(releases, self.materializer)["state"],
                "STAGED_EXACT",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
