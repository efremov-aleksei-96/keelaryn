from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
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


private_input = _load(
    "keelaryn_r0008_control_update_private_input",
    Path(__file__).with_name("operation_control_r0008_private_input.py"),
)
transaction = private_input.transaction
execution = transaction.execution

GATE_REVISION = "operation-control-r0008-control-update-runtime-gate-r0001"
SCHEMA = "keelaryn.operation-control-r0008-control-update-runtime.v1"
FAILURE_SCHEMA = "keelaryn.operation-control-r0008-control-update-runtime-failure.v1"

SCRIPT_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

INSTALL_ROOT = Path("/opt/keelaryn")
RELEASES_ROOT = INSTALL_ROOT / "releases"
PRODUCTION_CURRENT = INSTALL_ROOT / "current"
CONTROL_CURRENT = INSTALL_ROOT / "control-current"
UNIT_DIR = Path("/etc/systemd/system")
CREDENTIAL_PATH = Path(
    "/etc/keelaryn/operation-control/github-operations.env"
)
OPERATION_ROOT = Path("/var/lib/keelaryn/operations")
TRANSPORT_ROOT = Path("/var/lib/keelaryn-operation-transport")
UPDATE_ROOT = Path("/var/lib/keelaryn/operation-control-d0-updates")
WITNESS_ROOT = Path(
    "/var/lib/keelaryn/operation-control/r0008-stage-witness"
)

OLD_SOURCE = "08f2e211f53764590f6ff0f05f86b2de62c14418"
OLD_PAYLOAD = "6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7"
OLD_SIZE = 365052
OLD_COUNT = 190

NEW_SOURCE = "20727893662cde92998d88ecdca730b69633eaaa"
NEW_PAYLOAD = "bc74c0e5b7eba90465fb8d59c5bb9a619ebc1f2c737c06fbf357ae062c5b374d"
NEW_SIZE = 428403
NEW_COUNT = 217

PRODUCTION_SOURCE = "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
CREDENTIAL_SHA256 = "7002ed72a223dd7fc860451c53a4ec8f264d14f7144000559a295522b7cbe928"
CONTROL_UPDATE_TRANSACTION_ID = "83e20aeecd4ecd7a8288816065fa700ab3e99b8017177df215e18e03695d4e58"

TRANSACTION_ID = private_input.TRANSACTION_ID


class ControlUpdateRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _frozen_release_identity(
    materializer: Any,
    source: str,
    payload: str,
    size: int,
    count: int,
) -> dict[str, Any]:
    release = RELEASES_ROOT / source
    try:
        value = materializer.verify_release_directory(
            release,
            expected_source_commit=source,
            expected_payload_sha256=payload,
        )
    except Exception as exc:
        raise ControlUpdateRuntimeError(
            "RELEASE_IDENTITY_INVALID",
            f"release identity invalid: {source}",
        ) from exc
    observed = {
        "source_commit": value.get("source_commit"),
        "payload_sha256": value.get("payload_sha256"),
        "payload_size": value.get("payload_size"),
        "file_count": value.get("file_count"),
    }
    expected = {
        "source_commit": source,
        "payload_sha256": payload,
        "payload_size": size,
        "file_count": count,
    }
    if observed != expected:
        raise ControlUpdateRuntimeError(
            "RELEASE_IDENTITY_INVALID",
            f"release metadata mismatch: {source}",
        )
    return observed


def _load_frozen_updater(materializer: Any):
    _frozen_release_identity(
        materializer,
        NEW_SOURCE,
        NEW_PAYLOAD,
        NEW_SIZE,
        NEW_COUNT,
    )
    deploy = (
        RELEASES_ROOT
        / NEW_SOURCE
        / "deploy"
        / "zero-based-vps"
    )
    path = deploy / "operation_control_d0_update.py"
    sibling_materializer = deploy / "materialize_payload.py"

    # The frozen updater's legacy module intentionally imports
    # "materialize_payload" by its canonical sibling module name. Load that
    # exact staged-release sibling explicitly and expose the frozen deploy
    # directory only for the duration of the import. Never let an already
    # cached dev module satisfy the frozen updater dependency.
    previous_path = list(sys.path)
    marker = object()
    previous_materializer = sys.modules.get(
        "materialize_payload",
        marker,
    )
    try:
        _load(
            "materialize_payload",
            sibling_materializer,
        )
        sys.path.insert(0, str(deploy))
        return _load(
            "keelaryn_r0008_control_update_frozen",
            path,
        )
    except Exception as exc:
        raise ControlUpdateRuntimeError(
            "FROZEN_UPDATER_IMPORT_FAILED",
            "cannot load exact frozen r0008 control updater",
        ) from exc
    finally:
        sys.path[:] = previous_path
        if previous_materializer is marker:
            sys.modules.pop("materialize_payload", None)
        else:
            sys.modules["materialize_payload"] = previous_materializer


