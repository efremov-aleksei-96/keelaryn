from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .operation_runtime import OperationRuntime, OperationRuntimeError


def _render(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation")
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="private durable operation runtime root",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="print sanitized durable operation status")
    status.add_argument("--operation-id", default="latest")

    watch = sub.add_parser(
        "watch",
        help="watch sanitized status without controlling the operation process",
    )
    watch.add_argument("--operation-id", default="latest")
    watch.add_argument("--interval-seconds", type=float, default=2.0)
    watch.add_argument("--max-seconds", type=float, default=0.0)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runtime = OperationRuntime(args.root)
        if args.command == "status":
            print(_render(runtime.status(args.operation_id)))
            return 0

        if args.interval_seconds <= 0:
            raise OperationRuntimeError("watch interval must be positive")
        if args.max_seconds < 0:
            raise OperationRuntimeError("watch max-seconds cannot be negative")

        started = time.monotonic()
        previous = None
        while True:
            value = runtime.status(args.operation_id)
            rendered = _render(value)
            if rendered != previous:
                print(rendered, flush=True)
                previous = rendered
            if value["terminal"]:
                return 0
            if args.max_seconds and time.monotonic() - started >= args.max_seconds:
                return 3
            time.sleep(args.interval_seconds)
    except (OperationRuntimeError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
