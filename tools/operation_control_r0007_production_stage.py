from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


STAGE_PATH = Path(__file__).with_name("operation_control_r0007_stage.py")
STAGE_SPEC = importlib.util.spec_from_file_location(
    "keelaryn_r0007_stage_for_production_prep",
    STAGE_PATH,
)
if STAGE_SPEC is None or STAGE_SPEC.loader is None:
    raise RuntimeError("cannot load r0007 stage qualification primitive")
stage = importlib.util.module_from_spec(STAGE_SPEC)
sys.modules[STAGE_SPEC.name] = stage
STAGE_SPEC.loader.exec_module(stage)

PREP_PATH = Path(__file__).with_name("operation_control_r0007_vps.py")
PREP_SPEC = importlib.util.spec_from_file_location(
    "keelaryn_r0007_vps_for_production_stage",
    PREP_PATH,
)
if PREP_SPEC is None or PREP_SPEC.loader is None:
    raise RuntimeError("cannot load r0007 live-boundary primitive")
prep = importlib.util.module_from_spec(PREP_SPEC)
sys.modules[PREP_SPEC.name] = prep
PREP_SPEC.loader.exec_module(prep)


GATE_REVISION = "operation-control-r0007-production-stage-prep-r0001"
AUTH_SCHEMA = "keelaryn.operation-control-r0007-production-stage-authorization.v1"
RESULT_SCHEMA = "keelaryn.operation-control-r0007-production-stage-result.v1"

CANDIDATE = stage.CANDIDATE
SOURCE_COMMIT = stage.SOURCE_COMMIT
SOURCE_TREE = stage.SOURCE_TREE
PAYLOAD_SHA256 = stage.PAYLOAD_SHA256
PAYLOAD_SIZE = stage.PAYLOAD_SIZE
PAYLOAD_FILE_COUNT = stage.PAYLOAD_FILE_COUNT
MATERIALIZER_GIT_BLOB = stage.MATERIALIZER_GIT_BLOB

SCOPE = "R0007_RELEASE_STAGE_ONLY"


class ProductionStagePrepError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _git_blob_sha(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def _load_exact_materializer(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ProductionStagePrepError(
            "MATERIALIZER_NOT_REGULAR",
            "qualified materializer path is missing/not regular",
        )
    raw = path.read_bytes()
    if _git_blob_sha(raw) != MATERIALIZER_GIT_BLOB:
        raise ProductionStagePrepError(
            "MATERIALIZER_IDENTITY_MISMATCH",
            "materializer Git blob does not match qualified identity",
        )
    return stage._load_materializer(path)


def production_authorization_template() -> dict[str, Any]:
    return {
        "schema": AUTH_SCHEMA,
        "scope": SCOPE,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
        "production_stage_authorized": True,
        "activation_authorized": False,
        "drive_content_mutation_authorized": False,
        "legacy_hub_mutation_authorized": False,
        "writer_mutation_authorized": False,
        "credential_mutation_authorized": False,
    }


def validate_authorization(value: Any) -> dict[str, Any]:
    expected = production_authorization_template()
    if not isinstance(value, dict):
        raise ProductionStagePrepError(
            "AUTHORIZATION_INVALID",
            "production stage authorization must be an object",
        )
    if value != expected:
        raise ProductionStagePrepError(
            "AUTHORIZATION_INVALID",
            "production stage authorization is not the exact release-stage-only authority",
        )
    return dict(expected)


def live_boundary_probe() -> dict[str, Any]:
    value = prep.reconcile()
    if value.get("production_mutations_performed") is not False:
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_INVALID",
            "live boundary reconcile claims production mutation",
        )
    if value.get("drive_mutations_performed") is not False:
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_INVALID",
            "live boundary reconcile claims Drive mutation",
        )
    if value.get("legacy_hub_authority_scope") != "RUNTIME_SAFETY_ONLY":
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_INVALID",
            "legacy Hub authority scope widened",
        )
    boundary = value.get("production_boundary")
    if not isinstance(boundary, dict):
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_INVALID",
            "live production boundary missing",
        )
    return boundary


def _snapshot(probe: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    value = probe()
    if not isinstance(value, dict):
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_INVALID",
            "boundary probe did not return object",
        )
    try:
        return json.loads(_canonical(value).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_INVALID",
            "boundary probe output is not canonicalizable",
        ) from exc


