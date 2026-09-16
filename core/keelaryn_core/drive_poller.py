from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Mapping

from .drive_backend import DriveTransportError, DriveUncertainMutation
from .drive_bootstrap import DriveBootstrapBlocked, DriveBootstrapResult, DriveHubBootstrap
from .drive_oauth import GoogleOAuthRefreshTokenProvider
from .drive_rest import GoogleDriveBackend
from .drive_service import DrivePollingService, DriveServiceBlocked, DriveServiceStatus
from .protocol import ProtocolError


class DrivePollerConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DrivePollerResult:
    kind: str
    phase: str
    detail: str
    ready_clean: bool | None = None

    def to_json(self) -> str:
        value: dict[str, object] = {
            "kind": self.kind,
            "phase": self.phase,
            "detail": self.detail,
        }
        if self.ready_clean is not None:
            value["ready_clean"] = self.ready_clean
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class DrivePoller:
    """Small process wrapper around bootstrap and one polling service iteration."""

    def __init__(self, backend: GoogleDriveBackend, hub_root_id: str):
        if not isinstance(hub_root_id, str) or not hub_root_id or hub_root_id != hub_root_id.strip():
            raise DrivePollerConfigError("hub_root_id must be a non-empty trimmed string")
        self.backend = backend
        self.hub_root_id = hub_root_id

    def bootstrap(self) -> DrivePollerResult:
        result: DriveBootstrapResult = DriveHubBootstrap(self.backend, self.hub_root_id).run()
        return DrivePollerResult(
            "bootstrap",
            result.state,
            f"MASTER {result.master['state']}/{result.master['canonical_read_status']} epoch={result.master['canonical_epoch']}",
            result.master["canonical_read_status"] == "SAFE",
        )

    def run_once(self) -> DrivePollerResult:
        status: DriveServiceStatus = DrivePollingService(self.backend, self.hub_root_id).run_once()
        return DrivePollerResult("service", status.phase, status.detail, status.ready_clean)


def _token_source_from_environment(command: str, env: Mapping[str, str] | None = None):
    source = os.environ if env is None else env
    refresh_names = (
        "KEELARYN_GOOGLE_CLIENT_ID",
        "KEELARYN_GOOGLE_CLIENT_SECRET",
        "KEELARYN_GOOGLE_REFRESH_TOKEN",
    )
    if all(source.get(name) for name in refresh_names):
        return GoogleOAuthRefreshTokenProvider.from_environment(source)

    access_token = source.get("KEELARYN_GOOGLE_ACCESS_TOKEN")
    if access_token:
        if command == "serve":
            raise DrivePollerConfigError(
                "continuous serve mode requires refresh credentials; static access token is allowed only for bootstrap/once"
            )
        if not isinstance(access_token, str) or not access_token or access_token != access_token.strip():
            raise DrivePollerConfigError("KEELARYN_GOOGLE_ACCESS_TOKEN is malformed")
        return access_token

    missing = [name for name in refresh_names if not source.get(name)]
    raise DrivePollerConfigError(
        "Google authentication is not configured; provide refresh credentials"
        + (" or KEELARYN_GOOGLE_ACCESS_TOKEN for bootstrap/once" if command != "serve" else "")
        + "; missing: "
        + ", ".join(missing)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-drive")
    parser.add_argument(
        "--hub-root-id",
        default=os.environ.get("KEELARYN_HUB_ROOT_ID"),
        help="Google Drive file ID of the Keelaryn Hub root (or KEELARYN_HUB_ROOT_ID)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Initialize a fresh disposable Hub or verify an initialized Hub")
    sub.add_parser("once", help="Run one restart-safe polling iteration")
    serve = sub.add_parser("serve", help="Run the MVP polling loop")
    serve.add_argument("--interval-seconds", type=float, default=30.0)
    return parser


def _emit(result: DrivePollerResult, *, stream=None) -> None:
    target = sys.stdout if stream is None else stream
    print(result.to_json(), file=target, flush=True)


def _fatal_result(kind: str, phase: str, detail: str) -> DrivePollerResult:
    return DrivePollerResult(kind, phase, detail, False)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.hub_root_id:
        print("ERROR: --hub-root-id or KEELARYN_HUB_ROOT_ID is required", file=sys.stderr)
        return 2
    try:
        token_source = _token_source_from_environment(args.command)
        poller = DrivePoller(GoogleDriveBackend(token_source), args.hub_root_id)
        if args.command == "bootstrap":
            _emit(poller.bootstrap())
            return 0
        if args.command == "once":
            result = poller.run_once()
            _emit(result)
            return 2 if result.phase in {"RECOVERY_BLOCKED", "ABORTED_SAFE"} else 0

        interval = args.interval_seconds
        if not isinstance(interval, float) or interval < 1.0 or interval > 3600.0:
            raise DrivePollerConfigError("--interval-seconds must be between 1 and 3600")
        while True:
            try:
                result = poller.run_once()
                _emit(result)
                if result.phase in {"RECOVERY_BLOCKED", "ABORTED_SAFE"}:
                    return 2
            except (DriveUncertainMutation, DriveTransportError) as exc:
                # No mutation is retried in place. A later top-level iteration will
                # re-observe exact Drive state before deciding what to do next.
                _emit(_fatal_result("transport", "REOBSERVE_REQUIRED", str(exc)), stream=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 130
    except (DrivePollerConfigError, DriveBootstrapBlocked, DriveServiceBlocked, ProtocolError) as exc:
        _emit(_fatal_result("error", "BLOCKED", str(exc)), stream=sys.stderr)
        return 2
    except (DriveUncertainMutation, DriveTransportError) as exc:
        _emit(_fatal_result("transport", "REOBSERVE_REQUIRED", str(exc)), stream=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DrivePoller",
    "DrivePollerConfigError",
    "DrivePollerResult",
    "main",
]
