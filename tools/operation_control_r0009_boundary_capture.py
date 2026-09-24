from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vps = _load(
    "keelaryn_r0009_boundary_capture_vps",
    Path(__file__).with_name("operation_control_r0009_vps.py"),
)
authority = _load(
    "keelaryn_r0009_boundary_capture_authority",
    Path(__file__).with_name("operation_control_r0009_stage_authority.py"),
)


class BoundaryCaptureError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def capture() -> dict[str, Any]:
    observed = vps.reconcile()
    if observed.get("schema") != (
        "keelaryn.operation-control-r0009-bootstrap-reconcile.v1"
    ):
        raise BoundaryCaptureError("r0009 reconcile schema mismatch")
    if observed.get("candidate") != authority.CANDIDATE:
        raise BoundaryCaptureError("r0009 candidate mismatch")
    if observed.get("production_authorized") is not False:
        raise BoundaryCaptureError("reconcile unexpectedly authorizes production")
    if observed.get("production_mutations_performed") is not False:
        raise BoundaryCaptureError("reconcile claims production mutation")
    if observed.get("drive_mutations_performed") is not False:
        raise BoundaryCaptureError("reconcile claims Drive mutation")
    if observed.get("legacy_hub_authority_scope") != "RUNTIME_SAFETY_ONLY":
        raise BoundaryCaptureError("legacy Hub authority widened")

    boundary = observed.get("production_boundary")
    if not isinstance(boundary, dict):
        raise BoundaryCaptureError("production boundary missing")
    if boundary.get("r0009_snapshot_unit") != "ABSENT":
        raise BoundaryCaptureError("r0009 snapshot unit is not absent")

    services = boundary.get("services", {})
    writer = services.get("writer", {})
    if writer != {"active_state": "INACTIVE", "main_pid": 0}:
        raise BoundaryCaptureError("writer boundary mismatch")

    units = services.get("operation_units", {})
    for name in (
        "keelaryn-operation-transport.service",
        "keelaryn-operation-agent.service",
    ):
        unit = units.get(name, {})
        if (
            unit.get("active_state") != "ACTIVE"
            or unit.get("enabled") != "enabled"
            or unit.get("exact_release_bytes") is not True
        ):
            raise BoundaryCaptureError(
                f"persistent control unit boundary mismatch: {name}"
            )

    hub = boundary.get("legacy_hub", {})
    inhibit = hub.get("mutation_inhibit", {})
    credential = boundary.get("credential", {})

    value = {
        "schema": authority.BOUNDARY_SCHEMA,
        "observed_at_utc": _utc_now(),
        "conclusion": "PASS",
        "production_source_commit": boundary.get(
            "production_source_commit"
        ),
        "control_source_commit": boundary.get("control_source_commit"),
        "legacy_hub_status": hub.get("status"),
        "legacy_hub_transaction_id": hub.get("transaction_id"),
        "selector_role": hub.get("selector_role"),
        "writer": "INACTIVE_MAINPID_0",
        "mutation_inhibit_authority_matches": inhibit.get(
            "authority_matches"
        ),
        "credential_sha256": credential.get("sha256"),
        "legacy_hub_authority_scope": observed.get(
            "legacy_hub_authority_scope"
        ),
        "production_mutations_performed": False,
        "drive_mutations_performed": False,
    }
    return authority.validate_boundary_evidence(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0009-boundary-capture"
    )
    parser.add_argument("command", choices=("capture",))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command != "capture":
            raise BoundaryCaptureError("unsupported command")
        value = capture()
    except (
        BoundaryCaptureError,
        vps.PrepError,
        authority.StageAuthorityError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": (
                        "keelaryn.operation-control-r0009-"
                        "boundary-capture-failure.v1"
                    ),
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                    "production_mutations_performed": False,
                    "drive_mutations_performed": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    print(_canonical(value), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
