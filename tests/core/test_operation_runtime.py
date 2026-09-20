from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.operation_runtime import (  # noqa: E402
    OperationRuntime,
    OperationRuntimeError,
)


class FakeClock:
    def __init__(self, value: float = 1_800_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class OperationRuntimeTests(unittest.TestCase):
    def runtime(self, root: Path, clock: FakeClock | None = None) -> OperationRuntime:
        if root.exists():
            os.chmod(root, 0o700)
        return OperationRuntime(root, clock=clock or FakeClock())

    def test_create_publishes_private_state_handoff_and_latest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "operations"
            runtime = self.runtime(root)
            state = runtime.create(
                operation="READ_ONLY_TEST",
                source_commit="a" * 40,
                mutation_capable=False,
                timeout_seconds=30,
                operation_id="1" * 32,
            )

            self.assertEqual(state["execution_state"], "CREATED")
            self.assertEqual(state["mutation_state"], "READ_ONLY")
            self.assertEqual(runtime.resolve_operation_id("latest"), "1" * 32)

            operation = root / ("1" * 32)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(operation.stat().st_mode), 0o700)
                for name in ("state.json", "handoff.json"):
                    self.assertEqual(
                        stat.S_IMODE((operation / name).stat().st_mode),
                        0o600,
                    )
                self.assertEqual(stat.S_IMODE((root / "LATEST").stat().st_mode), 0o600)

            handoff = json.loads((operation / "handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["next_action"], "START")
            self.assertNotIn(str(root), json.dumps(handoff))

    def test_read_only_session_emits_heartbeat_and_finishes_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            runtime = self.runtime(root)
            state = runtime.create(
                operation="READ_ONLY_TEST",
                source_commit="b" * 40,
                mutation_capable=False,
                timeout_seconds=60,
            )
            stream = io.StringIO()

            with runtime.session(
                state["operation_id"],
                heartbeat_seconds=60,
                stream=stream,
            ) as session:
                session.record(
                    phase="VERIFY",
                    event="PHASE_BEGIN",
                    item_index=1,
                    item_total=2,
                )
                assert session.journal is not None
                session.journal.heartbeat_once()
                session.record(
                    phase="VERIFY",
                    event="PHASE_COMPLETE",
                    item_index=2,
                    item_total=2,
                )

            status = runtime.status(state["operation_id"])
            self.assertEqual(status["execution_state"], "SUCCEEDED")
            self.assertEqual(status["observed_state"], "SUCCEEDED")
            self.assertEqual(status["next_action"], "NONE")
            self.assertTrue(status["terminal"])

            progress = (
                root / state["operation_id"] / "progress.jsonl"
            ).read_text(encoding="utf-8")
            self.assertIn('"event":"HEARTBEAT"', progress)
            self.assertIn("GATE_PROGRESS", stream.getvalue())

    def test_mutation_boundaries_are_sequential_and_failure_requires_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            runtime = self.runtime(root)
            state = runtime.create(
                operation="MUTATION_TEST",
                source_commit="c" * 40,
                mutation_capable=True,
                timeout_seconds=60,
            )
            oid = state["operation_id"]
            runtime.start(oid)

            with self.assertRaises(OperationRuntimeError):
                runtime.update(oid, mutation_state="COMMITTED")

            runtime.update(oid, mutation_state="PRECOMMIT_VERIFIED")
            runtime.update(oid, mutation_state="COMMITTING")
            runtime.update(oid, mutation_state="COMMITTED")

            result = runtime.finish(
                oid,
                outcome="FAIL",
                phase="POSTCOMMIT_VERIFY",
            )

            self.assertEqual(result["execution_state"], "RECOVERY_REQUIRED")
            self.assertEqual(result["next_action"], "READ_ONLY_RECONCILE")
            status = runtime.status(oid)
            self.assertEqual(status["observed_state"], "RECOVERY_REQUIRED")
            self.assertEqual(status["next_action"], "READ_ONLY_RECONCILE")

    def test_stalled_committing_operation_never_recommends_retry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            clock = FakeClock()
            runtime = self.runtime(root, clock)
            state = runtime.create(
                operation="MUTATION_TEST",
                source_commit="d" * 40,
                mutation_capable=True,
                timeout_seconds=10,
            )
            oid = state["operation_id"]
            runtime.start(oid)
            runtime.update(oid, mutation_state="PRECOMMIT_VERIFIED")
            runtime.update(oid, mutation_state="COMMITTING")

            clock.advance(11)
            status = runtime.status(oid)

            self.assertEqual(status["execution_state"], "RUNNING")
            self.assertEqual(status["observed_state"], "STALLED")
            self.assertEqual(status["next_action"], "READ_ONLY_RECONCILE")
            self.assertFalse(status["terminal"])

    def test_mutation_success_requires_verified_or_noop_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            runtime = self.runtime(root)
            state = runtime.create(
                operation="MUTATION_TEST",
                source_commit="e" * 40,
                mutation_capable=True,
                timeout_seconds=60,
            )
            oid = state["operation_id"]
            runtime.start(oid)
            runtime.update(oid, mutation_state="PRECOMMIT_VERIFIED")

            with self.assertRaises(OperationRuntimeError):
                runtime.finish(oid, outcome="PASS")

            runtime.update(oid, mutation_state="COMMITTING")
            runtime.update(oid, mutation_state="COMMITTED")
            runtime.update(oid, mutation_state="POSTCOMMIT_VERIFYING")
            runtime.update(oid, mutation_state="VERIFIED")
            result = runtime.finish(oid, outcome="PASS")
            self.assertEqual(result["execution_state"], "SUCCEEDED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