def _verify_stage_witnesses(
    repo: Path,
    issued: Any,
) -> dict[str, Any]:
    prepared_path, completed_path = execution._witness_paths(
        WITNESS_ROOT,
        TRANSACTION_ID,
    )
    prepared = execution._read_canonical(
        prepared_path,
        "stage PREPARED witness",
    )
    completed = execution._read_canonical(
        completed_path,
        "stage COMPLETED witness",
    )
    provenance = issued.provenance
    evidence = execution._authority_evidence(repo, issued)
    expected_live = {
        "production_source_commit": PRODUCTION_SOURCE,
        "control_source_commit": OLD_SOURCE,
        "legacy_hub_status": "PREPARED",
        "legacy_hub_transaction_id": "61a2bfb65c9a47d088a76eee0df89d14",
        "selector_role": "OLD",
        "writer": "INACTIVE_MAINPID_0",
        "mutation_inhibit_authority_matches": True,
        "credential_sha256": CREDENTIAL_SHA256,
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
    }
    required_prepared = {
        "schema": execution.PREPARED_SCHEMA,
        "transaction_id": TRANSACTION_ID,
        "candidate": execution.authority.CANDIDATE,
        "source_commit": NEW_SOURCE,
        "source_tree": execution.authority.SOURCE_TREE,
        "payload_sha256": NEW_PAYLOAD,
        "payload_size": NEW_SIZE,
        "file_count": NEW_COUNT,
        "authority_commit": provenance["authority_commit"],
        "authority_path": provenance["authority_path"],
        "authority_git_blob": provenance["authority_git_blob"],
        "authority_sha256": provenance["authority_sha256"],
        "issuer_checkpoint": provenance["authority_parent_checkpoint"],
        "boundary_evidence_path": provenance["boundary_evidence_path"],
        "boundary_evidence_git_blob": provenance["boundary_evidence_git_blob"],
        "boundary_evidence_sha256": provenance["boundary_evidence_sha256"],
        "boundary_observed_at_utc": evidence["observed_at_utc"],
        "scope": execution.authority.SCOPE,
        "activation_authorized": False,
    }
    for key, expected in required_prepared.items():
        if prepared.get(key) != expected:
            raise ControlUpdateRuntimeError(
                "STAGE_WITNESS_INVALID",
                f"stage PREPARED field mismatch: {key}",
            )
    if prepared.get("live_projection") != expected_live:
        raise ControlUpdateRuntimeError(
            "STAGE_WITNESS_INVALID",
            "stage PREPARED live projection mismatch",
        )
    identity = prepared.get("payload_identity")
    if not isinstance(identity, dict):
        raise ControlUpdateRuntimeError(
            "STAGE_WITNESS_INVALID",
            "stage PREPARED payload identity missing",
        )
    if {
        "source_commit": identity.get("source_commit"),
        "payload_sha256": identity.get("payload_sha256"),
        "payload_size": identity.get("payload_size"),
        "file_count": identity.get("file_count"),
    } != {
        "source_commit": NEW_SOURCE,
        "payload_sha256": NEW_PAYLOAD,
        "payload_size": NEW_SIZE,
        "file_count": NEW_COUNT,
    }:
        raise ControlUpdateRuntimeError(
            "STAGE_WITNESS_INVALID",
            "stage PREPARED payload identity mismatch",
        )

    if completed.get("schema") != execution.COMPLETED_SCHEMA:
        raise ControlUpdateRuntimeError(
            "STAGE_WITNESS_INVALID",
            "stage COMPLETED schema mismatch",
        )
    if completed.get("transaction_id") != TRANSACTION_ID:
        raise ControlUpdateRuntimeError(
            "STAGE_WITNESS_INVALID",
            "stage COMPLETED transaction mismatch",
        )
    if completed.get("prepared_sha256") != _sha(_canonical(prepared)):
        raise ControlUpdateRuntimeError(
            "STAGE_WITNESS_INVALID",
            "stage COMPLETED does not bind exact PREPARED",
        )
    exact_completed = {
        "authority_commit": provenance["authority_commit"],
        "authority_git_blob": provenance["authority_git_blob"],
        "source_commit": NEW_SOURCE,
        "payload_sha256": NEW_PAYLOAD,
        "release_state": "STAGED_EXACT",
        "post_reconcile": "PASS",
        "activation_authorized": False,
        "release_deletion_allowed": False,
        "blind_retry_allowed": False,
    }
    for key, expected in exact_completed.items():
        if completed.get(key) != expected:
            raise ControlUpdateRuntimeError(
                "STAGE_WITNESS_INVALID",
                f"stage COMPLETED field mismatch: {key}",
            )
    return {
        "prepared_sha256": _sha(_canonical(prepared)),
        "stage_state": completed.get("stage_state"),
        "release_state": completed["release_state"],
        "post_reconcile": completed["post_reconcile"],
    }


