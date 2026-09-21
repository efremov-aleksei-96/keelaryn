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

from keelaryn_core.operation_agent import OperationAgent  # noqa: E402
from keelaryn_core.operation_request import REQUEST_SCHEMA  # noqa: E402
from keelaryn_core.operation_transport import (  # noqa: E402
    GitHubIssueClient,
    GitHubOperationTransport,
    GitHubTransportError,
    IssueComment,
    REQUEST_MARKER,
    STATUS_MARKER,
)


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


class FakeGitHub:
    def __init__(self) -> None:
        self.comments: list[IssueComment] = []
        self.created: list[str] = []
        self.updated: list[tuple[int, str]] = []
        self.next_id = 1000
        self.authenticated_actor = "keelaryn-bot"
        self.events: list[str] = []

    def add(self, actor: str, body: str, *, comment_id: int | None = None) -> IssueComment:
        cid = self.next_id if comment_id is None else comment_id
        self.next_id = max(self.next_id + 1, cid + 1)
        value = IssueComment(
            cid,
            actor,
            body,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        )
        self.comments.append(value)
        self.comments.sort(key=lambda item: item.comment_id)
        return value

    def authenticated_login(self) -> str:
        self.events.append("authenticated_login")
        return self.authenticated_actor

    def list_comments(self) -> list[IssueComment]:
        self.events.append("list_comments")
        return list(self.comments)

    def create_comment(self, body: str) -> IssueComment:
        self.created.append(body)
        return self.add("keelaryn-bot", body)

    def update_comment(self, comment_id: int, body: str) -> IssueComment:
        self.updated.append((comment_id, body))
        for index, value in enumerate(self.comments):
            if value.comment_id == comment_id:
                updated = IssueComment(
                    comment_id,
                    value.actor,
                    body,
                    value.created_at,
                    "2026-01-01T00:01:00Z",
                )
                self.comments[index] = updated
                return updated
        raise AssertionError("missing fake comment")


class Clock:
    def __init__(self) -> None:
        self.value = 1_800_000_000.0

    def __call__(self) -> float:
        return self.value


