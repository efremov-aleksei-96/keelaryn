from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "zero-based-vps"
MODULE_PATH = DEPLOY / "operation_control_plane_update.py"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_plane_update",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


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


class ControlPlaneUpdateTests(unittest.TestCase):
    OLD = "1" * 40
    NEW = "2" * 40
    PROD = "3" * 40
    OLD_PAYLOAD = "4" * 64
    NEW_PAYLOAD = "5" * 64

    def layout(self, root: Path):
        install = root / "opt" / "keelaryn"
        releases = install / "releases"
        old = releases / self.OLD
        new = releases / self.NEW
        for release in (old, new):
            deploy = release / "deploy" / "zero-based-vps"
            deploy.mkdir(parents=True)
        for name in update.PERSISTENT_UNITS:
            (old / "deploy" / "zero-based-vps" / name).write_bytes(
                f"old:{name}\n".encode()
            )
            (new / "deploy" / "zero-based-vps" / name).write_bytes(
                f"new:{name}\n".encode()
            )
        (new / "deploy" / "zero-based-vps" / update.WORKER_UNIT).write_bytes(
            b"worker\n"
        )

        os.symlink(f"releases/{self.PROD}", install / "current")
        os.symlink(f"releases/{self.OLD}", install / "control-current")

        unit_dir = root / "systemd"
        unit_dir.mkdir()
        for name in update.PERSISTENT_UNITS:
            target = unit_dir / name
            target.write_bytes(
                (old / "deploy" / "zero-based-vps" / name).read_bytes()
            )
            os.chmod(target, 0o644)

        config = root / "etc" / "keelaryn" / "operation-control"
        config.mkdir(parents=True, mode=0o700)
        os.chmod(config, 0o700)
        credential = config / "github-operations.env"
        credential.write_bytes(b"TOKEN=private\n")
        os.chmod(credential, 0o600)

        control = root / "var" / "operation-control"
        control.mkdir(parents=True, mode=0o700)
        os.chmod(control, 0o700)

        operations = root / "var" / "operations"
        operations.mkdir(mode=0o700)
        os.chmod(operations, 0o700)

        transport = root / "var" / "transport"
        inbox = transport / "inbox"
        outbox = transport / "outbox"
        transport.mkdir(mode=0o750)
        inbox.mkdir(mode=0o770)
        outbox.mkdir(mode=0o770)

        updates = root / "var" / "updates"

        source_root = "1abcdefghijk"
        profile_value = {
            "schema": "keelaryn.operation-hub-pre-apply-profile.v1",
            "operation": "HUB_PRE_APPLY",
            "request_profile": "CURRENT_PREPARED",
            "authorization": "APPROVED",
            "control_source_commit": self.NEW,
            "transaction_id": "6" * 32,
            "active_transaction_sha256": "7" * 64,
            "framework_source_commit": "8" * 40,
            "candidate_id": "migration-r0072-20260919-01",
            "candidate_source_commit": "9" * 40,
            "candidate_source_tree": "a" * 40,
            "pack_sha256": "b" * 64,
            "freeze_receipt_sha256": "c" * 64,
            "target_authority_sha256": "d" * 64,
            "qualification_evidence_sha256": "e" * 64,
            "credential_sha256": "f" * 64,
            "migration_source_root_id": source_root,
            "migration_source_identity_sha256": hashlib.sha256(
                source_root.encode()
            ).hexdigest(),
            "new_selector_identity_sha256": "0" * 64,
        }
        profile = root / "profile.json"
        profile.write_bytes(canonical(profile_value))
        os.chmod(profile, 0o600)

        return {
            "install": install,
            "old": old,
            "new": new,
            "unit_dir": unit_dir,
            "credential": credential,
            "control": control,
            "operations": operations,
            "transport": transport,
            "updates": updates,
            "profile": profile,
        }

    def identity(self, source: str, payload: str):
        return {
            "schema": "test",
            "source_commit": source,
            "payload_sha256": payload,
            "payload_size": 1,
            "file_count": 1,
        }

    def seed_prepared(self, layout) -> str:
        profile_raw = layout["profile"].read_bytes()
        credential_sha = hashlib.sha256(
            layout["credential"].read_bytes()
        ).hexdigest()
        digest = update._transaction_digest(
            old_source=self.OLD,
            old_payload=self.OLD_PAYLOAD,
            new_source=self.NEW,
            new_payload=self.NEW_PAYLOAD,
            profile_sha=hashlib.sha256(profile_raw).hexdigest(),
            production_target=f"releases/{self.PROD}",
        )
        update_root = layout["updates"]
        update_root.mkdir(mode=0o700)
        os.chmod(update_root, 0o700)
        tx = update_root / digest
        tx.mkdir(mode=0o700)
        os.chmod(tx, 0o700)

        def sha(raw):
            return hashlib.sha256(raw).hexdigest()

        prepared = {
            "schema": update.PREPARED_SCHEMA,
            "transaction_id": digest,
            "old_source_commit": self.OLD,
            "old_payload_sha256": self.OLD_PAYLOAD,
            "new_source_commit": self.NEW,
            "new_payload_sha256": self.NEW_PAYLOAD,
            "production_current_target": f"releases/{self.PROD}",
            "credential_sha256": credential_sha,
            "profile_sha256": sha(profile_raw),
            "old_unit_sha256": {
                name: sha(
                    (
                        layout["old"]
                        / "deploy"
                        / "zero-based-vps"
                        / name
                    ).read_bytes()
                )
                for name in update.PERSISTENT_UNITS
            },
            "new_unit_sha256": {
                name: sha(
                    (
                        layout["new"]
                        / "deploy"
                        / "zero-based-vps"
                        / name
                    ).read_bytes()
                )
                for name in update.PERSISTENT_UNITS
            },
            "worker_unit_sha256": sha(
                (
                    layout["new"]
                    / "deploy"
                    / "zero-based-vps"
                    / update.WORKER_UNIT
                ).read_bytes()
            ),
        }
        prepared_path = tx / "PREPARED.json"
        prepared_path.write_bytes(canonical(prepared))
        os.chmod(prepared_path, 0o600)
        return digest

    def recovery_runtime(self, active):
        enabled = set(update.PERSISTENT_UNITS)
        calls: list[list[str]] = []

        def systemctl(args):
            calls.append(list(args))
            if args[0] == "stop":
                active.discard(args[1])
            elif args[0] == "start":
                active.add(args[1])

        def active_probe(unit):
            return unit in active

        def enabled_probe(unit):
            return "enabled" if unit in enabled else "static"

        return systemctl, active_probe, enabled_probe, calls

    def run_update(self, layout, *, fail_start_agent=False):
        active = set(update.PERSISTENT_UNITS)
        enabled = set(update.PERSISTENT_UNITS)
        calls: list[list[str]] = []
        agent_start_failures_remaining = 1 if fail_start_agent else 0

        def systemctl(args):
            nonlocal agent_start_failures_remaining
            calls.append(list(args))
            if args[0] == "stop":
                active.discard(args[1])
            elif args[0] == "start":
                if (
                    agent_start_failures_remaining
                    and args[1].endswith("agent.service")
                ):
                    agent_start_failures_remaining -= 1
                    raise update.ControlPlaneUpdateError(
                        "injected one-shot successor start failure"
                    )
                active.add(args[1])

        def active_probe(unit):
            return unit in active

        def enabled_probe(unit):
            return "enabled" if unit in enabled else "static"

        with mock.patch.object(
            update,
            "_require_root",
            return_value=None,
        ), mock.patch.object(
            update,
            "verify_release_directory",
            side_effect=[
                self.identity(self.OLD, self.OLD_PAYLOAD),
                self.identity(self.NEW, self.NEW_PAYLOAD),
            ],
        ):
            if fail_start_agent:
                with self.assertRaisesRegex(
                    update.ControlPlaneUpdateError,
                    "rolled back exactly",
                ):
                    update.update_control_plane(
                        install_root=layout["install"],
                        unit_dir=layout["unit_dir"],
                        credential_path=layout["credential"],
                        operation_control_root=layout["control"],
                        operation_root=layout["operations"],
                        transport_root=layout["transport"],
                        update_root=layout["updates"],
                        profile_source=layout["profile"],
                        expected_old_source_commit=self.OLD,
                        expected_old_payload_sha256=self.OLD_PAYLOAD,
                        expected_new_source_commit=self.NEW,
                        expected_new_payload_sha256=self.NEW_PAYLOAD,
                        systemctl=systemctl,
                        active_probe=active_probe,
                        enabled_probe=enabled_probe,
                        restart_probe=lambda unit: 0,
                        sleeper=lambda seconds: None,
                    )
                return calls, active

            result = update.update_control_plane(
                install_root=layout["install"],
                unit_dir=layout["unit_dir"],
                credential_path=layout["credential"],
                operation_control_root=layout["control"],
                operation_root=layout["operations"],
                transport_root=layout["transport"],
                update_root=layout["updates"],
                profile_source=layout["profile"],
                expected_old_source_commit=self.OLD,
                expected_old_payload_sha256=self.OLD_PAYLOAD,
                expected_new_source_commit=self.NEW,
                expected_new_payload_sha256=self.NEW_PAYLOAD,
                systemctl=systemctl,
                active_probe=active_probe,
                enabled_probe=enabled_probe,
                restart_probe=lambda unit: 0,
                sleeper=lambda seconds: None,
            )
        return result, calls, active

    def test_success_updates_only_control_plane_and_preserves_credential(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            credential_before = layout["credential"].read_bytes()

            result, calls, active = self.run_update(layout)

            self.assertEqual(
                result["schema"],
                update.COMPLETED_SCHEMA,
            )
            self.assertEqual(
                os.readlink(layout["install"] / "current"),
                f"releases/{self.PROD}",
            )
            self.assertEqual(
                os.readlink(layout["install"] / "control-current"),
                f"releases/{self.NEW}",
            )
            self.assertEqual(
                layout["credential"].read_bytes(),
                credential_before,
            )
            for name in update.PERSISTENT_UNITS:
                self.assertEqual(
                    (layout["unit_dir"] / name).read_bytes(),
                    (
                        layout["new"]
                        / "deploy"
                        / "zero-based-vps"
                        / name
                    ).read_bytes(),
                )
            self.assertEqual(
                (
                    layout["unit_dir"] / update.WORKER_UNIT
                ).read_bytes(),
                (
                    layout["new"]
                    / "deploy"
                    / "zero-based-vps"
                    / update.WORKER_UNIT
                ).read_bytes(),
            )
            self.assertEqual(
                (
                    layout["control"]
                    / "hub-pre-apply-profile.json"
                ).read_bytes(),
                layout["profile"].read_bytes(),
            )
            self.assertTrue(
                (
                    layout["control"]
                    / "hub-pre-apply-activation.json"
                ).is_file()
            )
            self.assertEqual(active, set(update.PERSISTENT_UNITS))
            self.assertIn(["daemon-reload"], calls)

    def test_activation_failure_rolls_back_exact_predecessor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            credential_before = layout["credential"].read_bytes()

            _, active = self.run_update(
                layout,
                fail_start_agent=True,
            )

            self.assertEqual(
                os.readlink(layout["install"] / "current"),
                f"releases/{self.PROD}",
            )
            self.assertEqual(
                os.readlink(layout["install"] / "control-current"),
                f"releases/{self.OLD}",
            )
            for name in update.PERSISTENT_UNITS:
                self.assertEqual(
                    (layout["unit_dir"] / name).read_bytes(),
                    (
                        layout["old"]
                        / "deploy"
                        / "zero-based-vps"
                        / name
                    ).read_bytes(),
                )
            self.assertFalse(
                (layout["unit_dir"] / update.WORKER_UNIT).exists()
            )
            self.assertFalse(
                (
                    layout["control"]
                    / "hub-pre-apply-profile.json"
                ).exists()
            )
            self.assertEqual(
                layout["credential"].read_bytes(),
                credential_before,
            )
            self.assertEqual(active, set(update.PERSISTENT_UNITS))
            rolled = list(layout["updates"].glob("*/ROLLED_BACK.json"))
            self.assertEqual(len(rolled), 1)

    def test_commit_boundary_rechecks_transport_after_services_stop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            active = set(update.PERSISTENT_UNITS)
            enabled = set(update.PERSISTENT_UNITS)
            stop_count = 0

            def systemctl(args):
                nonlocal stop_count
                if args[0] == "stop":
                    active.discard(args[1])
                    stop_count += 1
                    if stop_count == len(update.PERSISTENT_UNITS):
                        pending = (
                            layout["transport"]
                            / "inbox"
                            / ("1" * 32 + ".json")
                        )
                        pending.write_bytes(b"raced")
                elif args[0] == "start":
                    active.add(args[1])

            with mock.patch.object(
                update,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update,
                "verify_release_directory",
                side_effect=[
                    self.identity(self.OLD, self.OLD_PAYLOAD),
                    self.identity(self.NEW, self.NEW_PAYLOAD),
                ],
            ):
                with self.assertRaisesRegex(
                    update.ControlPlaneUpdateError,
                    "rolled back exactly",
                ):
                    update.update_control_plane(
                        install_root=layout["install"],
                        unit_dir=layout["unit_dir"],
                        credential_path=layout["credential"],
                        operation_control_root=layout["control"],
                        operation_root=layout["operations"],
                        transport_root=layout["transport"],
                        update_root=layout["updates"],
                        profile_source=layout["profile"],
                        expected_old_source_commit=self.OLD,
                        expected_old_payload_sha256=self.OLD_PAYLOAD,
                        expected_new_source_commit=self.NEW,
                        expected_new_payload_sha256=self.NEW_PAYLOAD,
                        systemctl=systemctl,
                        active_probe=lambda unit: unit in active,
                        enabled_probe=lambda unit: (
                            "enabled" if unit in enabled else "static"
                        ),
                        restart_probe=lambda unit: 0,
                        sleeper=lambda seconds: None,
                    )

            self.assertEqual(
                os.readlink(layout["install"] / "control-current"),
                f"releases/{self.OLD}",
            )
            self.assertFalse(
                (layout["unit_dir"] / update.WORKER_UNIT).exists()
            )
            self.assertFalse(
                (
                    layout["control"]
                    / "hub-pre-apply-profile.json"
                ).exists()
            )

    def test_pending_transport_request_blocks_before_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            pending = layout["transport"] / "inbox" / ("1" * 32 + ".json")
            pending.write_bytes(b"pending")

            with mock.patch.object(
                update,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update,
                "verify_release_directory",
                side_effect=[
                    self.identity(self.OLD, self.OLD_PAYLOAD),
                    self.identity(self.NEW, self.NEW_PAYLOAD),
                ],
            ):
                with self.assertRaisesRegex(
                    update.ControlPlaneUpdateError,
                    "pending transport requests",
                ):
                    update.update_control_plane(
                        install_root=layout["install"],
                        unit_dir=layout["unit_dir"],
                        credential_path=layout["credential"],
                        operation_control_root=layout["control"],
                        operation_root=layout["operations"],
                        transport_root=layout["transport"],
                        update_root=layout["updates"],
                        profile_source=layout["profile"],
                        expected_old_source_commit=self.OLD,
                        expected_old_payload_sha256=self.OLD_PAYLOAD,
                        expected_new_source_commit=self.NEW,
                        expected_new_payload_sha256=self.NEW_PAYLOAD,
                        active_probe=lambda unit: True,
                        enabled_probe=lambda unit: "enabled",
                        restart_probe=lambda unit: 0,
                    )

            self.assertFalse(layout["updates"].exists())
            self.assertEqual(
                os.readlink(layout["install"] / "control-current"),
                f"releases/{self.OLD}",
            )

    def test_prepared_old_exact_resumes_with_services_already_stopped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            digest = self.seed_prepared(layout)
            active = set()
            systemctl, active_probe, enabled_probe, _ = self.recovery_runtime(active)

            with mock.patch.object(
                update,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update,
                "verify_release_directory",
                side_effect=[
                    self.identity(self.OLD, self.OLD_PAYLOAD),
                    self.identity(self.NEW, self.NEW_PAYLOAD),
                ],
            ):
                result = update.update_control_plane(
                    install_root=layout["install"],
                    unit_dir=layout["unit_dir"],
                    credential_path=layout["credential"],
                    operation_control_root=layout["control"],
                    operation_root=layout["operations"],
                    transport_root=layout["transport"],
                    update_root=layout["updates"],
                    profile_source=layout["profile"],
                    expected_old_source_commit=self.OLD,
                    expected_old_payload_sha256=self.OLD_PAYLOAD,
                    expected_new_source_commit=self.NEW,
                    expected_new_payload_sha256=self.NEW_PAYLOAD,
                    systemctl=systemctl,
                    active_probe=active_probe,
                    enabled_probe=enabled_probe,
                    restart_probe=lambda unit: 0,
                    sleeper=lambda seconds: None,
                )

            self.assertEqual(result["schema"], update.COMPLETED_SCHEMA)
            self.assertEqual(
                os.readlink(layout["install"] / "control-current"),
                f"releases/{self.NEW}",
            )
            self.assertTrue(
                (layout["updates"] / digest / "COMPLETED.json").is_file()
            )
            self.assertTrue(
                (
                    layout["control"]
                    / "hub-pre-apply-activation.json"
                ).is_file()
            )
            self.assertEqual(active, set(update.PERSISTENT_UNITS))

    def test_prepared_new_exact_terminalizes_without_republishing_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            digest = self.seed_prepared(layout)

            profile_destination = (
                layout["control"] / "hub-pre-apply-profile.json"
            )
            profile_destination.write_bytes(layout["profile"].read_bytes())
            os.chmod(profile_destination, 0o600)

            worker = layout["unit_dir"] / update.WORKER_UNIT
            worker.write_bytes(
                (
                    layout["new"]
                    / "deploy"
                    / "zero-based-vps"
                    / update.WORKER_UNIT
                ).read_bytes()
            )
            os.chmod(worker, 0o644)

            for name in update.PERSISTENT_UNITS:
                target = layout["unit_dir"] / name
                target.write_bytes(
                    (
                        layout["new"]
                        / "deploy"
                        / "zero-based-vps"
                        / name
                    ).read_bytes()
                )
                os.chmod(target, 0o644)

            current = layout["install"] / "control-current"
            current.unlink()
            os.symlink(f"releases/{self.NEW}", current)

            active = set()
            systemctl, active_probe, enabled_probe, _ = self.recovery_runtime(active)

            with mock.patch.object(
                update,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update,
                "verify_release_directory",
                side_effect=[
                    self.identity(self.OLD, self.OLD_PAYLOAD),
                    self.identity(self.NEW, self.NEW_PAYLOAD),
                ],
            ), mock.patch.object(
                update,
                "_atomic_file",
                side_effect=AssertionError(
                    "NEW_EXACT recovery must not republish unit bytes"
                ),
            ), mock.patch.object(
                update,
                "_atomic_symlink",
                side_effect=AssertionError(
                    "NEW_EXACT recovery must not republish selector"
                ),
            ):
                result = update.update_control_plane(
                    install_root=layout["install"],
                    unit_dir=layout["unit_dir"],
                    credential_path=layout["credential"],
                    operation_control_root=layout["control"],
                    operation_root=layout["operations"],
                    transport_root=layout["transport"],
                    update_root=layout["updates"],
                    profile_source=layout["profile"],
                    expected_old_source_commit=self.OLD,
                    expected_old_payload_sha256=self.OLD_PAYLOAD,
                    expected_new_source_commit=self.NEW,
                    expected_new_payload_sha256=self.NEW_PAYLOAD,
                    systemctl=systemctl,
                    active_probe=active_probe,
                    enabled_probe=enabled_probe,
                    restart_probe=lambda unit: 0,
                    sleeper=lambda seconds: None,
                )

            self.assertEqual(result["schema"], update.COMPLETED_SCHEMA)
            self.assertTrue(
                (layout["updates"] / digest / "COMPLETED.json").is_file()
            )
            self.assertTrue(
                (
                    layout["control"]
                    / "hub-pre-apply-activation.json"
                ).is_file()
            )
            self.assertEqual(active, set(update.PERSISTENT_UNITS))

    def test_prepared_mixed_boundary_never_overwrites_unknown_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            digest = self.seed_prepared(layout)
            victim = layout["unit_dir"] / update.PERSISTENT_UNITS[0]
            victim.write_bytes(b"unknown-foreign-bytes\n")
            os.chmod(victim, 0o644)
            before = victim.read_bytes()

            with mock.patch.object(
                update,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update,
                "verify_release_directory",
                side_effect=[
                    self.identity(self.OLD, self.OLD_PAYLOAD),
                    self.identity(self.NEW, self.NEW_PAYLOAD),
                ],
            ):
                with self.assertRaisesRegex(
                    update.ControlPlaneUpdateError,
                    "partial; read-only reconciliation required",
                ):
                    update.update_control_plane(
                        install_root=layout["install"],
                        unit_dir=layout["unit_dir"],
                        credential_path=layout["credential"],
                        operation_control_root=layout["control"],
                        operation_root=layout["operations"],
                        transport_root=layout["transport"],
                        update_root=layout["updates"],
                        profile_source=layout["profile"],
                        expected_old_source_commit=self.OLD,
                        expected_old_payload_sha256=self.OLD_PAYLOAD,
                        expected_new_source_commit=self.NEW,
                        expected_new_payload_sha256=self.NEW_PAYLOAD,
                        systemctl=lambda args: (_ for _ in ()).throw(
                            AssertionError(
                                "mixed boundary must not invoke systemctl"
                            )
                        ),
                        active_probe=lambda unit: False,
                        enabled_probe=lambda unit: "enabled",
                        restart_probe=lambda unit: 0,
                        sleeper=lambda seconds: None,
                    )

            self.assertEqual(victim.read_bytes(), before)
            self.assertFalse(
                (layout["updates"] / digest / "COMPLETED.json").exists()
            )
            self.assertFalse(
                (layout["updates"] / digest / "ROLLED_BACK.json").exists()
            )
            self.assertFalse(
                (
                    layout["control"]
                    / "hub-pre-apply-activation.json"
                ).exists()
            )

    def test_profile_must_bind_successor_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = self.layout(root)
            value = json.loads(layout["profile"].read_text())
            value["control_source_commit"] = "f" * 40
            layout["profile"].write_bytes(canonical(value))

            with mock.patch.object(
                update,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update,
                "verify_release_directory",
                side_effect=[
                    self.identity(self.OLD, self.OLD_PAYLOAD),
                    self.identity(self.NEW, self.NEW_PAYLOAD),
                ],
            ):
                with self.assertRaisesRegex(
                    update.ControlPlaneUpdateError,
                    "not bound to successor",
                ):
                    update.update_control_plane(
                        install_root=layout["install"],
                        unit_dir=layout["unit_dir"],
                        credential_path=layout["credential"],
                        operation_control_root=layout["control"],
                        operation_root=layout["operations"],
                        transport_root=layout["transport"],
                        update_root=layout["updates"],
                        profile_source=layout["profile"],
                        expected_old_source_commit=self.OLD,
                        expected_old_payload_sha256=self.OLD_PAYLOAD,
                        expected_new_source_commit=self.NEW,
                        expected_new_payload_sha256=self.NEW_PAYLOAD,
                        active_probe=lambda unit: True,
                        enabled_probe=lambda unit: "enabled",
                        restart_probe=lambda unit: 0,
                    )

            self.assertFalse(layout["updates"].exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
