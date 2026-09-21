from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "deploy"
    / "zero-based-vps"
    / "operation_hub_pre_apply.py"
)
SPEC = importlib.util.spec_from_file_location(
    "operation_hub_pre_apply",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def canonical(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


class HubPreApplyWorkerTests(unittest.TestCase):
    def profile(self, source_root: str = "1abcdefghijk") -> dict[str, object]:
        source_hash = hashlib.sha256(source_root.encode("utf-8")).hexdigest()
        return {
            "schema": worker.PROFILE_SCHEMA,
            "operation": "HUB_PRE_APPLY",
            "request_profile": "CURRENT_PREPARED",
            "authorization": "APPROVED",
            "control_source_commit": "0" * 40,
            "transaction_id": "1" * 32,
            "active_transaction_sha256": "2" * 64,
            "framework_source_commit": "3" * 40,
            "candidate_id": "migration-r0072-20260919-01",
            "candidate_source_commit": "4" * 40,
            "candidate_source_tree": "5" * 40,
            "pack_sha256": "6" * 64,
            "freeze_receipt_sha256": "7" * 64,
            "target_authority_sha256": "8" * 64,
            "qualification_evidence_sha256": "9" * 64,
            "credential_sha256": "a" * 64,
            "migration_source_root_id": source_root,
            "migration_source_identity_sha256": source_hash,
            "new_selector_identity_sha256": "b" * 64,
        }

    def test_private_profile_accepts_exact_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            path.write_bytes(canonical(self.profile()))
            os.chmod(path, 0o600)

            observed = worker._load_profile(path)

            self.assertEqual(
                observed["candidate_id"],
                "migration-r0072-20260919-01",
            )

    def test_profile_rejects_migration_source_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            value = self.profile()
            value["migration_source_identity_sha256"] = "c" * 64
            path = Path(td) / "profile.json"
            path.write_bytes(canonical(value))
            os.chmod(path, 0o600)

            with self.assertRaisesRegex(
                worker.HubPreApplyWorkerError,
                "migration source identity mismatch",
            ):
                worker._load_profile(path)

    def test_profile_rejects_noncanonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            path.write_text(
                json.dumps(self.profile(), indent=2),
                encoding="utf-8",
            )
            os.chmod(path, 0o600)

            with self.assertRaisesRegex(
                worker.HubPreApplyWorkerError,
                "not canonical",
            ):
                worker._load_profile(path)

    def test_profile_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = root / "real.json"
            real.write_bytes(canonical(self.profile()))
            os.chmod(real, 0o600)
            link = root / "profile.json"
            link.symlink_to(real)

            with self.assertRaisesRegex(
                worker.HubPreApplyWorkerError,
                "regular file",
            ):
                worker._load_profile(link)


if __name__ == "__main__":
    unittest.main(verbosity=2)
