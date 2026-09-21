from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE = (
    ROOT
    / "deploy"
    / "zero-based-vps"
    / "operation_control_d0_validate.py"
)
SPEC = importlib.util.spec_from_file_location(
    "operation_control_d0_validate",
    MODULE,
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(
    SPEC
)
SPEC.loader.exec_module(
    validator
)


class D0ControlValidatorTests(
    unittest.TestCase
):
    IDENTITY = {
        "schema": "test",
        "source_commit": "a" * 40,
        "payload_sha256": "b" * 64,
        "payload_size": 1,
        "file_count": 1,
    }

    def test_repository_release_exposes_exact_read_only_contract(
        self,
    ) -> None:
        with mock.patch.object(
            validator,
            "verify_release_directory",
            return_value=self.IDENTITY,
        ):
            value = (
                validator
                .validate_d0_control_release(
                    ROOT,
                    expected_source_commit=(
                        "a" * 40
                    ),
                    expected_payload_sha256=(
                        "b" * 64
                    ),
                )
            )

        self.assertEqual(
            value["remote_allowlist"],
            [
                "PRODUCTION_SNAPSHOT",
                "RUNTIME_SELFTEST",
            ],
        )
        self.assertEqual(
            value["remote_mutation_handlers"],
            0,
        )
        self.assertTrue(
            value[
                "snapshot_unit_policy_verified"
            ]
        )
        self.assertFalse(
            value[
                "installed_units_verified"
            ]
        )

    def test_installed_units_must_match_release_exactly(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            unit_dir = Path(td)
            os.chmod(
                unit_dir,
                0o755,
            )
            for name in (
                *validator.update.PERSISTENT_UNITS,
                validator.update.STATIC_UNIT,
            ):
                source = (
                    ROOT
                    / "deploy"
                    / "zero-based-vps"
                    / name
                )
                target = (
                    unit_dir
                    / name
                )
                target.write_bytes(
                    source.read_bytes()
                )
                os.chmod(
                    target,
                    0o644,
                )

            with mock.patch.object(
                validator,
                "verify_release_directory",
                return_value=self.IDENTITY,
            ):
                value = (
                    validator
                    .validate_d0_control_release(
                        ROOT,
                        expected_source_commit=(
                            "a" * 40
                        ),
                        expected_payload_sha256=(
                            "b" * 64
                        ),
                        installed_unit_dir=(
                            unit_dir
                        ),
                    )
                )
                self.assertTrue(
                    value[
                        "installed_units_verified"
                    ]
                )

                (
                    unit_dir
                    / validator.update.STATIC_UNIT
                ).write_bytes(
                    b"tampered\n"
                )
                with self.assertRaisesRegex(
                    validator
                    .D0ControlValidationError,
                    "bytes mismatch",
                ):
                    (
                        validator
                        .validate_d0_control_release(
                            ROOT,
                            expected_source_commit=(
                                "a" * 40
                            ),
                            expected_payload_sha256=(
                                "b" * 64
                            ),
                            installed_unit_dir=(
                                unit_dir
                            ),
                        )
                    )


if __name__ == "__main__":
    unittest.main(
        verbosity=2
    )
