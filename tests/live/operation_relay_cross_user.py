from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from keelaryn_core.operation_agent import OperationAgent
from keelaryn_core.operation_transport import (
    GitHubOperationTransport,
    IssueComment,
    REQUEST_MARKER,
    STATUS_MARKER,
)


REQUEST_ID = "0123456789abcdef0123456789abcdef"
REQUEST_ACTOR = "requester"
STATUS_ACTOR = "publisher"


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


def request(source_commit: str) -> dict[str, object]:
    return {
        "schema": "keelaryn.operation-request.v1",
        "request_id": REQUEST_ID,
        "operation": "RUNTIME_SELFTEST",
        "source_commit": source_commit,
        "profile": "DEFAULT",
        "mutation_capable": False,
        "timeout_seconds": 60,
        "approval": "NOT_REQUIRED",
    }


def request_body(source_commit: str) -> str:
    return REQUEST_MARKER + canonical(request(source_commit)).decode("utf-8").rstrip("\n")


class DeliverApi:
    def __init__(self, source_commit: str) -> None:
        self.source_commit = source_commit

    def authenticated_login(self) -> str:
        return STATUS_ACTOR

    def list_comments(self) -> list[IssueComment]:
        return [
            IssueComment(
                comment_id=1,
                actor=REQUEST_ACTOR,
                body=request_body(self.source_commit),
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )
        ]

    def create_comment(self, body: str) -> IssueComment:
        raise AssertionError("delivery phase must not publish status")

    def update_comment(self, comment_id: int, body: str) -> IssueComment:
        raise AssertionError("delivery phase must not update status")


class PublishApi:
    def __init__(self) -> None:
        self.created: list[str] = []

    def authenticated_login(self) -> str:
        return STATUS_ACTOR

    def list_comments(self) -> list[IssueComment]:
        return []

    def create_comment(self, body: str) -> IssueComment:
        self.created.append(body)
        return IssueComment(
            comment_id=2,
            actor=STATUS_ACTOR,
            body=body,
            created_at="2026-01-01T00:00:01Z",
            updated_at="2026-01-01T00:00:01Z",
        )

    def update_comment(self, comment_id: int, body: str) -> IssueComment:
        raise AssertionError("first publication must create one status comment")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def prove_transport_identity(root: Path) -> None:
    if os.geteuid() == 0:
        raise SystemExit("transport phase must run as a non-root UID")
    if root.stat(follow_symlinks=False).st_uid != os.geteuid():
        raise SystemExit("transport relay root owner does not match transport UID")
    if root.stat(follow_symlinks=False).st_gid != os.getegid():
        raise SystemExit("transport relay root group does not match shared GID")
    if mode(root) != 0o750:
        raise SystemExit("transport relay root mode is not 0750")
    for name in ("inbox", "outbox"):
        path = root / name
        if path.stat(follow_symlinks=False).st_gid != os.getegid():
            raise SystemExit(f"{name} group does not match shared GID")
        if mode(path) != 0o2770:
            raise SystemExit(f"{name} mode is not 2770")
    state = root / "state"
    if mode(state) != 0o700:
        raise SystemExit("transport private state directory mode is not 0700")


def capability_snapshot() -> dict[str, int]:
    wanted = {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}
    values: dict[str, int] = {}
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        name, sep, raw = line.partition(":")
        if sep and name in wanted:
            values[name] = int(raw.strip(), 16)
    if set(values) != wanted:
        raise SystemExit("cannot read exact Linux capability set")
    return values


def transport_deliver(root: Path, source_commit: str) -> None:
    transport = GitHubOperationTransport(
        root,
        DeliverApi(source_commit),
        source_commit=source_commit,
        allowed_actors={REQUEST_ACTOR},
        status_actor=STATUS_ACTOR,
    )
    result = transport.poll_once()
    if result["delivered"] != 1 or result["rejected"] != 0:
        raise SystemExit("transport did not deliver exact request")
    prove_transport_identity(root)
    request_path = transport.inbox / f"{REQUEST_ID}.json"
    if request_path.stat(follow_symlinks=False).st_uid != os.geteuid():
        raise SystemExit("transport request owner does not match transport UID")
    if request_path.stat(follow_symlinks=False).st_gid != os.getegid():
        raise SystemExit("transport request group does not match shared GID")
    if mode(request_path) != 0o660:
        raise SystemExit("transport request mode is not 0660")
    print(json.dumps({
        "phase": "TRANSPORT_DELIVER",
        "transport_uid": os.geteuid(),
        "shared_gid": os.getegid(),
        "request_mode": "0660",
        "result": "PASS",
    }, sort_keys=True, separators=(",", ":")))


