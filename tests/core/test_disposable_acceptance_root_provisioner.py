from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "tests" / "live"))

from drive_disposable_acceptance import (  # noqa: E402
    ACCEPTANCE_ROOT_NAME as LIVE_ROOT_NAME,
    CHILD_PREFIX as LIVE_CHILD_PREFIX,
    SENTINEL_BYTES as LIVE_SENTINEL_BYTES,
    SENTINEL_NAME as LIVE_SENTINEL_NAME,
)
from keelaryn_core.drive_model import DriveModel  # noqa: E402


def _load_module():
    path = ROOT / "tools" / "provision_zero_based_disposable_acceptance_root.py"
    spec = importlib.util.spec_from_file_location("disposable_acceptance_provisioner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _OpaqueGoogleRootParentDrive(DriveModel):
    def __init__(self) -> None:
        super().__init__()
        self._acceptance_id: str | None = None

    def create_folder(self, parent_id, name, **kwargs):
        item = super().create_folder(parent_id, name, **kwargs)
        if parent_id == "root" and name == LIVE_ROOT_NAME:
            self._acceptance_id = item.file_id
        return item

    def get(self, file_id, *, include_trashed=True):
        item = super().get(file_id, include_trashed=include_trashed)
        if file_id == self._acceptance_id:
            return replace(item, parent_id="opaque-google-root-folder-id")
        return item


class DisposableAcceptanceRootProvisionerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.tool_sha = "a" * 64

    def _authority(self, root: Path) -> Path:
        private = root / "private"
        private.mkdir(mode=0o700)
        os.chmod(private, 0o700)
        return private / "acceptance-authority.json"

    def test_contract_matches_live_disposable_acceptance_gate(self) -> None:
        self.assertEqual(self.module.ACCEPTANCE_ROOT_NAME, LIVE_ROOT_NAME)
        self.assertEqual(self.module.SENTINEL_NAME, LIVE_SENTINEL_NAME)
        self.assertEqual(self.module.SENTINEL_BYTES, LIVE_SENTINEL_BYTES)
        self.assertEqual(self.module.CHILD_PREFIX, LIVE_CHILD_PREFIX)

    def test_fresh_provision_is_exact_private_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            result = self.module.provision_disposable_acceptance_root(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )

            self.assertEqual(result["status"], "PROVISION_PASS")
            self.assertTrue(result["authority_created"])
            self.assertTrue(result["drive_mutations_performed"])
            self.assertEqual(result["existing_disposable_child_count"], 0)
            self.assertFalse(result["production_selector_mutated"])
            self.assertFalse(result["cutover_authorized"])

            matches = drive.list_children("root", name=LIVE_ROOT_NAME)
            self.assertEqual(len(matches), 1)
            acceptance = matches[0]
            children = drive.list_children(acceptance.file_id)
            self.assertEqual(len(children), 1)
            sentinel = children[0]
            self.assertEqual(sentinel.name, LIVE_SENTINEL_NAME)
            self.assertEqual(drive.download(sentinel.file_id), LIVE_SENTINEL_BYTES)

            self.assertEqual(stat.S_IMODE(authority.stat().st_mode), 0o600)
            raw_output = str(result)
            self.assertNotIn(acceptance.file_id, raw_output)
            self.assertNotIn(sentinel.file_id, raw_output)

    def test_google_root_alias_may_round_trip_as_opaque_parent_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = _OpaqueGoogleRootParentDrive()
            authority = self._authority(root)

            result = self.module.provision_disposable_acceptance_root(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )

            self.assertEqual(result["status"], "PROVISION_PASS")
            matches = drive.list_children("root", name=LIVE_ROOT_NAME)
            self.assertEqual(len(matches), 1)

    def test_replay_is_idempotent_and_performs_no_drive_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            first = self.module.provision_disposable_acceptance_root(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )
            second = self.module.provision_disposable_acceptance_root(
                drive,
                authority,
                tool_sha256="b" * 64,
            )

            self.assertTrue(first["drive_mutations_performed"])
            self.assertFalse(second["authority_created"])
            self.assertFalse(second["drive_mutations_performed"])
            self.assertEqual(first["authority_sha256"], second["authority_sha256"])
            self.assertEqual(
                first["acceptance_root_identity_sha256"],
                second["acceptance_root_identity_sha256"],
            )

    def test_replay_allows_exact_disposable_child_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            self.module.provision_disposable_acceptance_root(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )

            acceptance = drive.list_children("root", name=LIVE_ROOT_NAME)[0]
            drive.create_folder(
                acceptance.file_id,
                LIVE_CHILD_PREFIX + "migration-r0072-test",
            )

            result = self.module.provision_disposable_acceptance_root(
                drive,
                authority,
                tool_sha256="b" * 64,
            )

            self.assertFalse(result["drive_mutations_performed"])
            self.assertEqual(result["existing_disposable_child_count"], 1)

    def test_unmanaged_existing_root_fails_before_authority_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            drive.create_folder("root", LIVE_ROOT_NAME)
            authority = self._authority(root)

            with self.assertRaisesRegex(
                self.module.DisposableAcceptanceProvisionError,
                "unmanaged disposable acceptance root",
            ):
                self.module.provision_disposable_acceptance_root(
                    drive,
                    authority,
                    tool_sha256=self.tool_sha,
                )

            self.assertFalse(authority.exists())

    def test_unexpected_child_blocks_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drive = DriveModel()
            authority = self._authority(root)

            self.module.provision_disposable_acceptance_root(
                drive,
                authority,
                tool_sha256=self.tool_sha,
            )
            acceptance = drive.list_children("root", name=LIVE_ROOT_NAME)[0]
            drive.create_blob(acceptance.file_id, "unexpected.txt", b"block\n")

            with self.assertRaisesRegex(
                self.module.DisposableAcceptanceProvisionError,
                "unexpected objects",
            ):
                self.module.provision_disposable_acceptance_root(
                    drive,
                    authority,
                    tool_sha256=self.tool_sha,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
