from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "zero-based-vps"
SPEC = importlib.util.spec_from_file_location(
    "operation_control_d0_update",
    DEPLOY / "operation_control_d0_update.py",
)
assert SPEC is not None and SPEC.loader is not None
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


class D0ControlUpdateTests(unittest.TestCase):
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
            (release / "deploy" / "zero-based-vps").mkdir(
                parents=True
            )
            (
                release
                / "core"
                / "keelaryn_core"
            ).mkdir(
                parents=True
            )
        for name in update.PERSISTENT_UNITS:
            (
                old
                / "deploy"
                / "zero-based-vps"
                / name
            ).write_bytes(
                f"old:{name}\n".encode()
            )
            (
                new
                / "deploy"
                / "zero-based-vps"
                / name
            ).write_bytes(
                f"new:{name}\n".encode()
            )

        (
            new
            / "deploy"
            / "zero-based-vps"
            / update.STATIC_UNIT
        ).write_bytes(
            (
                "[Unit]\n"
                "Description=test\n"
                "[Service]\n"
                "User=root\n"
                "Group=root\n"
                "PrivateNetwork=true\n"
                "CapabilityBoundingSet=\n"
                "AmbientCapabilities=\n"
                "RestrictAddressFamilies=AF_UNIX\n"
                "ReadWritePaths=/var/lib/keelaryn/operations/%i\n"
                "InaccessiblePaths=/etc/keelaryn/drive.env "
                "/etc/keelaryn/operation-control "
                "/var/lib/keelaryn/migration "
                "/var/lib/keelaryn-operation-transport\n"
                "ExecStart=/usr/bin/python3 -B -m "
                "keelaryn_core.production_snapshot "
                "--operation-id %i "
                "--output /var/lib/keelaryn/operations/%i/"
                "production-snapshot.json\n"
            ).encode()
        )
        (
            new
            / "core"
            / "keelaryn_core"
            / "operation_agent.py"
        ).write_text(
            """
from dataclasses import dataclass

@dataclass(frozen=True)
class OperationHandler:
    mutation_capable: bool
    requires_approval: bool
    callback: object

def _runtime_selftest(): pass
def _production_snapshot(): pass

HANDLERS: dict[str, OperationHandler] = {
    "RUNTIME_SELFTEST": OperationHandler(
        mutation_capable=False,
        requires_approval=False,
        callback=_runtime_selftest,
    ),
    "PRODUCTION_SNAPSHOT": OperationHandler(
        mutation_capable=False,
        requires_approval=False,
        callback=_production_snapshot,
    ),
}
""".lstrip(),
            encoding="utf-8",
        )

        os.symlink(
            f"releases/{self.PROD}",
            install / "current",
        )
        os.symlink(
            f"releases/{self.OLD}",
            install / "control-current",
        )

        unit_dir = root / "systemd"
        unit_dir.mkdir()
        for name in update.PERSISTENT_UNITS:
            target = unit_dir / name
            target.write_bytes(
                (
                    old
                    / "deploy"
                    / "zero-based-vps"
                    / name
                ).read_bytes()
            )
            os.chmod(
                target,
                0o644,
            )

        config = (
            root
            / "etc"
            / "keelaryn"
            / "operation-control"
        )
        config.mkdir(
            parents=True,
            mode=0o700,
        )
        os.chmod(
            config,
            0o700,
        )
        credential = (
            config
            / "github-operations.env"
        )
        credential.write_bytes(
            b"TOKEN=private\n"
        )
        os.chmod(
            credential,
            0o600,
        )

        operations = (
            root
            / "var"
            / "operations"
        )
        operations.mkdir(
            parents=True,
            mode=0o700,
        )
        os.chmod(
            operations,
            0o700,
        )

        transport = (
            root
            / "var"
            / "transport"
        )
        (
            transport
            / "inbox"
        ).mkdir(
            parents=True,
            mode=0o770,
        )
        (
            transport
            / "outbox"
        ).mkdir(
            mode=0o770,
        )
        os.chmod(
            transport,
            0o750,
        )

        return {
            "install": install,
            "old": old,
            "new": new,
            "unit_dir": unit_dir,
            "credential": credential,
            "operations": operations,
            "transport": transport,
            "updates": (
                root
                / "var"
                / "d0-updates"
            ),
        }

    def identity(
        self,
        source: str,
        payload: str,
    ):
        return {
            "schema": "test",
            "source_commit": source,
            "payload_sha256": payload,
            "payload_size": 1,
            "file_count": 1,
        }

    def runtime(
        self,
        *,
        fail_start_agent: bool = False,
    ):
        active = set(
            update.PERSISTENT_UNITS
        )
        enabled = set(
            update.PERSISTENT_UNITS
        )
        calls: list[list[str]] = []
        remaining = (
            1
            if fail_start_agent
            else 0
        )

        def systemctl(args):
            nonlocal remaining
            calls.append(
                list(args)
            )
            if args[0] == "stop":
                active.discard(
                    args[1]
                )
            elif args[0] == "start":
                if (
                    remaining
                    and args[1].endswith(
                        "agent.service"
                    )
                ):
                    remaining -= 1
                    raise update.D0ControlUpdateError(
                        "injected start failure"
                    )
                active.add(
                    args[1]
                )

        def active_probe(unit):
            return unit in active

        def enabled_probe(unit):
            return (
                "enabled"
                if unit in enabled
                else "static"
            )

        return (
            systemctl,
            active_probe,
            enabled_probe,
            active,
            calls,
        )

    def invoke(
        self,
        layout,
        *,
        fail_start_agent: bool = False,
    ):
        (
            systemctl,
            active_probe,
            enabled_probe,
            active,
            calls,
        ) = self.runtime(
            fail_start_agent=fail_start_agent
        )
        kwargs = {
            "install_root": layout["install"],
            "unit_dir": layout["unit_dir"],
            "credential_path": layout["credential"],
            "operation_root": layout["operations"],
            "transport_root": layout["transport"],
            "update_root": layout["updates"],
            "expected_old_source_commit": self.OLD,
            "expected_old_payload_sha256": self.OLD_PAYLOAD,
            "expected_new_source_commit": self.NEW,
            "expected_new_payload_sha256": self.NEW_PAYLOAD,
            "systemctl": systemctl,
            "active_probe": active_probe,
            "template_active_probe": lambda unit: False,
            "enabled_probe": enabled_probe,
            "restart_probe": lambda unit: 0,
            "sleeper": lambda seconds: None,
        }
        with mock.patch.object(
            update.legacy,
            "_require_root",
            return_value=None,
        ), mock.patch.object(
            update.legacy,
            "verify_release_directory",
            side_effect=[
                self.identity(
                    self.OLD,
                    self.OLD_PAYLOAD,
                ),
                self.identity(
                    self.NEW,
                    self.NEW_PAYLOAD,
                ),
            ],
        ):
            if fail_start_agent:
                with self.assertRaisesRegex(
                    update.D0ControlUpdateError,
                    "rolled back exactly",
                ):
                    update.update_d0_control_plane(
                        **kwargs
                    )
                return (
                    None,
                    active,
                    calls,
                )
            result = (
                update.update_d0_control_plane(
                    **kwargs
                )
            )
            return (
                result,
                active,
                calls,
            )


    def test_template_probe_accepts_no_active_instances(self):
        completed = mock.Mock(
            returncode=0,
            stdout="",
            stderr="",
        )
        with mock.patch.object(
            update.legacy,
            "_systemctl",
            return_value=completed,
        ) as systemctl:
            self.assertFalse(
                update._template_has_active_instances(
                    update.STATIC_UNIT
                )
            )
        systemctl.assert_called_once_with(
            [
                "list-units",
                "--type=service",
                "--state=active",
                "--no-legend",
                "--plain",
                update.STATIC_INSTANCE_PATTERN,
            ]
        )

    def test_template_probe_detects_active_instance(self):
        completed = mock.Mock(
            returncode=0,
            stdout=(
                "keelaryn-production-snapshot@abc.service "
                "loaded active running test\n"
            ),
            stderr="",
        )
        with mock.patch.object(
            update.legacy,
            "_systemctl",
            return_value=completed,
        ):
            self.assertTrue(
                update._template_has_active_instances(
                    update.STATIC_UNIT
                )
            )

    def test_template_probe_fails_closed_on_systemctl_error(self):
        completed = mock.Mock(
            returncode=1,
            stdout="",
            stderr=(
                "Failed to retrieve unit state: Unit name "
                "keelaryn-production-snapshot@.service is neither "
                "a valid invocation ID nor unit name.\n"
            ),
        )
        with mock.patch.object(
            update.legacy,
            "_systemctl",
            return_value=completed,
        ):
            with self.assertRaisesRegex(
                update.D0ControlUpdateError,
                "template-instance probe failed",
            ):
                update._template_has_active_instances(
                    update.STATIC_UNIT
                )

    def test_verify_services_never_uses_generic_probe_for_bare_template(self):
        def active_probe(unit):
            if unit == update.STATIC_UNIT:
                raise update.D0ControlUpdateError(
                    "systemctl active-state probe failed"
                )
            return True

        observed = update._verify_services(
            active_probe=active_probe,
            template_active_probe=lambda unit: False,
            enabled_probe=lambda unit: (
                "static"
                if unit == update.STATIC_UNIT
                else "enabled"
            ),
            restart_probe=lambda unit: 0,
        )
        self.assertEqual(
            set(observed),
            set(update.PERSISTENT_UNITS),
        )

    def test_verify_services_blocks_active_template_instance(self):
        with self.assertRaisesRegex(
            update.D0ControlUpdateError,
            "template must be inactive",
        ):
            update._verify_services(
                active_probe=lambda unit: True,
                template_active_probe=lambda unit: True,
                enabled_probe=lambda unit: (
                    "static"
                    if unit == update.STATIC_UNIT
                    else "enabled"
                ),
                restart_probe=lambda unit: 0,
            )

    def test_success_installs_read_only_d0_boundary(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            layout = self.layout(
                Path(td)
            )
            credential_before = (
                layout["credential"]
                .read_bytes()
            )
            (
                result,
                active,
                calls,
            ) = self.invoke(
                layout
            )

            self.assertEqual(
                result["schema"],
                update.COMPLETED_SCHEMA,
            )
            self.assertEqual(
                result[
                    "remote_mutation_handlers"
                ],
                "ABSENT",
            )
            self.assertEqual(
                result["static_unit"],
                "STATIC_INACTIVE",
            )
            self.assertEqual(
                os.readlink(
                    layout["install"]
                    / "current"
                ),
                f"releases/{self.PROD}",
            )
            self.assertEqual(
                os.readlink(
                    layout["install"]
                    / "control-current"
                ),
                f"releases/{self.NEW}",
            )
            self.assertEqual(
                layout["credential"]
                .read_bytes(),
                credential_before,
            )
            self.assertEqual(
                active,
                set(
                    update.PERSISTENT_UNITS
                ),
            )
            self.assertIn(
                ["daemon-reload"],
                calls,
            )
            prepared = next(
                layout["updates"].glob(
                    "*/PREPARED.json"
                )
            )
            raw = prepared.read_text(
                encoding="utf-8"
            )
            self.assertIn(
                '"remote_mutation_handlers":0',
                raw,
            )
            self.assertNotIn(
                "HUB_PRE_APPLY",
                raw,
            )

    def test_start_failure_rolls_back_exact_predecessor(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            layout = self.layout(
                Path(td)
            )
            (
                _,
                active,
                _,
            ) = self.invoke(
                layout,
                fail_start_agent=True,
            )
            self.assertEqual(
                os.readlink(
                    layout["install"]
                    / "control-current"
                ),
                f"releases/{self.OLD}",
            )
            self.assertFalse(
                (
                    layout["unit_dir"]
                    / update.STATIC_UNIT
                ).exists()
            )
            self.assertEqual(
                active,
                set(
                    update.PERSISTENT_UNITS
                ),
            )
            self.assertEqual(
                len(
                    list(
                        layout["updates"].glob(
                            "*/ROLLED_BACK.json"
                        )
                    )
                ),
                1,
            )

    def test_mutation_handler_blocks_before_transaction(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            layout = self.layout(
                Path(td)
            )
            path = (
                layout["new"]
                / "core"
                / "keelaryn_core"
                / "operation_agent.py"
            )
            path.write_text(
                path.read_text(
                    encoding="utf-8"
                ).replace(
                    '"PRODUCTION_SNAPSHOT": '
                    "OperationHandler(",
                    '"HUB_PRE_APPLY": '
                    "OperationHandler(",
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                update.legacy,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update.legacy,
                "verify_release_directory",
                side_effect=[
                    self.identity(
                        self.OLD,
                        self.OLD_PAYLOAD,
                    ),
                    self.identity(
                        self.NEW,
                        self.NEW_PAYLOAD,
                    ),
                ],
            ):
                with self.assertRaisesRegex(
                    update.D0ControlUpdateError,
                    "allowlist is not exact",
                ):
                    update.update_d0_control_plane(
                        install_root=layout[
                            "install"
                        ],
                        unit_dir=layout[
                            "unit_dir"
                        ],
                        credential_path=layout[
                            "credential"
                        ],
                        operation_root=layout[
                            "operations"
                        ],
                        transport_root=layout[
                            "transport"
                        ],
                        update_root=layout[
                            "updates"
                        ],
                        expected_old_source_commit=(
                            self.OLD
                        ),
                        expected_old_payload_sha256=(
                            self.OLD_PAYLOAD
                        ),
                        expected_new_source_commit=(
                            self.NEW
                        ),
                        expected_new_payload_sha256=(
                            self.NEW_PAYLOAD
                        ),
                    )
            self.assertFalse(
                layout["updates"].exists()
            )

    def test_worker_policy_blocks_before_transaction(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            layout = self.layout(
                Path(td)
            )
            path = (
                layout["new"]
                / "deploy"
                / "zero-based-vps"
                / update.STATIC_UNIT
            )
            path.write_text(
                path.read_text(
                    encoding="utf-8"
                ).replace(
                    "PrivateNetwork=true\n",
                    "",
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                update.legacy,
                "_require_root",
                return_value=None,
            ), mock.patch.object(
                update.legacy,
                "verify_release_directory",
                side_effect=[
                    self.identity(
                        self.OLD,
                        self.OLD_PAYLOAD,
                    ),
                    self.identity(
                        self.NEW,
                        self.NEW_PAYLOAD,
                    ),
                ],
            ):
                with self.assertRaisesRegex(
                    update.D0ControlUpdateError,
                    "hardening is incomplete",
                ):
                    update.update_d0_control_plane(
                        install_root=layout[
                            "install"
                        ],
                        unit_dir=layout[
                            "unit_dir"
                        ],
                        credential_path=layout[
                            "credential"
                        ],
                        operation_root=layout[
                            "operations"
                        ],
                        transport_root=layout[
                            "transport"
                        ],
                        update_root=layout[
                            "updates"
                        ],
                        expected_old_source_commit=(
                            self.OLD
                        ),
                        expected_old_payload_sha256=(
                            self.OLD_PAYLOAD
                        ),
                        expected_new_source_commit=(
                            self.NEW
                        ),
                        expected_new_payload_sha256=(
                            self.NEW_PAYLOAD
                        ),
                    )
            self.assertFalse(
                layout["updates"].exists()
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
