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
from keelaryn_core.operation_request import REQUEST_SCHEMA, parse_operation_request  # noqa: E402
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
        transport_root = root / "transport"
        operation_root.mkdir(mode=0o700)
        control_root.mkdir(mode=0o700)
        transport_root.mkdir(mode=0o750)
        for path in (operation_root, control_root, transport_root):
            os.chmod(path, 0o700)
        for name in ("inbox", "outbox"):
            path = transport_root / name
            path.mkdir(mode=0o770)
            os.chmod(path, 0o2770)
        agent = OperationAgent(
            operation_root,
            control_root,
            transport_root,
            source_commit=self.COMMIT,
        )
        return agent, operation_root, control_root

    def test_agent_stays_idle_until_transport_relay_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            operation_root = root / "operations"
            control_root = root / "control"
            transport_root = root / "transport"
            operation_root.mkdir(mode=0o700)
            control_root.mkdir(mode=0o700)
            os.chmod(operation_root, 0o700)
            os.chmod(control_root, 0o700)

            agent = OperationAgent(
                operation_root,
                control_root,
                transport_root,
                source_commit=self.COMMIT,
            )
            self.assertIsNone(agent.process_pending_once())

            transport_root.mkdir(mode=0o750)
            os.chmod(transport_root, 0o750)
            for name in ("inbox", "outbox"):
                path = transport_root / name
                path.mkdir(mode=0o700)
                os.chmod(path, 0o700)

            request_path = agent.inbox / f"{self.REQUEST_ID}.json"
            request_path.write_bytes(canonical(self.request()))
            os.chmod(request_path, 0o660)
            result = agent.process_pending_once()

            self.assertEqual(result["disposition"], "COMPLETED")
            self.assertEqual(result["status"]["observed_state"], "SUCCEEDED")

    def test_malformed_transport_relay_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            operation_root = root / "operations"
            control_root = root / "control"
            transport_root = root / "transport"
            operation_root.mkdir(mode=0o700)
            control_root.mkdir(mode=0o700)
            transport_root.mkdir(mode=0o755)
            os.chmod(operation_root, 0o700)
            os.chmod(control_root, 0o700)
            os.chmod(transport_root, 0o755)

            agent = OperationAgent(
                operation_root,
                control_root,
                transport_root,
                source_commit=self.COMMIT,
            )
            with self.assertRaisesRegex(
                OperationRuntimeError,
                "operation transport root group/mode is not exact 0750",
            ):
                agent.process_pending_once()

    def test_request_is_strict_canonical_and_contains_no_command_surface(self) -> None:
        request = self.request()
        parsed = parse_operation_request(canonical(request))
        self.assertEqual(parsed.operation, "RUNTIME_SELFTEST")
        self.assertFalse(parsed.mutation_capable)

        with self.assertRaises(OperationRuntimeError):
            parse_operation_request(json.dumps(request, indent=2).encode("utf-8"))

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
            os.chmod(request_path, 0o660)

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

    def test_pending_request_is_archived_and_not_repeated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, _, control = self.layout(root)
            request_path = agent.inbox / f"{self.REQUEST_ID}.json"
            request_path.write_bytes(canonical(self.request()))
            os.chmod(request_path, 0o660)

            first = agent.process_pending_once()
            second = agent.process_pending_once()

            self.assertEqual(first["disposition"], "COMPLETED")
            self.assertIsNone(second)
            self.assertFalse(request_path.exists())
            self.assertTrue(
                (control / "processed" / f"{self.REQUEST_ID}.json").exists()
            )

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

                    self.assertFalse((operation_root / self.REQUEST_ID).exists())

    def test_restart_reclaims_prestate_initialization_orphan_and_executes_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, operation_root, _ = self.layout(root)
            request_path = agent.inbox / f"{self.REQUEST_ID}.json"
            raw = canonical(self.request())
            request_path.write_bytes(raw)
            os.chmod(request_path, 0o660)

            orphan = operation_root / self.REQUEST_ID
            orphan.mkdir(mode=0o700)
            staging = orphan / (".state.json.new-999-" + ("a" * 32))
            staging.write_bytes(b"partial")
            os.chmod(staging, 0o600)

            result = agent.process_pending_once()

            self.assertEqual(result["disposition"], "COMPLETED")
            self.assertEqual(result["status"]["execution_state"], "SUCCEEDED")
            self.assertTrue(
                (operation_root / self.REQUEST_ID / "result.json").exists()
            )

    def test_restart_marks_nonterminal_existing_operation_interrupted_without_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, operation_root, _ = self.layout(root)
            request_path = agent.inbox / f"{self.REQUEST_ID}.json"
            raw = canonical(self.request())
            request_path.write_bytes(raw)
            os.chmod(request_path, 0o660)

            agent.runtime.create(
                operation="RUNTIME_SELFTEST",
                source_commit=self.COMMIT,
                mutation_capable=False,
                timeout_seconds=60,
                operation_id=self.REQUEST_ID,
            )
            agent.runtime.start(self.REQUEST_ID)

            result = agent.process(request_path)

            self.assertEqual(result["disposition"], "INTERRUPTED")
            self.assertEqual(result["status"]["execution_state"], "FAILED")
            terminal = json.loads(
                (operation_root / self.REQUEST_ID / "result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(terminal["outcome"], "INTERRUPTED")

    def test_conflicting_replay_is_quarantined_without_agent_restart_loop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, _, control = self.layout(root)
            request_path = agent.inbox / f"{self.REQUEST_ID}.json"
            request_path.write_bytes(canonical(self.request()))
            os.chmod(request_path, 0o660)
            first = agent.process_pending_once()
            self.assertEqual(first["disposition"], "COMPLETED")

            conflicting = self.request(timeout_seconds=120)
            request_path.write_bytes(canonical(conflicting))
            os.chmod(request_path, 0o660)

            rejected = agent.process_pending_once()

            self.assertEqual(rejected["disposition"], "REJECTED")
            self.assertFalse(request_path.exists())
            rejected_files = list((control / "rejected").glob("*.json"))
            self.assertEqual(len(rejected_files), 1)
            self.assertEqual(rejected_files[0].read_bytes(), canonical(conflicting))
            self.assertTrue(
                (control / "processed" / f"{self.REQUEST_ID}.json").exists()
            )

    def test_invalid_pending_request_is_quarantined_instead_of_retry_loop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, _, control = self.layout(root)
            path = agent.inbox / f"{self.REQUEST_ID}.json"
            path.write_bytes(canonical(self.request(operation="ARBITRARY_SHELL")))
            os.chmod(path, 0o600)

            result = agent.process_pending_once()

            self.assertEqual(result["disposition"], "REJECTED")
            self.assertFalse(path.exists())
            self.assertTrue(
                (control / "rejected" / f"{self.REQUEST_ID}.json").exists()
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
