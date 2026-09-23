from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


AUTHORITY_PATH = Path(__file__).with_name(
    "operation_control_r0008_stage_authority.py"
)
SPEC = importlib.util.spec_from_file_location(
    "keelaryn_r0008_stage_authority_contract",
    AUTHORITY_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load r0008 stage authority contract")
authority = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = authority
SPEC.loader.exec_module(authority)


class StageAuthorityIssueError(RuntimeError):
    pass


def _hex(value: str, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or re.fullmatch(r"[0-9a-f]+", value) is None
    ):
        raise StageAuthorityIssueError(f"{label} is invalid")
    return value


def render_record(
    *,
    transaction_id: str,
    issuer_checkpoint: str,
    boundary_evidence_path: str,
    boundary_evidence_git_blob: str,
    boundary_evidence_sha256: str,
) -> dict[str, Any]:
    transaction_id = _hex(transaction_id, 32, "transaction_id")
    issuer_checkpoint = _hex(issuer_checkpoint, 40, "issuer_checkpoint")
    boundary_evidence_git_blob = _hex(
        boundary_evidence_git_blob,
        40,
        "boundary_evidence_git_blob",
    )
    boundary_evidence_sha256 = _hex(
        boundary_evidence_sha256,
        64,
        "boundary_evidence_sha256",
    )
    if (
        not isinstance(boundary_evidence_path, str)
        or not boundary_evidence_path.startswith("docs/evidence/")
        or boundary_evidence_path.startswith("/")
        or "\\" in boundary_evidence_path
        or "\x00" in boundary_evidence_path
        or ".." in boundary_evidence_path.split("/")
    ):
        raise StageAuthorityIssueError("boundary_evidence_path is unsafe")

    value = {
        "schema": authority.SCHEMA,
        "transaction_id": transaction_id,
        "scope": authority.SCOPE,
        "candidate": authority.CANDIDATE,
        "source_commit": authority.SOURCE_COMMIT,
        "source_tree": authority.SOURCE_TREE,
        "payload_sha256": authority.PAYLOAD_SHA256,
        "payload_size": authority.PAYLOAD_SIZE,
        "file_count": authority.PAYLOAD_FILE_COUNT,
        "issuer_repository": authority.REPOSITORY,
        "issuer_branch": authority.BRANCH,
        "issuer_checkpoint": issuer_checkpoint,
        "boundary_evidence_commit": issuer_checkpoint,
        "boundary_evidence_path": boundary_evidence_path,
        "boundary_evidence_git_blob": boundary_evidence_git_blob,
        "boundary_evidence_sha256": boundary_evidence_sha256,
        "production_stage_authorized": True,
        "activation_authorized": False,
        "drive_content_mutation_authorized": False,
        "legacy_hub_mutation_authorized": False,
        "writer_mutation_authorized": False,
        "credential_mutation_authorized": False,
    }
    return authority.validate_record(value)


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0008-stage-authority-issuer"
    )
    parser.add_argument("command", choices=("render",))
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--issuer-checkpoint", required=True)
    parser.add_argument("--boundary-evidence-path", required=True)
    parser.add_argument("--boundary-evidence-git-blob", required=True)
    parser.add_argument("--boundary-evidence-sha256", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = render_record(
            transaction_id=args.transaction_id,
            issuer_checkpoint=args.issuer_checkpoint,
            boundary_evidence_path=args.boundary_evidence_path,
            boundary_evidence_git_blob=args.boundary_evidence_git_blob,
            boundary_evidence_sha256=args.boundary_evidence_sha256,
        )
    except (StageAuthorityIssueError, authority.StageAuthorityError) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-r0008-stage-authority-issuer-failure.v1",
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    raw = _canonical(value)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8", newline="\n")
    print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
