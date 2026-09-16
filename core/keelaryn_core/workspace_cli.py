from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .drive_backend import DriveTransportError, DriveUncertainMutation
from .drive_poller import DrivePollerConfigError, _token_source_from_environment
from .drive_rest import GoogleDriveBackend
from .drive_workflow import DriveWorkflowBlocked
from .protocol import ProtocolError
from .workspace import DriveWorkspaceProject, DriveWorkspaceService


class WorkspaceCliError(ValueError):
    pass


def _state_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceCliError("Workspace STATE.md is not valid UTF-8") from exc


def _project_json(project: DriveWorkspaceProject) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "state_markdown": _state_text(project.state_raw),
    }


class DriveWorkspaceCommandSurface:
    """Thin machine-facing adapter over DriveWorkspaceService."""

    def __init__(self, backend: GoogleDriveBackend, hub_root_id: str):
        if not isinstance(hub_root_id, str) or not hub_root_id or hub_root_id != hub_root_id.strip():
            raise WorkspaceCliError("hub_root_id must be a non-empty trimmed string")
        self.workspace = DriveWorkspaceService(backend, hub_root_id)

    def list(self) -> dict[str, Any]:
        return {"projects": [_project_json(project) for project in self.workspace.list_projects()]}

    def read(self, project_id: str) -> dict[str, Any]:
        return {"project": _project_json(self.workspace.read_project(project_id))}

    def create(self, project_id: str, state_markdown: bytes) -> dict[str, Any]:
        _state_text(state_markdown)
        return {"project": _project_json(self.workspace.create_project(project_id, state_markdown))}

    def update(self, project_id: str, update_id: str, state_markdown: bytes) -> dict[str, Any]:
        _state_text(state_markdown)
        result = self.workspace.update_project(project_id, update_id, state_markdown)
        return {
            "project": _project_json(result.project),
            "update_id": result.state_update.update_id,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-workspace")
    parser.add_argument(
        "--hub-root-id",
        default=os.environ.get("KEELARYN_HUB_ROOT_ID"),
        help="Google Drive file ID of the initialized Keelaryn Hub root (or KEELARYN_HUB_ROOT_ID)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List all structurally valid projects and current STATE.md")
    read = sub.add_parser("read", help="Read one project STATE.md")
    read.add_argument("project_id")
    create = sub.add_parser("create", help="Create one project with exact initial STATE.md")
    create.add_argument("project_id")
    create.add_argument("--state-file", required=True, help="UTF-8 STATE.md file, or - for stdin")
    update = sub.add_parser("update", help="Restart-safely replace one project STATE.md")
    update.add_argument("project_id")
    update.add_argument("update_id")
    update.add_argument("--state-file", required=True, help="UTF-8 STATE.md file, or - for stdin")
    return parser


def _read_state_file(value: str, *, stdin=None) -> bytes:
    if value == "-":
        source = sys.stdin.buffer if stdin is None else stdin
        raw = source.read()
    else:
        try:
            raw = Path(value).read_bytes()
        except OSError as exc:
            raise WorkspaceCliError(f"cannot read STATE.md input file: {exc}") from exc
    if not raw:
        raise WorkspaceCliError("STATE.md input must be non-empty")
    _state_text(raw)
    return raw


def _emit(value: Mapping[str, Any], *, stream=None) -> None:
    target = sys.stdout if stream is None else stream
    print(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")), file=target, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.hub_root_id:
        print("ERROR: --hub-root-id or KEELARYN_HUB_ROOT_ID is required", file=sys.stderr)
        return 2
    try:
        token_source = _token_source_from_environment("once")
        surface = DriveWorkspaceCommandSurface(GoogleDriveBackend(token_source), args.hub_root_id)
        if args.command == "list":
            value = surface.list()
        elif args.command == "read":
            value = surface.read(args.project_id)
        elif args.command == "create":
            value = surface.create(args.project_id, _read_state_file(args.state_file))
        else:
            value = surface.update(args.project_id, args.update_id, _read_state_file(args.state_file))
        _emit(value)
        return 0
    except (WorkspaceCliError, DrivePollerConfigError, DriveWorkflowBlocked, ProtocolError) as exc:
        _emit({"error": "BLOCKED", "detail": str(exc)}, stream=sys.stderr)
        return 2
    except (DriveUncertainMutation, DriveTransportError) as exc:
        _emit({"error": "REOBSERVE_REQUIRED", "detail": str(exc)}, stream=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DriveWorkspaceCommandSurface",
    "WorkspaceCliError",
    "main",
]
