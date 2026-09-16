from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .drive_backend import DriveBackend, DriveTransportError, DriveUncertainMutation
from .drive_poller import DrivePollerConfigError, _token_source_from_environment
from .drive_rest import GoogleDriveBackend
from .pilot_drive import DrivePilotBlocked, DrivePilotImportService
from .pilot_pack import PilotPackBlocked, build_pilot_pack, verify_pilot_pack


class PilotCliError(ValueError):
    pass


def _emit(value: Mapping[str, Any], *, stream=None) -> None:
    target = sys.stdout if stream is None else stream
    print(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")), file=target, flush=True)


class PilotPackCommandSurface:
    @staticmethod
    def build(source_root: str, source_manifest: str, output_dir: str) -> dict[str, Any]:
        pack = build_pilot_pack(source_root, source_manifest, output_dir)
        return {"pack": pack.public_summary()}

    @staticmethod
    def verify(pack_dir: str) -> dict[str, Any]:
        pack = verify_pilot_pack(pack_dir)
        return {"pack": pack.public_summary()}


class DrivePilotCommandSurface:
    def __init__(self, drive: DriveBackend, hub_root_id: str):
        if not isinstance(hub_root_id, str) or not hub_root_id or hub_root_id != hub_root_id.strip():
            raise PilotCliError("hub_root_id must be a non-empty trimmed string")
        self.drive = drive
        self.hub_root_id = hub_root_id

    def import_pack(self, pack_dir: str) -> dict[str, Any]:
        pack = verify_pilot_pack(pack_dir)
        evidence = DrivePilotImportService(self.drive, self.hub_root_id).run(pack)
        return {"pilot": evidence.to_json_value()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-pilot")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("pack-build", help="Build an immutable private pilot pack from an explicit local allowlist")
    build.add_argument("--source-root", required=True, help="Read-only local copy root containing selected source files")
    build.add_argument("--source-manifest", required=True, help="PILOT_SOURCE.json allowlist outside or inside the source copy")
    build.add_argument("--output-dir", required=True, help="New output directory; existing paths are rejected")

    verify = sub.add_parser("pack-verify", help="Verify one immutable private pilot pack")
    verify.add_argument("--pack-dir", required=True)

    imp = sub.add_parser("import", help="Import one verified private pack into one fresh disposable Drive Hub")
    imp.add_argument("--pack-dir", required=True)
    imp.add_argument(
        "--hub-root-id",
        default=os.environ.get("KEELARYN_HUB_ROOT_ID"),
        help="Exact disposable Google Drive Hub root ID (or KEELARYN_HUB_ROOT_ID)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "pack-build":
            value = PilotPackCommandSurface.build(args.source_root, args.source_manifest, args.output_dir)
        elif args.command == "pack-verify":
            value = PilotPackCommandSurface.verify(args.pack_dir)
        else:
            if not args.hub_root_id:
                raise PilotCliError("--hub-root-id or KEELARYN_HUB_ROOT_ID is required")
            token_source = _token_source_from_environment("once")
            surface = DrivePilotCommandSurface(GoogleDriveBackend(token_source), args.hub_root_id)
            value = surface.import_pack(args.pack_dir)
        _emit(value)
        return 0
    except (PilotCliError, PilotPackBlocked, DrivePilotBlocked, DrivePollerConfigError) as exc:
        _emit({"error": "BLOCKED", "detail": str(exc)}, stream=sys.stderr)
        return 2
    except (DriveUncertainMutation, DriveTransportError) as exc:
        _emit({"error": "REOBSERVE_REQUIRED", "detail": str(exc)}, stream=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DrivePilotCommandSurface", "PilotCliError", "PilotPackCommandSurface", "main"]
