from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_backend import DriveUncertainMutation  # noqa: E402
from keelaryn_core.drive_model import DriveModel  # noqa: E402
from keelaryn_core.pilot_live import (  # noqa: E402
    DrivePrivatePilotLiveService,
    PILOT_HUB_PREFIX,
    PILOT_ROOT_PREFIX,
    SENTINEL_BYTES,
    SENTINEL_NAME,
)
from keelaryn_core.pilot_pack import build_pilot_pack  # noqa: E402
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class UncertainOnceDrive(DriveModel):
    def __init__(self, uncertain_label: str):
        super().__init__()
        self.uncertain_label = uncertain_label
        self.triggered = False

    def create_folder(self, parent_id, name, *, file_id=None, label="drive.create_folder"):
        item = super().create_folder(parent_id, name, file_id=file_id, label=label)
        if label == self.uncertain_label and not self.triggered:
            self.triggered = True
            raise DriveUncertainMutation(f"simulated lost response: {label}")
        return item

    def create_blob(
        self,
        parent_id,
        name,
        content,
        *,
        mime_type="application/octet-stream",
        file_id=None,
        label="drive.create_blob",
    ):
        item = super().create_blob(
            parent_id,
            name,
            content,
            mime_type=mime_type,
            file_id=file_id,
            label=label,
        )
        if label == self.uncertain_label and not self.triggered:
            self.triggered = True
            raise DriveUncertainMutation(f"simulated lost response: {label}")
        return item


class PrivatePilotLiveTests(unittest.TestCase):
    def _pack(self, root: Path):
        source = root / "source"
        source.mkdir()
        (source / "private.md").write_bytes(b"private real-hub-like bytes\r\n")
        manifest = root / "PILOT_SOURCE.json"
        manifest.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.pilot-source.v1",
                    "pilot_id": "pilot-live-unit-001",
                    "entries": [{"source": "private.md", "target": "legacy-private.md"}],
                }
            )
        )
        return build_pilot_pack(source, manifest, root / "pack")

    def _assert_success(self, drive: DriveModel, pack) -> None:
        evidence = DrivePrivatePilotLiveService(drive).run(pack)
        value = evidence.to_json_value()
        self.assertEqual(value["schema"], "keelaryn.private-pilot-live-evidence.v1")
        self.assertTrue(value["safety_root_verified"])
        self.assertTrue(value["sentinel_verified"])
        self.assertTrue(value["disposable_hub_verified"])
        self.assertEqual(value["pilot"]["outcome"], "COMMITTED")
        self.assertEqual(value["pilot"]["canonical_epoch"], 1)

        roots = drive.list_children("root", name=PILOT_ROOT_PREFIX + pack.pilot_id)
        self.assertEqual(len(roots), 1)
        children = drive.list_children(roots[0].file_id)
        self.assertEqual(len(children), 2)
        sentinel = [item for item in children if item.name == SENTINEL_NAME]
        hub = [item for item in children if item.name == PILOT_HUB_PREFIX + pack.pilot_id + "_PILOT"]
        self.assertEqual(len(sentinel), 1)
        self.assertEqual(len(hub), 1)
        self.assertEqual(drive.download(sentinel[0].file_id), SENTINEL_BYTES)

        canonical = drive.exact_name(hub[0].file_id, "canonical")
        self.assertIsNotNone(canonical)
        imported = drive.exact_name(canonical.file_id, "legacy-private.md")
        self.assertIsNotNone(imported)
        self.assertEqual(drive.download(imported.file_id), b"private real-hub-like bytes\r\n")

        rendered = json.dumps(value, sort_keys=True)
        self.assertNotIn("private.md", rendered)
        self.assertNotIn("legacy-private.md", rendered)
        self.assertNotIn("private real-hub-like bytes", rendered)

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._pack(Path(tmp))
            self._assert_success(DriveModel(), pack)

    def test_lost_setup_mutation_responses_reobserve_reserved_ids(self) -> None:
        labels = (
            "drive.private-pilot.root.create",
            "drive.private-pilot.sentinel.create",
            "drive.private-pilot.hub.create",
        )
        for label in labels:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                pack = self._pack(Path(tmp))
                drive = UncertainOnceDrive(label)
                self._assert_success(drive, pack)
                self.assertTrue(drive.triggered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