def agent_process(
    transport_root: Path,
    operation_root: Path,
    control_root: Path,
    source_commit: str,
    expected_gid: int,
) -> None:
    if os.geteuid() != 0:
        raise SystemExit("agent phase must retain UID 0")
    if os.getegid() != expected_gid:
        raise SystemExit("agent effective GID does not match shared relay GID")
    caps = capability_snapshot()
    if any(caps.values()):
        raise SystemExit(f"agent process retained Linux capabilities: {caps}")

    agent = OperationAgent(
        operation_root,
        control_root,
        transport_root,
        source_commit=source_commit,
    )
    result = agent.process_pending_once()
    if result is None or result.get("disposition") != "COMPLETED":
        raise SystemExit(f"agent did not complete shared relay request: {result}")
    if result["status"]["observed_state"] != "SUCCEEDED":
        raise SystemExit("agent selftest did not succeed")

    if (transport_root / "inbox" / f"{REQUEST_ID}.json").exists():
        raise SystemExit("agent did not archive delivered request")
    status = transport_root / "outbox" / f"{REQUEST_ID}.json"
    if status.stat(follow_symlinks=False).st_uid != 0:
        raise SystemExit("agent relay status is not root-owned")
    if status.stat(follow_symlinks=False).st_gid != expected_gid:
        raise SystemExit("agent relay status does not retain shared GID")
    if mode(status) != 0o660:
        raise SystemExit("agent relay status mode is not 0660")

    print(json.dumps({
        "phase": "AGENT_PROCESS",
        "agent_uid": os.geteuid(),
        "shared_gid": os.getegid(),
        "capabilities": caps,
        "status_mode": "0660",
        "result": "PASS",
    }, sort_keys=True, separators=(",", ":")))


def transport_publish(root: Path, source_commit: str) -> None:
    api = PublishApi()
    transport = GitHubOperationTransport(
        root,
        api,
        source_commit=source_commit,
        allowed_actors={REQUEST_ACTOR},
        status_actor=STATUS_ACTOR,
    )
    prove_transport_identity(root)
    result = transport.poll_once()
    if result["status_created"] != 1 or result["status_updated"] != 0:
        raise SystemExit("transport did not publish agent status exactly once")
    if len(api.created) != 1 or not api.created[0].startswith(STATUS_MARKER):
        raise SystemExit("transport publication body is not exact status protocol")
    payload = json.loads(api.created[0][len(STATUS_MARKER):])
    if (
        payload.get("operation_id") != REQUEST_ID
        or payload.get("terminal") is not True
        or payload.get("outcome") != "PASS"
    ):
        raise SystemExit("published terminal status identity/outcome mismatch")

    print(json.dumps({
        "phase": "TRANSPORT_PUBLISH",
        "transport_uid": os.geteuid(),
        "shared_gid": os.getegid(),
        "status_created": result["status_created"],
        "outcome": payload["outcome"],
        "result": "PASS",
    }, sort_keys=True, separators=(",", ":")))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="operation-relay-cross-user")
    sub = value.add_subparsers(dest="command", required=True)

    deliver = sub.add_parser("transport-deliver")
    deliver.add_argument("--root", required=True, type=Path)
    deliver.add_argument("--source-commit", required=True)

    agent = sub.add_parser("agent-process")
    agent.add_argument("--transport-root", required=True, type=Path)
    agent.add_argument("--operation-root", required=True, type=Path)
    agent.add_argument("--control-root", required=True, type=Path)
    agent.add_argument("--source-commit", required=True)
    agent.add_argument("--expected-gid", required=True, type=int)

    publish = sub.add_parser("transport-publish")
    publish.add_argument("--root", required=True, type=Path)
    publish.add_argument("--source-commit", required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.command == "transport-deliver":
        transport_deliver(args.root, args.source_commit)
    elif args.command == "agent-process":
        agent_process(
            args.transport_root,
            args.operation_root,
            args.control_root,
            args.source_commit,
            args.expected_gid,
        )
    else:
        transport_publish(args.root, args.source_commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