def _expected_prepared(
    updater: Any,
    *,
    production_target: str,
    credential_sha: str,
) -> tuple[str, dict[str, Any]]:
    old_release = RELEASES_ROOT / OLD_SOURCE
    new_release = RELEASES_ROOT / NEW_SOURCE
    old_static = updater._optional_unit_bytes(
        old_release,
        updater.STATIC_UNIT,
    )
    new_static = updater.legacy._unit_bytes(
        new_release,
        updater.STATIC_UNIT,
    )
    digest = updater._transaction_digest(
        old_source=OLD_SOURCE,
        old_payload=OLD_PAYLOAD,
        new_source=NEW_SOURCE,
        new_payload=NEW_PAYLOAD,
        production_target=production_target,
    )
    if digest != CONTROL_UPDATE_TRANSACTION_ID:
        raise ControlUpdateRuntimeError(
            "CONTROL_UPDATE_TRANSACTION_ID_MISMATCH",
            "derived control-update transaction identity is not canonical",
        )
    value = {
        "schema": updater.PREPARED_SCHEMA,
        "transaction_id": digest,
        "old_source_commit": OLD_SOURCE,
        "old_payload_sha256": OLD_PAYLOAD,
        "new_source_commit": NEW_SOURCE,
        "new_payload_sha256": NEW_PAYLOAD,
        "production_current_target": production_target,
        "credential_sha256": credential_sha,
        "old_unit_sha256": {
            name: _sha(
                updater.legacy._unit_bytes(
                    old_release,
                    name,
                )
            )
            for name in updater.PERSISTENT_UNITS
        },
        "new_unit_sha256": {
            name: _sha(
                updater.legacy._unit_bytes(
                    new_release,
                    name,
                )
            )
            for name in updater.PERSISTENT_UNITS
        },
        "static_unit": updater.STATIC_UNIT,
        "old_static_unit_sha256": (
            None if old_static is None else _sha(old_static)
        ),
        "new_static_unit_sha256": _sha(new_static),
        "remote_allowlist": [
            "PRODUCTION_SNAPSHOT",
            "RUNTIME_SELFTEST",
        ],
        "remote_mutation_handlers": 0,
    }
    return digest, value


def _completed_expected(updater: Any, digest: str) -> dict[str, Any]:
    return {
        "schema": updater.COMPLETED_SCHEMA,
        "transaction_id": digest,
        "production_current_unchanged": True,
        "control_current": "SUCCESSOR",
        "persistent_services": "ACTIVE_STABLE",
        "static_unit": "STATIC_INACTIVE",
        "remote_mutation_handlers": "ABSENT",
        "credential_unchanged": True,
    }


def _rolled_exact(
    updater: Any,
    value: dict[str, Any],
    digest: str,
) -> bool:
    return (
        value.get("schema") == updater.ROLLED_BACK_SCHEMA
        and value.get("transaction_id") == digest
        and value.get("production_current_unchanged") is True
        and value.get("control_current") == "PREDECESSOR"
        and value.get("persistent_services") == "ACTIVE_STABLE"
        and value.get("credential_unchanged") is True
        and isinstance(value.get("failure_class"), str)
        and bool(value["failure_class"])
    )