class GitHubOperationTransportTests(unittest.TestCase):
    COMMIT = "a" * 40
    REQUEST_ID = "1" * 32

    def request(self) -> dict[str, object]:
        return {
            "schema": REQUEST_SCHEMA,
            "request_id": self.REQUEST_ID,
            "operation": "RUNTIME_SELFTEST",
            "source_commit": self.COMMIT,
            "profile": "DEFAULT",
            "mutation_capable": False,
            "timeout_seconds": 60,
            "approval": "NOT_REQUIRED",
        }

    def request_comment(self, value: dict[str, object]) -> str:
        return REQUEST_MARKER + canonical(value).decode("utf-8").rstrip("\n")

    def layout(self, root: Path, api: FakeGitHub):
        transport_root = root / "transport"
        os.mkdir(transport_root, 0o750)
        os.chmod(transport_root, 0o750)
        return GitHubOperationTransport(
            transport_root,
            api,
            source_commit=self.COMMIT,
            allowed_actors={"alexey"},
            status_actor="keelaryn-bot",
            clock=Clock(),
        )

    def test_client_authenticated_login_uses_exact_github_identity(self) -> None:
        client = GitHubIssueClient(
            "efremov-aleksei-96/keelaryn",
            65,
            "github_pat_" + ("A" * 40),
        )
        with mock.patch.object(
            client,
            "_request",
            return_value=(200, b'{"login":"efremov-aleksei-96"}'),
        ) as request:
            self.assertEqual(client.authenticated_login(), "efremov-aleksei-96")
        request.assert_called_once_with("GET", "/user")

    def test_startup_probe_authenticates_expected_actor_before_live_poll(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            api = FakeGitHub()
            transport = self.layout(root, api)

            result = transport.startup_probe()

            self.assertEqual(result["authenticated_actor"], "keelaryn-bot")
            self.assertEqual(
                result["poll"]["schema"],
                "keelaryn.github-operation-transport-poll.v1",
            )
            self.assertEqual(
                api.events[:2],
                ["authenticated_login", "list_comments"],
            )

            api.authenticated_actor = "other-actor"
            with self.assertRaisesRegex(
                GitHubTransportError,
                "authenticated actor mismatch",
            ):
                transport.startup_probe()

    def test_authorized_comment_delivers_exact_private_request_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            api = FakeGitHub()
            api.add("alexey", self.request_comment(self.request()), comment_id=10)
            transport = self.layout(root, api)

            first = transport.poll_once()
            second = transport.poll_once()

            self.assertEqual(first["delivered"], 1)
            self.assertEqual(second["delivered"], 0)
            path = transport.inbox / f"{self.REQUEST_ID}.json"
            self.assertEqual(path.read_bytes(), canonical(self.request()))
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_unauthorized_and_malformed_comments_advance_cursor_without_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            api = FakeGitHub()
            api.add("mallory", self.request_comment(self.request()), comment_id=10)
            api.add("alexey", REQUEST_MARKER + "{not-json}", comment_id=11)
            transport = self.layout(root, api)

            result = transport.poll_once()

            self.assertEqual(result["delivered"], 0)
            self.assertEqual(result["rejected"], 2)
            state = json.loads(transport.state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["last_comment_id"], 11)
            self.assertEqual(list(transport.inbox.iterdir()), [])

    def test_agent_executes_request_and_transport_publishes_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            api = FakeGitHub()
            api.add("alexey", self.request_comment(self.request()), comment_id=10)
            transport = self.layout(root, api)
            transport.poll_once()

            operation_root = root / "operations"
            control_root = root / "control"
            operation_root.mkdir(mode=0o700)
            control_root.mkdir(mode=0o700)
            os.chmod(operation_root, 0o700)
            os.chmod(control_root, 0o700)
            agent = OperationAgent(
                operation_root,
                control_root,
                transport.root,
                source_commit=self.COMMIT,
            )

            result = agent.process_pending_once()
            self.assertEqual(result["disposition"], "COMPLETED")

            published = transport.poll_once()
            self.assertEqual(published["status_created"], 1)
            self.assertEqual(len(api.created), 1)
            self.assertTrue(api.created[0].startswith(STATUS_MARKER))
            payload = json.loads(api.created[0][len(STATUS_MARKER):])
            self.assertEqual(payload["operation_id"], self.REQUEST_ID)
            self.assertEqual(payload["execution_state"], "SUCCEEDED")
            self.assertTrue(payload["terminal"])
            self.assertEqual(payload["outcome"], "PASS")

            again = transport.poll_once()
            self.assertEqual(again["status_created"], 0)
            self.assertEqual(again["status_updated"], 0)

    def test_untrusted_remote_status_cannot_be_adopted_as_transport_publication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            api = FakeGitHub()
            transport = self.layout(root, api)

            relay = {
                "schema": "keelaryn.operation-relay-status.v1",
                "operation_id": self.REQUEST_ID,
                "operation": "RUNTIME_SELFTEST",
                "source_commit": self.COMMIT,
                "execution_state": "SUCCEEDED",
                "observed_state": "SUCCEEDED",
                "mutation_state": "READ_ONLY",
                "phase": "COMPLETE",
                "event": "TERMINAL",
                "sequence": 0,
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "next_action": "NONE",
                "terminal": True,
                "outcome": "PASS",
            }
            relay_path = transport.outbox / f"{self.REQUEST_ID}.json"
            relay_path.write_bytes(canonical(relay))
            os.chmod(relay_path, 0o640)
            body = STATUS_MARKER + canonical(relay).decode("utf-8").rstrip("\n")
            api.add("mallory", body, comment_id=55)

            result = transport.poll_once()

            self.assertEqual(result["status_created"], 1)
            self.assertEqual(api.updated, [])
            state = json.loads(transport.state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(
                state["status_comments"][self.REQUEST_ID]["comment_id"],
                55,
            )

    def test_existing_remote_status_is_adopted_instead_of_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.chmod(root, 0o700)
            api = FakeGitHub()
            transport = self.layout(root, api)

            relay = {
                "schema": "keelaryn.operation-relay-status.v1",
                "operation_id": self.REQUEST_ID,
                "operation": "RUNTIME_SELFTEST",
                "source_commit": self.COMMIT,
                "execution_state": "SUCCEEDED",
                "observed_state": "SUCCEEDED",
                "mutation_state": "READ_ONLY",
                "phase": "COMPLETE",
                "event": "TERMINAL",
                "sequence": 0,
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "next_action": "NONE",
                "terminal": True,
                "outcome": "PASS",
            }
            relay_path = transport.outbox / f"{self.REQUEST_ID}.json"
            relay_path.write_bytes(canonical(relay))
            os.chmod(relay_path, 0o640)
            body = STATUS_MARKER + canonical(relay).decode("utf-8").rstrip("\n")
            api.add("keelaryn-bot", body, comment_id=55)

            result = transport.poll_once()

            self.assertEqual(result["status_created"], 0)
            self.assertEqual(api.created, [])
            state = json.loads(transport.state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                state["status_comments"][self.REQUEST_ID]["comment_id"],
                55,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
