from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.operation_agent import OperationAgent  # noqa: E402
from keelaryn_core.operation_request import (  # noqa: E402
    REQUEST_SCHEMA,
    parse_operation_request,
)
from keelaryn_core.operation_runtime import OperationRuntimeError  # noqa: E402


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


class OperationAgentTests(unittest.TestCase):
    COMMIT = "a" * 40
    REQUEST_ID = "1" * 32

    def request(self, **updates: object) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": REQUEST_SCHEMA,
            "request_id": self.REQUEST_ID,
            "operation": "RUNTIME_SELFTEST",
            "source_commit": self.COMMIT,
            "profile": "DEFAULT",
            "mutation_capable": False,
            "timeout_seconds": 60,
            "approval": "NOT_REQUIRED",
        }
        value.update(updates)
        return value

    def layout(self, root: Path):
        operation_root = root / "operations"
        control_root = root / "control"
        operation_root.mkdir(mode=0o700)
        control_root.mkdir(mode=0o700)
        os.chmod(operation_root, 0o700)
        os.chmod(control_root, 0o700)
        agent = OperationAgent(
            operation_root,
            control_root,
            source_commit=self.COMMIT,
        )
        return agent, operation_root, control_root

    def test_request_is_strict_canonical_and_contains_no_command_surface(self) -> None:
        request = self.request()
        parsed = parse_operation_request(canonical(request))
        self.assertEqual(parsed.operation, "RUNTIME_SELFTEST")
        self.assertFalse(parsed.mutation_capable)

        with self.assertRaises(OperationRuntimeError):
            parse_operation_request(
                json.dumps(request, indent=2).encode("utf-8")
            )

        bad = dict(request)
        bad["command"] = "rm -rf /"
        with self.assertRaises(OperationRuntimeError):
            parse_operation_request(canonical(bad))

    def test_allowlisted_selftest_executes_once_and_replay_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, operation_root, _ = self.layout(root)
            request_path = agent.inbox / f"{self.REQUEST_ID}.json"
            request_path.write_bytes(canonical(self.request()))
            os.chmod(request_path, 0o600)

            first = agent.process(request_path)
            self.assertEqual(first["disposition"], "COMPLETED")
            self.assertEqual(first["status"]["observed_state"], "SUCCEEDED")

            result_before = (
                operation_root / self.REQUEST_ID / "result.json"
            ).read_bytes()
            second = agent.process(request_path)
            result_after = (
                operation_root / self.REQUEST_ID / "result.json"
            ).read_bytes()

            self.assertEqual(second["disposition"], "EXISTING")
            self.assertEqual(result_before, result_after)

    def test_unknown_or_source_mismatched_request_fails_before_operation_creation(self) -> None:
        for updates in (
            {"operation": "ARBITRARY_SHELL"},
            {"source_commit": "b" * 40},
            {"mutation_capable": True},
            {"approval": "REQUIRED"},
        ):
            with self.subTest(updates=updates):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    os.chmod(root, 0o700)
                    agent, operation_root, _ = self.layout(root)
                    path = agent.inbox / f"{self.REQUEST_ID}.json"
                    path.write_bytes(canonical(self.request(**updates)))
                    os.chmod(path, 0o600)

                    with self.assertRaises(OperationRuntimeError):
                        agent.process(path)

                    self.assertFalse(
                        (operation_root / self.REQUEST_ID).exists()
                    )

    def test_request_filename_must_bind_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, _, _ = self.layout(root)
            path = agent.inbox / f"{'2' * 32}.json"
            path.write_bytes(canonical(self.request()))
            os.chmod(path, 0o600)

            with self.assertRaises(OperationRuntimeError):
                agent.process(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