def _inspect_transaction(
    updater: Any,
    *,
    digest: str,
    prepared_expected: dict[str, Any],
    live: str,
) -> dict[str, Any]:
    root_exists = UPDATE_ROOT.exists() or UPDATE_ROOT.is_symlink()
    if not root_exists:
        if live == "NEW_EXACT":
            raise ControlUpdateRuntimeError(
                "UNATTRIBUTED_SUCCESSOR_STATE",
                "successor control boundary exists without update authority",
            )
        return {
            "state": "NEW",
            "update_root_state": "ABSENT",
            "transaction_id": digest,
        }

    root = updater.legacy._owned_dir(
        UPDATE_ROOT,
        "control update root",
        exact_mode=0o700,
    )
    updater.legacy._assert_no_foreign_incomplete(root, digest)
    tx, prepared_path, completed_path, rolled_path = (
        updater.legacy._transaction_paths(root, digest)
    )
    tx_exists = tx.exists() or tx.is_symlink()
    if not tx_exists:
        if live == "NEW_EXACT":
            raise ControlUpdateRuntimeError(
                "UNATTRIBUTED_SUCCESSOR_STATE",
                "successor control boundary exists without update transaction",
            )
        return {
            "state": "NEW",
            "update_root_state": "PRESENT",
            "transaction_id": digest,
        }

    updater.legacy._owned_dir(
        tx,
        "D0 control update transaction",
        exact_mode=0o700,
    )
    prepared_exists = prepared_path.exists() or prepared_path.is_symlink()
    completed_exists = completed_path.exists() or completed_path.is_symlink()
    rolled_exists = rolled_path.exists() or rolled_path.is_symlink()

    if rolled_exists:
        rolled = updater.legacy._json_private(
            rolled_path,
            "rolled-back D0 control authority",
        )
        if (
            not prepared_exists
            or completed_exists
            or live != "OLD_EXACT"
            or not _rolled_exact(updater, rolled, digest)
        ):
            raise ControlUpdateRuntimeError(
                "CONTROL_UPDATE_TRANSACTION_INVALID",
                "rolled-back transaction conflicts with live state",
            )
        prepared = updater.legacy._json_private(
            prepared_path,
            "prepared D0 control authority",
        )
        if prepared != prepared_expected:
            raise ControlUpdateRuntimeError(
                "CONTROL_UPDATE_TRANSACTION_INVALID",
                "rolled-back transaction PREPARED mismatch",
            )
        return {
            "state": "ROLLED_BACK_EXACT",
            "update_root_state": "PRESENT",
            "transaction_id": digest,
        }

    if completed_exists:
        if not prepared_exists:
            raise ControlUpdateRuntimeError(
                "CONTROL_UPDATE_TRANSACTION_INVALID",
                "COMPLETED exists without PREPARED",
            )
        prepared = updater.legacy._json_private(
            prepared_path,
            "prepared D0 control authority",
        )
        completed = updater.legacy._json_private(
            completed_path,
            "completed D0 control authority",
        )
        if (
            prepared != prepared_expected
            or completed != _completed_expected(updater, digest)
            or live != "NEW_EXACT"
        ):
            raise ControlUpdateRuntimeError(
                "CONTROL_UPDATE_TRANSACTION_INVALID",
                "completed transaction conflicts with exact successor state",
            )
        return {
            "state": "COMPLETED_EXACT",
            "update_root_state": "PRESENT",
            "transaction_id": digest,
        }

    if prepared_exists:
        prepared = updater.legacy._json_private(
            prepared_path,
            "prepared D0 control authority",
        )
        if prepared != prepared_expected:
            raise ControlUpdateRuntimeError(
                "CONTROL_UPDATE_TRANSACTION_INVALID",
                "PREPARED authority mismatch",
            )
        if live == "OLD_EXACT":
            state = "PREPARED_OLD_EXACT"
        elif live == "NEW_EXACT":
            state = "PREPARED_NEW_EXACT"
        else:
            state = "PREPARED_PARTIAL"
        return {
            "state": state,
            "update_root_state": "PRESENT",
            "transaction_id": digest,
        }

    if any(tx.iterdir()):
        raise ControlUpdateRuntimeError(
            "CONTROL_UPDATE_TRANSACTION_INVALID",
            "orphan transaction contains unexpected material",
        )
    if live == "NEW_EXACT":
        raise ControlUpdateRuntimeError(
            "UNATTRIBUTED_SUCCESSOR_STATE",
            "successor boundary exists with empty transaction",
        )
    return {
        "state": "EMPTY_TRANSACTION_DIR",
        "update_root_state": "PRESENT",
        "transaction_id": digest,
    }


