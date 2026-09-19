from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.drive_model import DriveModel  # noqa: E402
from keelaryn_core.migration_production_qualification import (  # noqa: E402
    STAGING_ROOT_NAME,
    STAGING_SENTINEL_BYTES,
    STAGING_SENTINEL_NAME,
)


def _load_module():
    path = ROOT / "tools" / "provision_zero_based_production_staging_root.py"
    spec = importlib.util.spec_from_file_location("production_staging_provisioner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProductionStagingProvisionerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.tool_sha = "a" * 64

    def _authority(self, root: Path) -> Path:
        private = root / "private"
        private.mkdir(mode=0o700)
        os.chmod(private, 0o700)
        return private / "staging-authority.json"

    def test_fresh_provision_is_exact_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            result = self.module.provision_production_staging(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )

            self.assertEqual(result["status"], "PROVISION_PASS")
            self.assertTrue(result["authority_created"])
            self.assertTrue(result["drive_mutations_performed"])
            self.assertFalse(result["production_selector_mutated"])
            self.assertFalse(result["cutover_authorized"])

            matches = drive.list_children("root", name=STAGING_ROOT_NAME)
            self.assertEqual(len(matches), 1)
            staging = matches[0]
            children = drive.list_children(staging.file_id)
            self.assertEqual(len(children), 1)
            sentinel = children[0]
            self.assertEqual(sentinel.name, STAGING_SENTINEL_NAME)
            self.assertEqual(drive.download(sentinel.file_id), STAGING_SENTINEL_BYTES)

            self.assertEqual(stat.S_IMODE(authority.stat().st_mode), 0o600)
            raw_output = str(result)
            self.assertNotIn(staging.file_id, raw_output)
            self.assertNotIn(sentinel.file_id, raw_output)

    def test_replay_is_idempotent_and_performs_no_drive_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            first = self.module.provision_production_staging(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )
            second = self.module.provision_production_staging(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )

            self.assertTrue(first["drive_mutations_performed"])
            self.assertFalse(second["authority_created"])
            self.assertFalse(second["drive_mutations_performed"])
            self.assertEqual(first["staging_identity_sha256"], second["staging_identity_sha256"])
            self.assertEqual(first["authority_sha256"], second["authority_sha256"])

    def test_unmanaged_existing_root_fails_before_authority_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            drive.create_folder("root", STAGING_ROOT_NAME)
            authority = self._authority(root)

            with self.assertRaisesRegex(
                self.module.ProductionStagingProvisionError,
                "unmanaged production staging root",
            ):
                self.module.provision_production_staging(
                    drive,
                    authority,
                    tool_sha256=self.tool_sha,
                )

            self.assertFalse(authority.exists())

    def test_unexpected_staging_child_blocks_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            self.module.provision_production_staging(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )
            staging = drive.list_children("root", name=STAGING_ROOT_NAME)[0]
            drive.create_blob(staging.file_id, "unexpected.txt", b"block\n")

            with self.assertRaisesRegex(
                self.module.ProductionStagingProvisionError,
                "unexpected objects",
            ):
                self.module.provision_production_staging(
                    drive,
                    authority,
                    tool_sha256=self.tool_sha,
                )

    def test_tool_identity_drift_blocks_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            self.module.provision_production_staging(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )

            with self.assertRaisesRegex(
                self.module.ProductionStagingProvisionError,
                "exact gate identity",
            ):
                self.module.provision_production_staging(
                    drive,
                    authority,
                    tool_sha256="b" * 64,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
