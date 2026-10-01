#!/usr/bin/env python3
"""Print a compact, deterministic read-only view of DEVELOPMENT_STATE.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SUMMARY_SCHEMA = "keelaryn.development-preflight.v1"
EXPECTED_STATE_SCHEMA = "keelaryn.development-state.v2"


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def summarize(state: dict[str, Any]) -> dict[str, Any]:
    required = (
        "schema",
        "revision",
        "repository",
        "authoritative_branch",
        "architecture_authority",
        "phase",
        "status",
        "product_level",
        "next_objective",
        "transaction_rules",
        "audit",
        "p0_closure_audit",
        "platform_targets",
    )
    missing = [key for key in required if key not in state]
    if missing:
        raise ValueError("missing required development-state keys: " + ", ".join(missing))
    if state["schema"] != EXPECTED_STATE_SCHEMA:
        raise ValueError(
            f"unsupported development-state schema: {state['schema']!r}"
        )

    objective = require_mapping(state["next_objective"], "next_objective")
    audit = require_mapping(state["audit"], "audit")
    closure = require_mapping(state["p0_closure_audit"], "p0_closure_audit")
    platforms = require_mapping(state["platform_targets"], "platform_targets")
    findings = require_list(audit.get("open_findings", []), "audit.open_findings")

    compact_findings: list[dict[str, Any]] = []
    for index, item in enumerate(findings):
        finding = require_mapping(item, f"audit.open_findings[{index}]")
        compact_findings.append(
            {
                "id": finding.get("id"),
                "severity": finding.get("severity"),
                "status": finding.get("status"),
                "gate_scope": finding.get("gate_scope"),
            }
        )

    completed = require_list(state.get("completed", []), "completed")
    transaction_rules = require_list(state["transaction_rules"], "transaction_rules")

    return {
        "summary_schema": SUMMARY_SCHEMA,
        "state": {
            "schema": state["schema"],
            "revision": state["revision"],
            "repository": state["repository"],
            "authoritative_branch": state["authoritative_branch"],
            "architecture_authority": state["architecture_authority"],
            "phase": state["phase"],
            "status": state["status"],
            "product_level": state["product_level"],
            "completed_count": len(completed),
        },
        "next_objective": {
            "id": objective.get("id"),
            "audit_gate": objective.get("audit_gate"),
        },
        "audit": {
            "current_stage": audit.get("current_stage"),
            "next_stage_locked": audit.get("next_stage_locked"),
            "blocked_next_stage": audit.get("blocked_next_stage"),
            "last_retrospective": audit.get("last_retrospective"),
            "last_retrospective_result": audit.get("last_retrospective_result"),
            "substantive_slice_counter": audit.get("substantive_slice_counter"),
            "open_findings": compact_findings,
        },
        "p0_closure": {
            "status": closure.get("status"),
            "audited_product_head": closure.get("audited_product_head"),
            "qualification_head": closure.get("qualification_head"),
            "qualification_ci_run_id": closure.get("qualification_ci_run_id"),
            "earliest_remaining_autonomous_product_gap": closure.get(
                "earliest_remaining_autonomous_product_gap"
            ),
            "remaining_gates": closure.get("p0_closure_gates_remaining", []),
        },
        "platforms": {
            "first_class_product_targets": platforms.get(
                "first_class_product_targets", []
            ),
            "server_ci_targets": platforms.get("server_ci_targets", []),
            "current_ci": platforms.get("current_ci", []),
            "android_ci_status": platforms.get("android_ci_status"),
        },
        "transaction_rules": transaction_rules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print a compact read-only Keelaryn development-state preflight."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="DEVELOPMENT_STATE.json",
        help="development-state JSON path (default: DEVELOPMENT_STATE.json)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print deterministic JSON instead of one compact line",
    )
    args = parser.parse_args()

    try:
        state_path = Path(args.path)
        state = require_mapping(
            json.loads(state_path.read_text(encoding="utf-8")),
            "development state",
        )
        summary = summarize(state)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"development-preflight: {exc}", file=sys.stderr)
        return 2

    if args.pretty:
        json.dump(summary, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        json.dump(
            summary,
            sys.stdout,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
