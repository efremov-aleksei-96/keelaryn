from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

import hub_cutover

SCHEMA = "keelaryn.zero-vps-hub-cutover-rehearsal.v1"
OLD_HUB_ROOT_ID = "DISPOSABLE_OLD_HUB_ROOT_0001"
NEW_HUB_ROOT_ID = "DISPOSABLE_NEW_HUB_ROOT_0002"


class HubCutoverRehearsalError(RuntimeError):
    pass


def _source_commit(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise HubCutoverRehearsalError(
            "source commit must be exactly 40 lowercase hexadecimal characters"
        )
    return value


def _write_selector(path: Path, hub_root_id: str) -> None:
    path.write_bytes(f"{hub_cutover.SELECTOR_KEY}={hub_root_id}\n".encode("ascii"))
    os.chmod(path, 0o600)


def _load_single_json(root: Path, label: str) -> dict[str, Any]:
    members = sorted(root.glob("*.json"))
    if len(members) != 1:
        raise HubCutoverRehearsalError(f"{label} must contain exactly one JSON record")
    if members[0].is_symlink() or not members[0].is_file():
        raise HubCutoverRehearsalError(f"{label} record must be a regular file")
    try:
        value = json.loads(members[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubCutoverRehearsalError(f"{label} record is invalid") from exc
    if not isinstance(value, dict):
        raise HubCutoverRehearsalError(f"{label} record must be a JSON object")
    return value


def _new_switch(selector: Path, state: Path, source_commit: str) -> hub_cutover.HubSelectorCutover:
    return hub_cutover.HubSelectorCutover(
        selector,
        state,
        source_commit,
        executing_tool=Path(hub_cutover.__file__),
    )


def _verify_terminal_state(
    selector: Path,
    state: Path,
    *,
    expected_hub_root_id: str,
    expected_outcome: str,
) -> None:
    expected = f"{hub_cutover.SELECTOR_KEY}={expected_hub_root_id}\n".encode("ascii")
    if selector.read_bytes() != expected:
        raise HubCutoverRehearsalError("terminal selector bytes are not exact")
    info = selector.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise HubCutoverRehearsalError("terminal selector is not regular mode 0600")
    if (state / hub_cutover.ACTIVE_NAME).exists() or (state / hub_cutover.ACTIVE_NAME).is_symlink():
        raise HubCutoverRehearsalError("terminal rehearsal left active transaction authority")

    history = _load_single_json(state / "history", "history")
    terminal = _load_single_json(state / "terminal", "terminal")
    if history.get("schema") != hub_cutover.SCHEMA:
        raise HubCutoverRehearsalError("history schema mismatch")
    if terminal.get("schema") != hub_cutover.TERMINAL_SCHEMA:
        raise HubCutoverRehearsalError("terminal schema mismatch")
    if terminal.get("outcome") != expected_outcome:
        raise HubCutoverRehearsalError("terminal outcome mismatch")
    if history.get("transaction_id") != terminal.get("transaction_id"):
        raise HubCutoverRehearsalError("history/terminal transaction mismatch")


def _run_accept_path(root: Path, source_commit: str) -> None:
    selector = root / "hub.env"
    state = root / "deployment"
    _write_selector(selector, OLD_HUB_ROOT_ID)

    first = _new_switch(selector, state, source_commit)
    prepared = first.prepare(NEW_HUB_ROOT_ID)
    if prepared.get("status") != "PREPARED":
        raise HubCutoverRehearsalError("accept path did not prepare")
    if first.apply().get("status") != "APPLIED":
        raise HubCutoverRehearsalError("accept path did not apply")

    restarted = _new_switch(selector, state, source_commit)
    if restarted.status().get("status") != "APPLIED":
        raise HubCutoverRehearsalError("accept path restart did not recover APPLIED")
    if restarted.accept() != {"status": "IDLE"}:
        raise HubCutoverRehearsalError("accept path did not settle to IDLE")
    if _new_switch(selector, state, source_commit).status() != {"status": "IDLE"}:
        raise HubCutoverRehearsalError("accepted path did not remain IDLE after restart")

    _verify_terminal_state(
        selector,
        state,
        expected_hub_root_id=NEW_HUB_ROOT_ID,
        expected_outcome="ACCEPTED",
    )


def _run_rollback_path(root: Path, source_commit: str) -> None:
    selector = root / "hub.env"
    state = root / "deployment"
    _write_selector(selector, OLD_HUB_ROOT_ID)

    first = _new_switch(selector, state, source_commit)
    prepared = first.prepare(NEW_HUB_ROOT_ID)
    if prepared.get("status") != "PREPARED":
        raise HubCutoverRehearsalError("rollback path did not prepare")
    if first.apply().get("status") != "APPLIED":
        raise HubCutoverRehearsalError("rollback path did not apply")

    restarted = _new_switch(selector, state, source_commit)
    if restarted.status().get("status") != "APPLIED":
        raise HubCutoverRehearsalError("rollback path restart did not recover APPLIED")
    if restarted.rollback() != {"status": "IDLE"}:
        raise HubCutoverRehearsalError("rollback path did not settle to IDLE")
    if _new_switch(selector, state, source_commit).status() != {"status": "IDLE"}:
        raise HubCutoverRehearsalError("rolled-back path did not remain IDLE after restart")

    _verify_terminal_state(
        selector,
        state,
        expected_hub_root_id=OLD_HUB_ROOT_ID,
        expected_outcome="ROLLED_BACK",
    )


def run_rehearsal(source_commit: str) -> dict[str, Any]:
    source_commit = _source_commit(source_commit)
    with tempfile.TemporaryDirectory(prefix="keelaryn-hub-cutover-rehearsal-") as temp:
        root = Path(temp)
        accept_root = root / "accept"
        rollback_root = root / "rollback"
        accept_root.mkdir(mode=0o700)
        rollback_root.mkdir(mode=0o700)
        _run_accept_path(accept_root, source_commit)
        _run_rollback_path(rollback_root, source_commit)

    evidence = {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "accept_path_verified": True,
        "rollback_path_verified": True,
        "restart_recovery_verified": True,
        "terminal_history_verified": True,
        "selector_bytes_verified": True,
        "hub_bytes_touched": False,
    }
    raw = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if OLD_HUB_ROOT_ID.encode("ascii") in raw or NEW_HUB_ROOT_ID.encode("ascii") in raw:
        raise HubCutoverRehearsalError("sanitized evidence leaked disposable Hub identity")
    return evidence


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise HubCutoverRehearsalError("evidence output already exists")
    raw = (
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-hub-cutover-rehearsal")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = run_rehearsal(args.source_commit)
        write_evidence(args.output, evidence)
    except (HubCutoverRehearsalError, hub_cutover.HubCutoverError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
