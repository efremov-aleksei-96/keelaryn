from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

import keelaryn_core.operation_agent as operation_agent  # noqa: E402
import keelaryn_core.operation_transport as operation_transport  # noqa: E402
from keelaryn_core.operation_agent import OperationAgent  # noqa: E402
from keelaryn_core.operation_request import REQUEST_SCHEMA  # noqa: E402
from keelaryn_core.operation_transport import GitHubTransportError  # noqa: E402
from keelaryn_core.production_snapshot import (  # noqa: E402
    SNAPSHOT_NAME,
    write_production_snapshot,
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def snapshot() -> dict[str, object]:
    return {
        "schema": "keelaryn.production-snapshot.v1",
        "observed_at_utc": "2026-09-21T17:30:00Z",
        "production_source_commit": "c" * 40,
        "control_source_commit": "a" * 40,
        "services": {
            "writer": {"active_state": "INACTIVE", "main_pid": 0},
            "operation_agent": {"active_state": "ACTIVE", "main_pid": 111},
            "operation_transport": {"active_state": "ACTIVE", "main_pid": 222},
        },
        "legacy_hub": {
            "status": "PREPARED",
            "transaction_id": "2" * 32,
            "selector_role": "OLD",
            "terminal": None,
            "reason": None,
            "active_transaction": {
                "state": "PRESENT",
                "sha256": "3" * 64,
            },
            "mutation_inhibit": {
                "state": "PRESENT",
                "sha256": "4" * 64,
                "transaction_matches": True,
                "active_transaction_matches": True,
            },
        },
        "production_mutations_performed": False,
        "drive_mutations_performed": False,
    }


class OperationSnapshotProtocolTests(unittest.TestCase):
    COMMIT = "a" * 40
    REQUEST_ID = "1" * 32

    def layout(self, root: Path) -> tuple[OperationAgent, Path]:
        operation_root = root / "operations"
        control_root = root / "control"
        transport_root = root / "transport"
        operation_root.mkdir(mode=0o700)
        control_root.mkdir(mode=0o700)
        transport_root.mkdir(mode=0o750)
        os.chmod(operation_root, 0o700)
        os.chmod(control_root, 0o700)
        os.chmod(transport_root, 0o750)
        for name in ("inbox", "outbox"):
            path = transport_root / name
            path.mkdir(mode=0o770)
            os.chmod(path, 0o770)
        return (
            OperationAgent(
                operation_root,
                control_root,
                transport_root,
                source_commit=self.COMMIT,
            ),
            operation_root,
        )

    def request(self, operation: str = "PRODUCTION_SNAPSHOT") -> dict[str, object]:
        return {
            "schema": REQUEST_SCHEMA,
            "request_id": self.REQUEST_ID,
            "operation": operation,
            "source_commit": self.COMMIT,
            "profile": "DEFAULT",
            "mutation_capable": False,
            "timeout_seconds": 60,
            "approval": "NOT_REQUIRED",
        }

    def test_snapshot_executes_fixed_worker_and_replays_durable_result(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            agent, operation_root = self.layout(root)
            request_path = agent.inbox / f"{self.REQUEST_ID}.json"
            request_path.write_bytes(canonical(self.request()))
            os.chmod(request_path, 0o640)

            def worker(operation_id: str) -> None:
                path = operation_root / operation_id / SNAPSHOT_NAME
                write_production_snapshot(path, snapshot())

            with mock.patch.object(
                operation_agent,
                "_run_production_snapshot_worker",
                side_effect=worker,
            ) as run_worker:
                first = agent.process(request_path)

            self.assertEqual(first["disposition"], "COMPLETED")
            run_worker.assert_called_once_with(self.REQUEST_ID)
            relay_path = agent.outbox / f"{self.REQUEST_ID}.json"
            relay = json.loads(relay_path.read_text(encoding="utf-8"))
            self.assertEqual(
                relay["schema"],
                "keelaryn.operation-relay-status.v2",
            )
            self.assertEqual(relay["outcome"], "PASS")
            self.assertEqual(relay["result"], snapshot())

            with mock.patch.object(
                operation_agent,
                "_run_production_snapshot_worker",
                side_effect=AssertionError("worker must not replay"),
            ) as replay_worker:
                second = agent.process(request_path)

            self.assertEqual(second["disposition"], "EXISTING")
            replay_worker.assert_not_called()
            replay = json.loads(relay_path.read_text(encoding="utf-8"))
            self.assertEqual(replay["result"], snapshot())

    def test_transport_accepts_historical_v1_and_snapshot_v2(self) -> None:
        base = {
            "operation_id": self.REQUEST_ID,
            "operation": "RUNTIME_SELFTEST",
            "source_commit": self.COMMIT,
            "execution_state": "SUCCEEDED",
            "observed_state": "SUCCEEDED",
            "mutation_state": "READ_ONLY",
            "phase": "COMPLETE",
            "event": "TERMINAL",
            "sequence": 0,
            "timestamp_utc": "2026-09-21T17:30:00Z",
            "next_action": "NONE",
            "terminal": True,
            "outcome": "PASS",
        }
        v1 = {"schema": "keelaryn.operation-relay-status.v1", **base}
        parsed_v1 = operation_transport._relay_status(canonical(v1))
        self.assertEqual(parsed_v1, v1)

        v2 = {
            "schema": "keelaryn.operation-relay-status.v2",
            **base,
            "operation": "PRODUCTION_SNAPSHOT",
            "result": snapshot(),
        }
        parsed_v2 = operation_transport._relay_status(canonical(v2))
        self.assertEqual(parsed_v2["result"], snapshot())

    def test_transport_rejects_structured_result_for_non_snapshot_status(self) -> None:
        value = {
            "schema": "keelaryn.operation-relay-status.v2",
            "operation_id": self.REQUEST_ID,
            "operation": "RUNTIME_SELFTEST",
            "source_commit": self.COMMIT,
            "execution_state": "SUCCEEDED",
            "observed_state": "SUCCEEDED",
            "mutation_state": "READ_ONLY",
            "phase": "COMPLETE",
            "event": "TERMINAL",
            "sequence": 0,
            "timestamp_utc": "2026-09-21T17:30:00Z",
            "next_action": "NONE",
            "terminal": True,
            "outcome": "PASS",
            "result": snapshot(),
        }
        with self.assertRaisesRegex(
            GitHubTransportError,
            "not authorized",
        ):
            operation_transport._relay_status(canonical(value))

    def test_transport_requires_result_for_successful_snapshot(self) -> None:
        value = {
            "schema": "keelaryn.operation-relay-status.v2",
            "operation_id": self.REQUEST_ID,
            "operation": "PRODUCTION_SNAPSHOT",
            "source_commit": self.COMMIT,
            "execution_state": "SUCCEEDED",
            "observed_state": "SUCCEEDED",
            "mutation_state": "READ_ONLY",
            "phase": "COMPLETE",
            "event": "TERMINAL",
            "sequence": 0,
            "timestamp_utc": "2026-09-21T17:30:00Z",
            "next_action": "NONE",
            "terminal": True,
            "outcome": "PASS",
            "result": None,
        }
        with self.assertRaisesRegex(
            GitHubTransportError,
            "missing result",
        ):
            operation_transport._relay_status(canonical(value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