def _context() -> dict[str, Any]:
    repo = SCRIPT_REPOSITORY_ROOT.resolve()
    branch = private_input._verify_repository(repo)
    issued = private_input._resolve_issued(repo)

    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0008-control-update-reconcile-"
    ) as td:
        _, materializer = private_input._load_frozen_materializer(Path(td))
        old_identity = _frozen_release_identity(
            materializer,
            OLD_SOURCE,
            OLD_PAYLOAD,
            OLD_SIZE,
            OLD_COUNT,
        )
        new_identity = _frozen_release_identity(
            materializer,
            NEW_SOURCE,
            NEW_PAYLOAD,
            NEW_SIZE,
            NEW_COUNT,
        )
        updater = _load_frozen_updater(materializer)

    stage_witness = _verify_stage_witnesses(repo, issued)

    updater.legacy._require_root()
    updater.legacy._owned_dir(
        INSTALL_ROOT,
        "install root",
    )
    updater.legacy._owned_dir(
        RELEASES_ROOT,
        "release root",
    )
    unit_dir = updater.legacy._owned_dir(
        UNIT_DIR,
        "systemd unit directory",
    )

    production_target = updater.legacy._production_target(
        PRODUCTION_CURRENT
    )
    if production_target != f"releases/{PRODUCTION_SOURCE}":
        raise ControlUpdateRuntimeError(
            "PRODUCTION_CURRENT_CHANGED",
            "production current no longer selects exact production source",
        )

    credential_raw = updater.legacy._regular(
        CREDENTIAL_PATH,
        "GitHub operations credential",
        mode=0o600,
    ).read_bytes()
    credential_sha = _sha(credential_raw)
    if credential_sha != CREDENTIAL_SHA256:
        raise ControlUpdateRuntimeError(
            "CREDENTIAL_IDENTITY_CHANGED",
            "GitHub operations credential identity changed",
        )

    updater.legacy._operation_runtime_idle(OPERATION_ROOT)
    updater.legacy._transport_inbox_idle(TRANSPORT_ROOT)

    old_release = RELEASES_ROOT / OLD_SOURCE
    new_release = RELEASES_ROOT / NEW_SOURCE
    updater._verify_read_only_agent_contract(new_release)
    updater._verify_snapshot_unit_policy(
        updater.legacy._unit_bytes(
            new_release,
            updater.STATIC_UNIT,
        )
    )
    live = updater._live_boundary(
        old_release=old_release,
        new_release=new_release,
        old_source=OLD_SOURCE,
        new_source=NEW_SOURCE,
        control_current=CONTROL_CURRENT,
        unit_dir=unit_dir,
    )
    if live == "OLD_EXACT":
        updater._verify_persistent_services(
            active_probe=updater.legacy._is_active,
            enabled_probe=updater.legacy._enabled_state,
            restart_probe=updater.legacy._restart_count,
        )
    elif live == "NEW_EXACT":
        updater._verify_services(
            active_probe=updater.legacy._is_active,
            enabled_probe=updater.legacy._enabled_state,
            restart_probe=updater.legacy._restart_count,
        )
    else:
        raise ControlUpdateRuntimeError(
            "CONTROL_BOUNDARY_PARTIAL",
            "control boundary is neither exact predecessor nor exact successor",
        )

    digest, prepared_expected = _expected_prepared(
        updater,
        production_target=production_target,
        credential_sha=credential_sha,
    )
    tx = _inspect_transaction(
        updater,
        digest=digest,
        prepared_expected=prepared_expected,
        live=live,
    )
    return {
        "repo": repo,
        "branch": branch,
        "issued": issued,
        "updater": updater,
        "old_identity": old_identity,
        "new_identity": new_identity,
        "stage_witness": stage_witness,
        "production_target": production_target,
        "credential_sha256": credential_sha,
        "live": live,
        "transaction": tx,
    }


