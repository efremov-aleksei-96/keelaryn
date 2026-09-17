from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "zero-based-vps"
sys.path.insert(0, str(DEPLOY))

import target_host_validate as targetmod  # noqa: E402


class ZeroBasedVpsTargetHostValidationTests(unittest.TestCase):
    def _selector(self, root: Path, raw: bytes) -> Path:
        parent = root / "etc" / "keelaryn"
        parent.mkdir(parents=True, mode=0o700)
        os.chmod(parent, 0o700)
        selector = parent / "hub.env"
        selector.write_bytes(raw)
        os.chmod(selector, 0o600)
        return selector

    def test_selector_accepts_only_exact_canonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            selector = self._selector(
                root,
                b"KEELARYN_HUB_ROOT_ID=abcDEF0123_-valid\n",
            )
            targetmod.validate_selector_file(selector)

    def test_selector_rejects_quoted_value_even_when_inner_id_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            selector = self._selector(
                Path(td),
                b'KEELARYN_HUB_ROOT_ID="abcDEF0123_-valid"\n',
            )
            with self.assertRaises(targetmod.TargetHostValidationError):
                targetmod.validate_selector_file(selector)

    def test_selector_rejects_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            selector = self._selector(
                Path(td),
                b"KEELARYN_HUB_ROOT_ID=abcDEF0123_-valid\r\n",
            )
            with self.assertRaises(targetmod.TargetHostValidationError):
                targetmod.validate_selector_file(selector)

    def test_installed_units_must_match_qualified_release_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            unit_dir = Path(td) / "systemd"
            unit_dir.mkdir(mode=0o755)
            os.chmod(unit_dir, 0o755)
            for name in targetmod.UNIT_NAMES:
                target = unit_dir / name
                shutil.copyfile(DEPLOY / name, target)
                os.chmod(target, 0o644)
            targetmod.validate_installed_units(REPO, unit_dir)

            changed = unit_dir / targetmod.UNIT_NAMES[0]
            changed.write_bytes(changed.read_bytes() + b"\n")
            os.chmod(changed, 0o644)
            with self.assertRaises(targetmod.TargetHostValidationError):
                targetmod.validate_installed_units(REPO, unit_dir)

    def test_deployment_contract_uses_target_validator_not_full_development_suite(self) -> None:
        raw = (DEPLOY / "README.md").read_text(encoding="utf-8")
        self.assertIn("target_host_validate.py", raw)
        self.assertNotIn("unittest discover -s tests/core", raw)
        self.assertIn("must not run the full `tests/core` development suite", raw)

    def test_payload_ci_executes_materialized_target_host_validator(self) -> None:
        raw = (
            REPO / ".github" / "workflows" / "zero-based-core-validation.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("target_host_validate.py", raw)
        self.assertIn('"target_host_validator_verified": True', raw)
        self.assertIn('"development_test_suite_executed"', raw)

    def test_target_validator_source_never_invokes_unittest_discovery(self) -> None:
        raw = (DEPLOY / "target_host_validate.py").read_text(encoding="utf-8")
        self.assertNotIn("unittest", raw)
        self.assertNotIn("tests/core", raw)
        self.assertIn("PYTHONDONTWRITEBYTECODE", raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