def _same(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _canonical(left) == _canonical(right)


def _sanitize_boundary(boundary: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "production_source_commit",
        "control_source_commit",
        "control_release",
        "services",
        "legacy_hub",
        "credential",
        "r0007_snapshot_unit",
    }
    value = {key: boundary[key] for key in allowed if key in boundary}
    hub = value.get("legacy_hub")
    if isinstance(hub, dict):
        forbidden = {"old_hub_root_id", "new_hub_root_id"}
        if forbidden.intersection(hub):
            raise ProductionStagePrepError(
                "BOUNDARY_SECRET_LEAK",
                "raw legacy Hub identifiers are forbidden in stage evidence",
            )
    credential = value.get("credential")
    if isinstance(credential, dict) and any(
        "token" in key.lower() for key in credential
    ):
        raise ProductionStagePrepError(
            "BOUNDARY_SECRET_LEAK",
            "credential token material is forbidden in stage evidence",
        )
    return value


def _result(
    *,
    stage_result: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    authorization: dict[str, Any],
) -> dict[str, Any]:
    unchanged = _same(before, after)
    state = stage_result.get("state")
    staged_exact_states = {
        "STAGED_EXACT",
        "ALREADY_STAGED_EXACT",
        "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY",
        "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED",
    }
    if state not in staged_exact_states:
        raise ProductionStagePrepError(
            "STAGE_RESULT_INVALID",
            "stage primitive did not return a recognized exact-release state",
        )
    requires_reconcile = bool(stage_result.get("requires_reconcile")) or not unchanged
    return {
        "schema": RESULT_SCHEMA,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "authorization_scope": authorization["scope"],
        "state": state,
        "release_publication_performed": bool(
            stage_result.get("release_publication_performed")
        ),
        "runtime_anchors_unchanged": unchanged,
        "requires_reconcile": requires_reconcile,
        "activation_allowed": False,
        "release_deletion_allowed": False,
        "blind_retry_allowed": False,
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
        "boundary_before": _sanitize_boundary(before),
        "boundary_after": _sanitize_boundary(after),
    }


def execute_authorized_stage(
    *,
    payload: Path,
    releases_root: Path,
    materializer: Any,
    authorization: Any,
    boundary_probe: Callable[[], dict[str, Any]] = live_boundary_probe,
    materialize_call: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    auth = validate_authorization(authorization)

    # First fresh two-pass live check before any filesystem classification/write.
    first = _snapshot(boundary_probe)
    second = _snapshot(boundary_probe)
    if not _same(first, second):
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_DRIFT_PRECHECK",
            "live runtime boundary changed during fresh precheck",
        )

    prestate = stage.reconcile_stage(releases_root, materializer)
    if prestate["state"] in {
        "FOREIGN_OR_PARTIAL_DESTINATION",
        "RECOVERY_REQUIRED",
        "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED",
    }:
        raise ProductionStagePrepError(
            prestate["state"],
            "successor release state requires reconciliation before production stage",
        )

    # stage_release revalidates payload, filesystem state and boundary again
    # immediately at its own mutation boundary.
    try:
        stage_result = stage.stage_release(
            payload=payload,
            releases_root=releases_root,
            materializer=materializer,
            boundary_probe=boundary_probe,
            materialize_call=materialize_call,
        )
    except stage.StageError as exc:
        raise ProductionStagePrepError(exc.code, str(exc)) from exc

    # Mandatory post-publication read-only reconcile of all non-release anchors.
    after_first = _snapshot(boundary_probe)
    after_second = _snapshot(boundary_probe)
    if not _same(after_first, after_second):
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_DRIFT_POSTCHECK",
            "post-publication runtime boundary is not stable",
        )

    value = _result(
        stage_result=stage_result,
        before=second,
        after=after_second,
        authorization=auth,
    )
    observed = stage.reconcile_stage(releases_root, materializer)
    if observed["state"] != "STAGED_EXACT":
        raise ProductionStagePrepError(
            "POST_STAGE_RELEASE_NOT_EXACT",
            "production-stage result is not reconciled to exact immutable release",
        )
    return value


def reconcile_production_stage(
    *,
    releases_root: Path,
    materializer: Any,
    boundary_probe: Callable[[], dict[str, Any]] = live_boundary_probe,
) -> dict[str, Any]:
    first = _snapshot(boundary_probe)
    second = _snapshot(boundary_probe)
    if not _same(first, second):
        raise ProductionStagePrepError(
            "LIVE_BOUNDARY_DRIFT_RECONCILE",
            "runtime boundary changed during production-stage reconcile",
        )
    release = stage.reconcile_stage(releases_root, materializer)
    return {
        "schema": "keelaryn.operation-control-r0007-production-stage-reconcile.v1",
        "candidate": CANDIDATE,
        "release": release,
        "runtime_boundary": _sanitize_boundary(second),
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
        "production_mutations_performed": False,
        "drive_mutations_performed": False,
        "activation_allowed": False,
    }