def _public(
    *,
    command: str,
    ctx: dict[str, Any],
    result: dict[str, Any] | None = None,
    mutation_performed: bool = False,
) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "gate_revision": GATE_REVISION,
        "command": command,
        "branch_tip": ctx["branch"]["expected"],
        "stage_transaction_id": TRANSACTION_ID,
        "stage_witness": ctx["stage_witness"],
        "old_release": ctx["old_identity"],
        "new_release": ctx["new_identity"],
        "production_current": ctx["production_target"],
        "credential_sha256": ctx["credential_sha256"],
        "control_boundary": ctx["live"],
        "control_update": ctx["transaction"],
        "control_update_mutation_performed": mutation_performed,
        "production_current_mutation_performed": False,
        "legacy_hub_mutation_performed": False,
        "credential_mutation_performed": False,
        "drive_mutations_performed": False,
    }
    if result is not None:
        value["result"] = result
    return value


def reconcile() -> dict[str, Any]:
    return _public(command="reconcile", ctx=_context())


def update_once() -> dict[str, Any]:
    before = _context()
    state = before["transaction"]["state"]
    if state == "ROLLED_BACK_EXACT":
        raise ControlUpdateRuntimeError(
            "ROLLED_BACK_RETRY_FORBIDDEN",
            "this exact control update previously rolled back",
        )
    if state == "COMPLETED_EXACT":
        return _public(
            command="update",
            ctx=before,
            result={
                "state": "ALREADY_COMPLETED_EXACT",
                "recovery_performed": False,
            },
            mutation_performed=False,
        )
    if state not in {
        "NEW",
        "EMPTY_TRANSACTION_DIR",
        "PREPARED_OLD_EXACT",
        "PREPARED_NEW_EXACT",
    }:
        raise ControlUpdateRuntimeError(
            "RECONCILE_REQUIRED",
            f"control update state is not safely actionable: {state}",
        )

    branch2 = private_input._verify_repository(
        before["repo"],
        before["branch"]["expected"],
    )
    if branch2 != before["branch"]:
        raise ControlUpdateRuntimeError(
            "MUTATION_BOUNDARY_DRIFT",
            "repository branch identity changed before control update",
        )

    updater = before["updater"]
    result = updater.update_d0_control_plane(
        install_root=INSTALL_ROOT,
        unit_dir=UNIT_DIR,
        credential_path=CREDENTIAL_PATH,
        operation_root=OPERATION_ROOT,
        transport_root=TRANSPORT_ROOT,
        update_root=UPDATE_ROOT,
        expected_old_source_commit=OLD_SOURCE,
        expected_old_payload_sha256=OLD_PAYLOAD,
        expected_new_source_commit=NEW_SOURCE,
        expected_new_payload_sha256=NEW_PAYLOAD,
    )

    after = _context()
    if (
        after["live"] != "NEW_EXACT"
        or after["transaction"]["state"] != "COMPLETED_EXACT"
        or after["production_target"] != before["production_target"]
        or after["credential_sha256"] != before["credential_sha256"]
    ):
        raise ControlUpdateRuntimeError(
            "POST_UPDATE_RECONCILE_FAILED",
            "control update did not reconcile to exact successor boundary",
        )
    return _public(
        command="update",
        ctx=after,
        result=result,
        mutation_performed=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0008-control-update-runtime"
    )
    parser.add_argument("command", choices=("reconcile", "update"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = (
            reconcile()
            if args.command == "reconcile"
            else update_once()
        )
    except (
        ControlUpdateRuntimeError,
        private_input.PrivateInputError,
        execution.StageExecutionError,
        execution.authority.StageAuthorityError,
        OSError,
    ) as exc:
        update_command = args.command == "update"
        print(
            json.dumps(
                {
                    "schema": FAILURE_SCHEMA,
                    "command": args.command,
                    "error_code": getattr(
                        exc,
                        "code",
                        type(exc).__name__,
                    ),
                    "message": str(exc),
                    "reconcile_required": update_command,
                    "control_update_mutation_performed": (
                        None if update_command else False
                    ),
                    "production_current_mutation_performed": False,
                    "legacy_hub_mutation_performed": False,
                    "credential_mutation_performed": (
                        None if update_command else False
                    ),
                    "drive_mutations_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2

    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
