from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "deploy" / "zero-based-vps" / "operation_control_successor_upgrade.py"
SPEC = importlib.util.spec_from_file_location("operation_control_successor_upgrade", MODULE)
assert SPEC is not None and SPEC.loader is not None
upgrade = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = upgrade
SPEC.loader.exec_module(upgrade)


class FakeDrive:
    def __init__(self):
        self.children = {
            "root": [SimpleNamespace(file_id="a", name="My Laptop", trashed=False, is_folder=True)],
            "a": [SimpleNamespace(file_id="b", name="0__Core", trashed=False, is_folder=True)],
            "b": [SimpleNamespace(file_id="c", name="keelaryn", trashed=False, is_folder=True)],
            "c": [SimpleNamespace(file_id="legacy-root", name="hub", trashed=False, is_folder=True)],
        }

    def list_children(self, parent_id):
        return list(self.children.get(parent_id, []))


class SuccessorUpgradeTests(unittest.TestCase):
    def spec(self):
        return upgrade.SuccessorSpec(
            old_source_commit="1" * 40,
            old_payload_sha256="2" * 64,
            new_source_commit="3" * 40,
            new_source_tree="4" * 40,
            new_payload_sha256="5" * 64,
            new_payload_size=123,
            new_payload_file_count=7,
            migration_candidate_id="migration-r0072-20260919-01",
            migration_source_identity_sha256=hashlib.sha256(
                b"legacy-root"
            ).hexdigest(),
        )

    def test_exact_drive_path_resolves_only_matching_identity(self):
        drive = FakeDrive()
        observed = upgrade.resolve_legacy_source_root(
            drive,
            path_segments=upgrade.LEGACY_SOURCE_PATH,
            expected_identity_sha256=hashlib.sha256(
                b"legacy-root"
            ).hexdigest(),
        )
        self.assertEqual(observed, "legacy-root")

    def test_drive_path_rejects_case_conflict(self):
        drive = FakeDrive()
        drive.children["b"].append(
            SimpleNamespace(
                file_id="other",
                name="Keelaryn",
                trashed=False,
                is_folder=True,
            )
        )
        with self.assertRaisesRegex(
            upgrade.SuccessorUpgradeError,
            "case-conflicting",
        ):
            upgrade.resolve_legacy_source_root(
                drive,
                path_segments=upgrade.LEGACY_SOURCE_PATH,
                expected_identity_sha256=hashlib.sha256(
                    b"legacy-root"
                ).hexdigest(),
            )

    def test_drive_path_rejects_identity_mismatch(self):
        with self.assertRaisesRegex(
            upgrade.SuccessorUpgradeError,
            "identity mismatch",
        ):
            upgrade.resolve_legacy_source_root(
                FakeDrive(),
                path_segments=upgrade.LEGACY_SOURCE_PATH,
                expected_identity_sha256="f" * 64,
            )

    def test_target_authority_requires_exact_canonical_schema(self):
        value = {
            "schema": upgrade.TARGET_AUTHORITY_SCHEMA,
            "candidate_id": "migration-r0072-20260919-01",
            "pack_sha256": "a" * 64,
            "staging_root_id": "staging-id",
            "target_id": "target-id",
            "target_name": "target-name",
        }
        raw = upgrade.canonical_json_bytes(value)
        self.assertEqual(
            upgrade._strict_target_authority(raw),
            value,
        )
        with self.assertRaisesRegex(
            upgrade.SuccessorUpgradeError,
            "noncanonical",
        ):
            upgrade._strict_target_authority(
                json.dumps(value, indent=2).encode("utf-8")
            )
        bad = dict(value)
        bad["extra"] = "forbidden"
        with self.assertRaisesRegex(
            upgrade.SuccessorUpgradeError,
            "keys mismatch",
        ):
            upgrade._strict_target_authority(
                upgrade.canonical_json_bytes(bad)
            )

    def test_prepared_snapshot_must_be_stable_across_two_observations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install = root / "install"
            release = install / "releases" / ("a" * 40)
            release.mkdir(parents=True)
            current = install / "current"
            os.symlink(f"releases/{'a' * 40}", current)
            state = root / "state"
            state.mkdir()
            active_path = state / "ACTIVE_TRANSACTION.json"
            active_path.write_bytes(b"ignored")
            os.chmod(active_path, 0o600)

            layout = upgrade.UpgradeLayout(
                install_root=install,
                deployment_state_root=state,
                selector=root / "selector",
                mutation_gate_root=root / "gate",
            )
            first = {
                "schema": "x",
                "transaction_id": "1" * 32,
                "tool": {"source_commit": "a" * 40, "sha256": "b" * 64},
                "finalizers": {},
                "old_hub_root_id": "old-root-identity",
                "new_hub_root_id": "new-root-identity",
            }
            second = dict(first)
            second["transaction_id"] = "2" * 32

            with mock.patch.object(
                upgrade,
                "verify_release_directory",
                return_value={},
            ), mock.patch.object(
                upgrade,
                "_json_command",
                side_effect=[
                    {"status": "PREPARED", "transaction_id": "1" * 32},
                    {"status": "PREPARED", "transaction_id": "2" * 32},
                ],
            ), mock.patch.object(
                upgrade,
                "_read_json_private",
                side_effect=[
                    (b"first", first),
                    (b"second", second),
                ],
            ):
                with self.assertRaisesRegex(
                    upgrade.SuccessorUpgradeError,
                    "changed during stabilization",
                ):
                    upgrade._load_current_hub_authority(layout)

    def test_atomic_private_profile_publication_is_create_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            path = root / "profile.json"
            raw = b'{"schema":"test"}\n'
            published = upgrade._atomic_private_new(
                path,
                raw,
                "profile",
            )
            self.assertEqual(published.read_bytes(), raw)
            if os.name == "posix":
                self.assertEqual(
                    published.stat().st_mode & 0o777,
                    0o600,
                )
            with self.assertRaisesRegex(
                upgrade.SuccessorUpgradeError,
                "already exists",
            ):
                upgrade._atomic_private_new(
                    path,
                    b"different\n",
                    "profile",
                )
            self.assertEqual(path.read_bytes(), raw)

    def test_existing_successor_is_verified_without_rebuild(self):
        spec = self.spec()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = upgrade.UpgradeLayout(install_root=root)
            releases = root / "releases"
            predecessor = releases / spec.old_source_commit
            successor = releases / spec.new_source_commit
            predecessor.mkdir(parents=True)
            successor.mkdir()
            calls = []

            def verify(path, **kwargs):
                calls.append((path, kwargs))
                return {
                    "source_commit": kwargs.get("expected_source_commit"),
                    "payload_sha256": kwargs.get("expected_payload_sha256"),
                }

            with mock.patch.object(
                upgrade,
                "verify_release_directory",
                side_effect=verify,
            ), mock.patch.object(
                upgrade,
                "_checkout_source",
                side_effect=AssertionError("must not rebuild existing exact release"),
            ):
                value = upgrade.materialize_successor(spec, layout)

            self.assertEqual(value["source_commit"], spec.new_source_commit)
            self.assertEqual(len(calls), 2)

    def test_upgrade_uses_exact_successor_updater_and_sanitizes_result(self):
        spec = self.spec()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            release = root / "releases" / spec.new_source_commit
            release.mkdir(parents=True)
            profile = root / "profile.json"
            profile.write_bytes(b"{}\n")
            os.chmod(profile, 0o600)

            updater = SimpleNamespace(
                update_control_plane=mock.Mock(
                    return_value={
                        "schema": "keelaryn.operation-control-update-completed.v1",
                        "transaction_id": "a" * 64,
                    }
                )
            )
            layout = upgrade.UpgradeLayout(
                install_root=root,
                unit_dir=root / "units",
                credential_path=root / "credential",
                operation_control_root=root / "control",
                operation_root=root / "operations",
                transport_root=root / "transport",
                update_root=root / "updates",
            )

            with mock.patch.object(
                upgrade,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                upgrade,
                "materialize_successor",
                return_value={},
            ), mock.patch.object(
                upgrade,
                "build_hub_pre_apply_profile",
                return_value=(b"private", profile),
            ), mock.patch.object(
                upgrade,
                "_load_successor_updater",
                return_value=updater,
            ):
                value = upgrade.upgrade_successor(spec, layout)

            updater.update_control_plane.assert_called_once()
            kwargs = updater.update_control_plane.call_args.kwargs
            self.assertEqual(
                kwargs["expected_old_source_commit"],
                spec.old_source_commit,
            )
            self.assertEqual(
                kwargs["expected_new_source_commit"],
                spec.new_source_commit,
            )
            self.assertEqual(kwargs["profile_source"], profile)
            self.assertEqual(value["control_update"], "COMPLETED")
            self.assertFalse(value["production_current_mutated"])
            self.assertFalse(value["hub_selector_mutated"])
            self.assertFalse(value["drive_mutations_performed"])
            rendered = json.dumps(value, sort_keys=True)
            self.assertNotIn("legacy-root", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