class _SequenceProbe:
    def __init__(self, values: list[dict[str, Any]]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> dict[str, Any]:
        if self.index >= len(self.values):
            return self.values[-1]
        value = self.values[self.index]
        self.index += 1
        return value


def _qualification_boundary() -> dict[str, Any]:
    return {
        "production_source_commit": prep.PRODUCTION_SOURCE,
        "control_source_commit": prep.PREDECESSOR_SOURCE_COMMIT,
        "control_release": {
            "exact": True,
            "payload_sha256": prep.PREDECESSOR_PAYLOAD_SHA256,
            "payload_size": prep.PREDECESSOR_PAYLOAD_SIZE,
            "file_count": prep.PREDECESSOR_PAYLOAD_FILE_COUNT,
        },
        "services": {
            "writer": {"active_state": "INACTIVE", "main_pid": 0},
            "operation_units": {
                "keelaryn-operation-agent.service": {
                    "active_state": "ACTIVE",
                    "enabled": "enabled",
                    "exact_release_bytes": True,
                },
                "keelaryn-operation-transport.service": {
                    "active_state": "ACTIVE",
                    "enabled": "enabled",
                    "exact_release_bytes": True,
                },
            },
        },
        "legacy_hub": {
            "status": "PREPARED",
            "transaction_id": prep.HUB_TRANSACTION_ID,
            "active_transaction_sha256": prep.ACTIVE_TRANSACTION_SHA256,
            "selector_role": "OLD",
            "old_selector_identity_sha256": prep.OLD_SELECTOR_IDENTITY_SHA256,
            "new_selector_identity_sha256": prep.NEW_SELECTOR_IDENTITY_SHA256,
            "mutation_inhibit": {
                "state": "PRESENT",
                "authority_matches": True,
            },
            "authority_scope": "RUNTIME_SAFETY_ONLY",
        },
        "credential": {
            "sha256": prep.CREDENTIAL_SHA256,
            "bootstrap_receipt_exact": True,
        },
        "r0007_snapshot_unit": "ABSENT",
    }


def qualify(repository_root: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    recorded = prep._recorded_boundary(repository_root)
    authorization = production_authorization_template()

    with tempfile.TemporaryDirectory(
        prefix="keelaryn-r0007-production-stage-prep-"
    ) as td:
        work = Path(td)
        source = prep._checkout_frozen(work)
        payload_identity = prep._rebuild_frozen(source, work)
        payload = work / "first.tar.gz"
        materializer_path = (
            source
            / "deploy"
            / "zero-based-vps"
            / "materialize_payload.py"
        )
        materializer = _load_exact_materializer(materializer_path)

        boundary = _qualification_boundary()
        changed = json.loads(_canonical(boundary).decode("utf-8"))
        changed["services"]["writer"] = {
            "active_state": "ACTIVE",
            "main_pid": 999,
        }

        scenarios: dict[str, str] = {}

        # A. Missing/widened authorization blocks before publication.
        auth_root = work / "authorization"
        auth_root.mkdir()
        auth_releases = auth_root / "releases"
        auth_releases.mkdir()
        auth_payload = auth_root / "payload.tar.gz"
        auth_payload.write_bytes(payload.read_bytes())
        bad = dict(authorization)
        bad["activation_authorized"] = True
        try:
            execute_authorized_stage(
                payload=auth_payload,
                releases_root=auth_releases,
                materializer=materializer,
                authorization=bad,
                boundary_probe=_SequenceProbe([boundary, boundary]),
            )
        except ProductionStagePrepError as exc:
            if exc.code != "AUTHORIZATION_INVALID":
                raise
        else:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "widened authorization was accepted",
            )
        if stage.reconcile_stage(auth_releases, materializer)["state"] != "NOT_STAGED":
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "authorization failure still published release",
            )
        scenarios["authorization_scope"] = "EXACT_STAGE_ONLY_FAIL_CLOSED"

        # B. Exact authorization publishes once and preserves anchors.
        exact_root = work / "exact"
        exact_root.mkdir()
        exact_releases = exact_root / "releases"
        exact_releases.mkdir()
        exact_payload = exact_root / "payload.tar.gz"
        exact_payload.write_bytes(payload.read_bytes())
        exact = execute_authorized_stage(
            payload=exact_payload,
            releases_root=exact_releases,
            materializer=materializer,
            authorization=authorization,
            boundary_probe=_SequenceProbe([boundary] * 8),
        )
        if exact["state"] != "STAGED_EXACT":
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "exact authorization did not stage exact release",
            )
        if exact["runtime_anchors_unchanged"] is not True:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "exact stage changed non-release runtime anchors",
            )
        scenarios["exact_authorized_stage"] = "STAGED_EXACT_ANCHORS_UNCHANGED"

        # C. Exact replay is idempotent and does not invoke materializer.
        def forbidden_materialize(*args, **kwargs):
            raise AssertionError("idempotent production replay attempted publication")

        replay = execute_authorized_stage(
            payload=exact_payload,
            releases_root=exact_releases,
            materializer=materializer,
            authorization=authorization,
            boundary_probe=_SequenceProbe([boundary] * 8),
            materialize_call=forbidden_materialize,
        )
        if replay["state"] != "ALREADY_STAGED_EXACT":
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "exact replay is not idempotent",
            )
        scenarios["exact_replay"] = "ALREADY_STAGED_EXACT_NO_PUBLICATION"

        # D. Foreign destination fails before stage primitive can write.
        foreign_root = work / "foreign"
        foreign_root.mkdir()
        foreign_releases = foreign_root / "releases"
        foreign_releases.mkdir()
        foreign_payload = foreign_root / "payload.tar.gz"
        foreign_payload.write_bytes(payload.read_bytes())
        destination = foreign_releases / SOURCE_COMMIT
        destination.mkdir()
        marker = destination / "foreign"
        marker.write_bytes(b"KEEP\n")
        marker_before = marker.read_bytes()
        try:
            execute_authorized_stage(
                payload=foreign_payload,
                releases_root=foreign_releases,
                materializer=materializer,
                authorization=authorization,
                boundary_probe=_SequenceProbe([boundary] * 4),
            )
        except ProductionStagePrepError as exc:
            if exc.code != "FOREIGN_OR_PARTIAL_DESTINATION":
                raise
        else:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "foreign production destination was accepted",
            )
        if marker.read_bytes() != marker_before:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "foreign production destination was modified",
            )
        scenarios["foreign_destination"] = "FAIL_CLOSED_UNTOUCHED"

        # E. Interrupted stage residue blocks any retry/publication.
        residue_root = work / "residue"
        residue_root.mkdir()
        residue_releases = residue_root / "releases"
        residue_releases.mkdir()
        residue_payload = residue_root / "payload.tar.gz"
        residue_payload.write_bytes(payload.read_bytes())
        residue = residue_releases / f".{SOURCE_COMMIT}.stage-interrupted"
        residue.mkdir()
        residue_marker = residue / "partial"
        residue_marker.write_bytes(b"PARTIAL\n")
        residue_before = residue_marker.read_bytes()
        try:
            execute_authorized_stage(
                payload=residue_payload,
                releases_root=residue_releases,
                materializer=materializer,
                authorization=authorization,
                boundary_probe=_SequenceProbe([boundary] * 4),
            )
        except ProductionStagePrepError as exc:
            if exc.code != "RECOVERY_REQUIRED":
                raise
        else:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "stage residue did not block production retry",
            )
        if residue_marker.read_bytes() != residue_before:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "stage residue was modified",
            )
        scenarios["interrupted_residue"] = "RECOVERY_REQUIRED_UNTOUCHED"

        # F. Durable publication with response loss is recognized, retained,
        # sanitized and never authorizes activation.
        uncertain_root = work / "uncertain"
        uncertain_root.mkdir()
        uncertain_releases = uncertain_root / "releases"
        uncertain_releases.mkdir()
        uncertain_payload = uncertain_root / "payload.tar.gz"
        uncertain_payload.write_bytes(payload.read_bytes())

        def publish_then_raise(*args, **kwargs):
            materializer.materialize_payload(*args, **kwargs)
            raise RuntimeError("simulated response loss after durable publication")

        uncertain = execute_authorized_stage(
            payload=uncertain_payload,
            releases_root=uncertain_releases,
            materializer=materializer,
            authorization=authorization,
            boundary_probe=_SequenceProbe([boundary] * 8),
            materialize_call=publish_then_raise,
        )
        if uncertain["state"] != "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY":
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "durable uncertainty was not recognized",
            )
        if uncertain["activation_allowed"] is not False:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "uncertain stage authorized activation",
            )
        scenarios["postpublication_uncertainty"] = (
            "DURABLE_EXACT_RETAINED_RECONCILE_REQUIRED"
        )

        # G. Fresh boundary drift before stage primitive publication blocks write.
        drift_root = work / "drift-before"
        drift_root.mkdir()
        drift_releases = drift_root / "releases"
        drift_releases.mkdir()
        drift_payload = drift_root / "payload.tar.gz"
        drift_payload.write_bytes(payload.read_bytes())
        try:
            execute_authorized_stage(
                payload=drift_payload,
                releases_root=drift_releases,
                materializer=materializer,
                authorization=authorization,
                boundary_probe=_SequenceProbe(
                    [boundary, boundary, boundary, changed]
                ),
                materialize_call=forbidden_materialize,
            )
        except ProductionStagePrepError as exc:
            if exc.code != "BOUNDARY_DRIFT_BEFORE_MUTATION":
                raise
        else:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "mutation-boundary drift was ignored",
            )
        if stage.reconcile_stage(drift_releases, materializer)["state"] != "NOT_STAGED":
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "drift-before scenario published release",
            )
        scenarios["mutation_boundary_drift"] = "ABORTED_BEFORE_PUBLICATION"

        # H. Post-publication anchor drift retains exact release and blocks activation.
        post_root = work / "drift-after"
        post_root.mkdir()
        post_releases = post_root / "releases"
        post_releases.mkdir()
        post_payload = post_root / "payload.tar.gz"
        post_payload.write_bytes(payload.read_bytes())
        post_values = [boundary, boundary, boundary, boundary, changed, changed, changed]
        post = execute_authorized_stage(
            payload=post_payload,
            releases_root=post_releases,
            materializer=materializer,
            authorization=authorization,
            boundary_probe=_SequenceProbe(post_values),
        )
        if post["state"] != "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED":
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "postpublication drift state mismatch",
            )
        if post["runtime_anchors_unchanged"] is not False:
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "postpublication drift was not recorded",
            )
        if stage.reconcile_stage(post_releases, materializer)["state"] != "STAGED_EXACT":
            raise ProductionStagePrepError(
                "QUALIFICATION_FAILED",
                "postpublication drift lost exact release",
            )
        scenarios["postpublication_boundary_drift"] = (
            "EXACT_RELEASE_RETAINED_ACTIVATION_BLOCKED"
        )

    expected = {
        "authorization_scope": "EXACT_STAGE_ONLY_FAIL_CLOSED",
        "exact_authorized_stage": "STAGED_EXACT_ANCHORS_UNCHANGED",
        "exact_replay": "ALREADY_STAGED_EXACT_NO_PUBLICATION",
        "foreign_destination": "FAIL_CLOSED_UNTOUCHED",
        "interrupted_residue": "RECOVERY_REQUIRED_UNTOUCHED",
        "postpublication_uncertainty": "DURABLE_EXACT_RETAINED_RECONCILE_REQUIRED",
        "mutation_boundary_drift": "ABORTED_BEFORE_PUBLICATION",
        "postpublication_boundary_drift": "EXACT_RELEASE_RETAINED_ACTIVATION_BLOCKED",
    }
    if scenarios != expected:
        raise ProductionStagePrepError(
            "QUALIFICATION_FAILED",
            f"scenario evidence mismatch: {scenarios}",
        )

    return {
        "schema": "keelaryn.operation-control-r0007-production-stage-prep.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload": payload_identity,
        "materializer_git_blob": MATERIALIZER_GIT_BLOB,
        "recorded_live_boundary": recorded,
        "authorization_contract": production_authorization_template(),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "production_surface_function": "execute_authorized_stage",
        "production_stage_cli_exposed": False,
        "real_vps_stage_performed": False,
        "activation_implemented": False,
        "release_deletion_allowed": False,
        "blind_retry_allowed": False,
        "fresh_live_revalidation_required": True,
        "postpublication_anchor_reconcile_required": True,
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
        "drive_content_mutation_allowed": False,
        "production_mutation_allowed": False,
        "production_qualified": False,
        "next_action": "AUTHORIZE_AND_EXECUTE_SEPARATE_REAL_STAGE_TRANSACTION",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0007-production-stage-prep"
    )
    parser.add_argument("command", choices=("qualify",))
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = qualify(args.repository_root)
    except (ProductionStagePrepError, stage.StageError, OSError) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-r0007-production-stage-prep-failure.v1",
                    "error_class": type(exc).__name__,
                    "error_code": getattr(exc, "code", "OS_ERROR"),
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8", newline="\n")
    print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
