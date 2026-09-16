from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import CoreEngine
from .protocol import CoreError, strict_json_bytes, validate_master
from .storage import StorageRuntime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-core")
    parser.add_argument("--hub", required=True, type=Path, help="Keelaryn Hub root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Create a disposable zero-based Hub skeleton")
    sub.add_parser("run", help="Run one deterministic Core wake cycle")
    sub.add_parser("status", help="Print validated MASTER state")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            StorageRuntime.bootstrap(args.hub)
            print("BOOTSTRAPPED")
            return 0
        if args.command == "run":
            print(CoreEngine(args.hub).run())
            return 0
        raw = (args.hub / "MASTER.json").read_bytes()
        master = validate_master(strict_json_bytes(raw, label="MASTER"))
        print(json.dumps(master, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (CoreError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
