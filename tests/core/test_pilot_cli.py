from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_model import DriveModel
from keelaryn_core.pilot_cli import DrivePilotCommandSurface, PilotCliError, PilotPackCommandSurface, main
from keelaryn_core.protocol import canonical_json_bytes


class PilotCliTests(unittest.TestCase):
    def fixture(self, root: Path):
        source = root / "source"
        source.mkdir()
        (source / "private-note.md").write_bytes(b"private pilot bytes\n")
        manifest = root / "PILOT_SOURCE.json"
        manifest.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.pilot-source.v1",
                    "pilot_id": "pilot-cli",
                    "entries": [{"source": "private-note.md", "target": "pilot.md"}],
                }
            )
        )
        return source, manifest, root / "pack"

    def test_pack_surface_returns_only_sanitized_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, manifest, output = self.fixture(Path(tmp))
            built = PilotPackCommandSurface.build(str(source), str(manifest), str(output))
            verified = PilotPackCommandSurface.verify(str(output))
            self.assertEqual(built, verified)
            self.assertEqual(
                set(built["pack"]),
                {"schema", "pilot_id", "pack_sha256", "file_count", "total_bytes"},
            )
            rendered = json.dumps(built, sort_keys=True)
            self.assertNotIn("private-note.md", rendered)
            self.assertNotIn("pilot.md", rendered)
            self.assertNotIn("private pilot bytes", rendered)

    def test_pack_build_cli_does_not_require_drive_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, manifest, output = self.fixture(Path(tmp))
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(
                    [
                        "pack-build",
                        "--source-root",
                        str(source),
                        "--source-manifest",
                        str(manifest),
                        "--output-dir",
                        str(output),
                    ]
                )
            self.assertEqual(rc, 0)
            value = json.loads(out.getvalue())
            self.assertEqual(value["pack"]["pilot_id"], "pilot-cli")
            self.assertNotIn("private-note.md", out.getvalue())
            self.assertNotIn("pilot.md", out.getvalue())

    def test_drive_surface_imports_verified_pack_and_emits_sanitized_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, manifest, output = self.fixture(Path(tmp))
            PilotPackCommandSurface.build(str(source), str(manifest), str(output))
            drive = DriveModel()
            hub = drive.create_folder("root", "Disposable Pilot Hub", label="setup.hub")
            value = DrivePilotCommandSurface(drive, hub.file_id).import_pack(str(output))
            pilot = value["pilot"]
            self.assertEqual(pilot["schema"], "keelaryn.pilot-import-evidence.v1")
            self.assertEqual(pilot["pilot_id"], "pilot-cli")
            self.assertEqual(pilot["outcome"], "COMMITTED")
            self.assertEqual(pilot["canonical_epoch"], 1)
            rendered = json.dumps(value, sort_keys=True)
            self.assertNotIn("private-note.md", rendered)
            self.assertNotIn("pilot.md", rendered)
            self.assertNotIn("private pilot bytes", rendered)

    def test_drive_surface_rejects_untrimmed_hub_identity(self) -> None:
        with self.assertRaises(PilotCliError):
            DrivePilotCommandSurface(DriveModel(), " hub ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
