from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


GATE_REVISION = "operation-control-r0007-stage-gate-r0001"
CANDIDATE = "operation-control-r0007-20260921-01"
SOURCE_COMMIT = "833123b6a7ad2c61087ee8a86700bb9ad8a46298"
SOURCE_TREE = "bbca9e3a17162e12a7a0f649138e8c469518ad2a"
PAYLOAD_SHA256 = "c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9"
PAYLOAD_SIZE = 414534
PAYLOAD_FILE_COUNT = 208
MATERIALIZER_GIT_BLOB = "ece36ad98d4a15442f5f081db76345525fe1b8c1"

PREP_PATH = Path(__file__).with_name("operation_control_r0007_vps.py")
PREP_SPEC = importlib.util.spec_from_file_location(
    "keelaryn_r0007_bootstrap_prep_for_stage",
    PREP_PATH,
)
if PREP_SPEC is None or PREP_SPEC.loader is None:
    raise RuntimeError("cannot load r0007 bootstrap-prep authority")
prep = importlib.util.module_from_spec(PREP_SPEC)
sys.modules[PREP_SPEC.name] = prep
PREP_SPEC.loader.exec_module(prep)


class StageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def _load_materializer(path: Path):
    spec = importlib.util.spec_from_file_location(
        "keelaryn_r0007_stage_materializer",
        path,
    )
    if spec is None or spec.loader is None:
        raise StageError("MATERIALIZER_UNAVAILABLE", "cannot load exact materializer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    required = ("verify_payload", "verify_release_directory", "materialize_payload")
    if any(not callable(getattr(module, name, None)) for name in required):
        raise StageError("MATERIALIZER_INVALID", "materializer API is incomplete")
    return module


def _release_root(releases_root: Path) -> Path:
    root = releases_root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise StageError(
            "RELEASE_ROOT_INVALID",
            "release root must already be a real directory",
        )
    return root


def _stage_residues(releases_root: Path) -> tuple[str, ...]:
    prefix = f".{SOURCE_COMMIT}.stage-"
    try:
        entries = tuple(releases_root.iterdir())
    except OSError as exc:
        raise StageError("RELEASE_ROOT_UNREADABLE", "cannot enumerate release root") from exc
    return tuple(sorted(item.name for item in entries if item.name.startswith(prefix)))


def _exact_identity(materializer: Any, destination: Path) -> dict[str, Any]:
    try:
        identity = materializer.verify_release_directory(
            destination,
            expected_source_commit=SOURCE_COMMIT,
            expected_payload_sha256=PAYLOAD_SHA256,
        )
    except Exception as exc:
        raise StageError(
            "FOREIGN_OR_PARTIAL_DESTINATION",
            "successor destination exists but is not the exact frozen release",
        ) from exc
    observed = {
        "payload_sha256": identity.get("payload_sha256"),
        "payload_size": identity.get("payload_size"),
        "file_count": identity.get("file_count"),
    }
    expected = {
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }
    if observed != expected:
        raise StageError(
            "FOREIGN_OR_PARTIAL_DESTINATION",
            "successor release identity size/count mismatch",
        )
    return observed


def reconcile_stage(releases_root: Path, materializer: Any) -> dict[str, Any]:
    root = _release_root(releases_root)
    destination = root / SOURCE_COMMIT
    residues = _stage_residues(root)

    exists = destination.exists() or destination.is_symlink()
    if exists:
        try:
            identity = _exact_identity(materializer, destination)
        except StageError:
            return {
                "state": "FOREIGN_OR_PARTIAL_DESTINATION",
                "destination": destination.name,
                "residues": list(residues),
                "exact": False,
            }
        if residues:
            return {
                "state": "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED",
                "destination": destination.name,
                "residues": list(residues),
                "exact": True,
                "identity": identity,
            }
        return {
            "state": "STAGED_EXACT",
            "destination": destination.name,
            "residues": [],
            "exact": True,
            "identity": identity,
        }

    if residues:
        return {
            "state": "RECOVERY_REQUIRED",
            "destination": destination.name,
            "residues": list(residues),
            "exact": False,
        }

    return {
        "state": "NOT_STAGED",
        "destination": destination.name,
        "residues": [],
        "exact": False,
    }


def _verify_payload(payload: Path, materializer: Any) -> dict[str, Any]:
    if payload.is_symlink() or not payload.is_file():
        raise StageError("PAYLOAD_INVALID", "payload must be a regular file")
    try:
        raw = payload.read_bytes()
        source, members = materializer.verify_payload(
            raw,
            expected_source_commit=SOURCE_COMMIT,
            expected_payload_sha256=PAYLOAD_SHA256,
        )
    except Exception as exc:
        raise StageError("PAYLOAD_INVALID", "payload verification failed") from exc
    observed = {
        "source_commit": source,
        "payload_sha256": _sha(raw),
        "payload_size": len(raw),
        "file_count": len(members),
    }
    expected = {
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }
    if observed != expected:
        raise StageError("PAYLOAD_INVALID", f"payload identity mismatch: {observed}")
    return observed


def _boundary_snapshot(boundary_probe: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    value = boundary_probe()
    if not isinstance(value, dict):
        raise StageError("BOUNDARY_INVALID", "boundary probe did not return an object")
    try:
        return json.loads(_canonical(value).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StageError("BOUNDARY_INVALID", "boundary probe is not canonicalizable") from exc


def _stable_boundary(
    boundary_probe: Callable[[], dict[str, Any]],
    *,
    drift_code: str,
) -> dict[str, Any]:
    first = _boundary_snapshot(boundary_probe)
    second = _boundary_snapshot(boundary_probe)
    if _canonical(first) != _canonical(second):
        raise StageError(drift_code, "runtime boundary changed between read-only passes")
    return second


def stage_release(
    *,
    payload: Path,
    releases_root: Path,
    materializer: Any,
    boundary_probe: Callable[[], dict[str, Any]],
    materialize_call: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = _release_root(releases_root)
    payload_identity = _verify_payload(payload, materializer)
    prestate = reconcile_stage(root, materializer)

    if prestate["state"] == "FOREIGN_OR_PARTIAL_DESTINATION":
        raise StageError(
            "FOREIGN_OR_PARTIAL_DESTINATION",
            "foreign/partial successor destination must not be overwritten or deleted",
        )
    if prestate["state"] == "RECOVERY_REQUIRED":
        raise StageError(
            "RECOVERY_REQUIRED",
            "interrupted stage residue requires reconciliation before any retry",
        )
    if prestate["state"] == "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED":
        raise StageError(
            "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED",
            "exact release plus stage residue requires reconciliation; residue is preserved",
        )

    if prestate["state"] == "STAGED_EXACT":
        boundary = _stable_boundary(
            boundary_probe,
            drift_code="BOUNDARY_DRIFT_READ_ONLY",
        )
        return {
            "schema": "keelaryn.operation-control-r0007-stage-result.v1",
            "state": "ALREADY_STAGED_EXACT",
            "payload": payload_identity,
            "boundary": boundary,
            "release_publication_performed": False,
            "release_deletion_performed": False,
            "activation_allowed": False,
            "requires_reconcile": False,
        }

    if prestate["state"] != "NOT_STAGED":
        raise StageError("STAGE_STATE_INVALID", "unexpected stage prestate")

    preflight = _boundary_snapshot(boundary_probe)
    mutation_boundary = _boundary_snapshot(boundary_probe)
    if _canonical(preflight) != _canonical(mutation_boundary):
        raise StageError(
            "BOUNDARY_DRIFT_BEFORE_MUTATION",
            "runtime boundary changed before release publication",
        )

    immediate = reconcile_stage(root, materializer)
    if immediate["state"] != "NOT_STAGED":
        raise StageError(
            "STAGE_STATE_CHANGED_AT_MUTATION_BOUNDARY",
            "stage filesystem state changed at mutation boundary",
        )

    call = materialize_call or materializer.materialize_payload
    publication_reported_success = False
    try:
        call(
            payload,
            root,
            expected_source_commit=SOURCE_COMMIT,
            expected_payload_sha256=PAYLOAD_SHA256,
        )
        publication_reported_success = True
    except Exception as exc:
        observed = reconcile_stage(root, materializer)
        post = _boundary_snapshot(boundary_probe)
        if observed["state"] == "STAGED_EXACT":
            return {
                "schema": "keelaryn.operation-control-r0007-stage-result.v1",
                "state": "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY",
                "payload": payload_identity,
                "boundary": post,
                "boundary_unchanged": _canonical(post) == _canonical(mutation_boundary),
                "release_publication_performed": True,
                "materializer_reported_success": False,
                "release_deletion_performed": False,
                "activation_allowed": False,
                "requires_reconcile": True,
            }
        if observed["state"] in {
            "RECOVERY_REQUIRED",
            "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED",
        }:
            raise StageError(
                observed["state"],
                "materializer failed with durable stage residue; do not retry or delete blindly",
            ) from exc
        if observed["state"] == "FOREIGN_OR_PARTIAL_DESTINATION":
            raise StageError(
                "FOREIGN_OR_PARTIAL_DESTINATION",
                "materializer failed with non-exact destination; do not overwrite or delete",
            ) from exc
        raise StageError(
            "MATERIALIZATION_FAILED_NOT_STAGED",
            "materializer failed before durable publication; fresh reconcile required before retry",
        ) from exc

    observed = reconcile_stage(root, materializer)
    if observed["state"] != "STAGED_EXACT":
        raise StageError(
            "POST_PUBLICATION_STATE_INVALID",
            "materializer returned success without exact staged release",
        )

    post = _boundary_snapshot(boundary_probe)
    unchanged = _canonical(post) == _canonical(mutation_boundary)
    return {
        "schema": "keelaryn.operation-control-r0007-stage-result.v1",
        "state": (
            "STAGED_EXACT"
            if unchanged
            else "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED"
        ),
        "payload": payload_identity,
        "boundary": post,
        "boundary_unchanged": unchanged,
        "release_publication_performed": publication_reported_success,
        "materializer_reported_success": publication_reported_success,
        "release_deletion_performed": False,
        "activation_allowed": False,
        "requires_reconcile": not unchanged,
    }


def _sentinels(root: Path) -> dict[str, str]:
    sentinel_root = root / "non-release-boundary"
    sentinel_root.mkdir()
    values = {
        "production_current": b"releases/e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f\n",
        "control_current": b"releases/08f2e211f53764590f6ff0f05f86b2de62c14418\n",
        "systemd_control_units": b"r0005-exact-units\n",
        "writer": b"INACTIVE:0\n",
        "credential": b"sha256:7002ed72a223dd7fc860451c53a4ec8f264d14f7144000559a295522b7cbe928\n",
        "legacy_hub": b"PREPARED:OLD:RUNTIME_SAFETY_ONLY\n",
        "drive": b"NO_CONTENT_MUTATION\n",
    }
    result: dict[str, str] = {}
    for name, raw in values.items():
        path = sentinel_root / name
        path.write_bytes(raw)
        result[name] = _sha(raw)
    return result


def _sentinel_hashes(root: Path) -> dict[str, str]:
    sentinel_root = root / "non-release-boundary"
    return {
        path.name: _sha(path.read_bytes())
        for path in sorted(sentinel_root.iterdir(), key=lambda item: item.name)
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


def _scenario_root(parent: Path, name: str) -> tuple[Path, Path, dict[str, str]]:
    root = parent / name
    root.mkdir()
    releases = root / "releases"
    releases.mkdir()
    before = _sentinels(root)
    return root, releases, before


def _assert_sentinels(root: Path, before: dict[str, str]) -> None:
    after = _sentinel_hashes(root)
    if after != before:
        raise StageError(
            "NON_RELEASE_BOUNDARY_MUTATED",
            "stage qualification mutated a non-release sentinel",
        )


def _copy_payload(payload: Path, root: Path) -> Path:
    target = root / "r0007.tar.gz"
    shutil.copyfile(payload, target)
    return target


def _materializer_from_source(source: Path):
    return _load_materializer(
        source / "deploy" / "zero-based-vps" / "materialize_payload.py"
    )


def _stable_boundary_value() -> dict[str, Any]:
    return {
        "production_source_commit": prep.PRODUCTION_SOURCE,
        "control_source_commit": prep.PREDECESSOR_SOURCE_COMMIT,
        "writer": "INACTIVE_MAINPID_0",
        "legacy_hub": {
            "status": "PREPARED",
            "selector_role": "OLD",
            "authority_scope": "RUNTIME_SAFETY_ONLY",
        },
        "credential_sha256": prep.CREDENTIAL_SHA256,
        "drive_mutations_performed": False,
    }


def qualify(repository_root: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    recorded = prep._recorded_boundary(repository_root)

    with tempfile.TemporaryDirectory(prefix="keelaryn-r0007-stage-qualification-") as td:
        work = Path(td)
        source = prep._checkout_frozen(work)
        payload_identity = prep._rebuild_frozen(source, work)
        payload = work / "first.tar.gz"
        materializer = _materializer_from_source(source)
        scenario_parent = work / "scenarios"
        scenario_parent.mkdir()

        stable = _stable_boundary_value()
        changed = json.loads(_canonical(stable).decode("utf-8"))
        changed["writer"] = "ACTIVE:999"

        scenarios: dict[str, Any] = {}

        # 1. ABSENT -> exact immutable release publication.
        root, releases, before = _scenario_root(scenario_parent, "absent_to_exact")
        result = stage_release(
            payload=_copy_payload(payload, root),
            releases_root=releases,
            materializer=materializer,
            boundary_probe=_SequenceProbe([stable, stable, stable]),
        )
        if result["state"] != "STAGED_EXACT":
            raise StageError("QUALIFICATION_FAILED", "ABSENT -> STAGED_EXACT failed")
        _assert_sentinels(root, before)
        scenarios["absent_to_staged_exact"] = result["state"]

        # 2. Exact replay must not invoke publication again.
        def forbidden_materialize(*args, **kwargs):
            raise AssertionError("idempotent exact replay attempted publication")

        replay = stage_release(
            payload=root / "r0007.tar.gz",
            releases_root=releases,
            materializer=materializer,
            boundary_probe=_SequenceProbe([stable, stable]),
            materialize_call=forbidden_materialize,
        )
        if replay["state"] != "ALREADY_STAGED_EXACT":
            raise StageError("QUALIFICATION_FAILED", "exact replay is not idempotent")
        _assert_sentinels(root, before)
        scenarios["already_staged_exact"] = replay["state"]

        # 3. Foreign/partial destination is never overwritten/deleted.
        root3, releases3, before3 = _scenario_root(scenario_parent, "foreign_partial")
        partial = releases3 / SOURCE_COMMIT
        partial.mkdir()
        marker = partial / "foreign.txt"
        marker.write_bytes(b"FOREIGN\n")
        marker_sha = _sha(marker.read_bytes())
        try:
            stage_release(
                payload=_copy_payload(payload, root3),
                releases_root=releases3,
                materializer=materializer,
                boundary_probe=_SequenceProbe([stable, stable]),
            )
        except StageError as exc:
            if exc.code != "FOREIGN_OR_PARTIAL_DESTINATION":
                raise
        else:
            raise StageError("QUALIFICATION_FAILED", "foreign destination was accepted")
        if _sha(marker.read_bytes()) != marker_sha:
            raise StageError("QUALIFICATION_FAILED", "foreign destination was modified")
        _assert_sentinels(root3, before3)
        scenarios["foreign_partial"] = "FAIL_CLOSED_UNTOUCHED"

        # 4. Pre-publication crash residue blocks blind retry/cleanup.
        root4, releases4, before4 = _scenario_root(scenario_parent, "prepublication_residue")
        residue = releases4 / f".{SOURCE_COMMIT}.stage-interrupted"
        residue.mkdir()
        residue_marker = residue / "partial"
        residue_marker.write_bytes(b"PARTIAL\n")
        residue_sha = _sha(residue_marker.read_bytes())
        try:
            stage_release(
                payload=_copy_payload(payload, root4),
                releases_root=releases4,
                materializer=materializer,
                boundary_probe=_SequenceProbe([stable, stable]),
            )
        except StageError as exc:
            if exc.code != "RECOVERY_REQUIRED":
                raise
        else:
            raise StageError("QUALIFICATION_FAILED", "stage residue was ignored")
        if _sha(residue_marker.read_bytes()) != residue_sha:
            raise StageError("QUALIFICATION_FAILED", "stage residue was modified")
        _assert_sentinels(root4, before4)
        scenarios["prepublication_residue"] = "RECOVERY_REQUIRED_UNTOUCHED"

        # 5. Publication may commit before caller sees an error.
        root5, releases5, before5 = _scenario_root(scenario_parent, "postpublication_uncertainty")
        payload5 = _copy_payload(payload, root5)

        def publish_then_raise(*args, **kwargs):
            materializer.materialize_payload(*args, **kwargs)
            raise RuntimeError("simulated response loss after durable publication")

        uncertain = stage_release(
            payload=payload5,
            releases_root=releases5,
            materializer=materializer,
            boundary_probe=_SequenceProbe([stable, stable, stable]),
            materialize_call=publish_then_raise,
        )
        if uncertain["state"] != "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY":
            raise StageError("QUALIFICATION_FAILED", "post-publication uncertainty not reconciled")
        exact5 = reconcile_stage(releases5, materializer)
        if exact5["state"] != "STAGED_EXACT":
            raise StageError("QUALIFICATION_FAILED", "durable publication was not retained")
        _assert_sentinels(root5, before5)
        scenarios["postpublication_uncertainty"] = uncertain["state"]

        # 6. Boundary drift before publication blocks materialization entirely.
        root6, releases6, before6 = _scenario_root(scenario_parent, "prepublication_boundary_drift")
        payload6 = _copy_payload(payload, root6)
        try:
            stage_release(
                payload=payload6,
                releases_root=releases6,
                materializer=materializer,
                boundary_probe=_SequenceProbe([stable, changed]),
                materialize_call=forbidden_materialize,
            )
        except StageError as exc:
            if exc.code != "BOUNDARY_DRIFT_BEFORE_MUTATION":
                raise
        else:
            raise StageError("QUALIFICATION_FAILED", "prepublication boundary drift was ignored")
        if reconcile_stage(releases6, materializer)["state"] != "NOT_STAGED":
            raise StageError("QUALIFICATION_FAILED", "boundary drift still published release")
        _assert_sentinels(root6, before6)
        scenarios["prepublication_boundary_drift"] = "ABORTED_BEFORE_PUBLICATION"

        # 7. Drift after durable publication retains exact release and requires reconcile.
        root7, releases7, before7 = _scenario_root(scenario_parent, "postpublication_boundary_drift")
        drifted = stage_release(
            payload=_copy_payload(payload, root7),
            releases_root=releases7,
            materializer=materializer,
            boundary_probe=_SequenceProbe([stable, stable, changed]),
        )
        if drifted["state"] != "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED":
            raise StageError("QUALIFICATION_FAILED", "postpublication drift state mismatch")
        if reconcile_stage(releases7, materializer)["state"] != "STAGED_EXACT":
            raise StageError("QUALIFICATION_FAILED", "exact release lost after postpublication drift")
        _assert_sentinels(root7, before7)
        scenarios["postpublication_boundary_drift"] = drifted["state"]

        # 8. Exact destination plus orphan stage residue remains fail-closed.
        root8, releases8, before8 = _scenario_root(scenario_parent, "exact_plus_residue")
        payload8 = _copy_payload(payload, root8)
        materializer.materialize_payload(
            payload8,
            releases8,
            expected_source_commit=SOURCE_COMMIT,
            expected_payload_sha256=PAYLOAD_SHA256,
        )
        orphan = releases8 / f".{SOURCE_COMMIT}.stage-orphan"
        orphan.mkdir()
        orphan_marker = orphan / "marker"
        orphan_marker.write_bytes(b"ORPHAN\n")
        orphan_sha = _sha(orphan_marker.read_bytes())
        try:
            stage_release(
                payload=payload8,
                releases_root=releases8,
                materializer=materializer,
                boundary_probe=_SequenceProbe([stable, stable]),
                materialize_call=forbidden_materialize,
            )
        except StageError as exc:
            if exc.code != "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED":
                raise
        else:
            raise StageError("QUALIFICATION_FAILED", "exact+residue state was accepted")
        if reconcile_stage(releases8, materializer)["state"] != "STAGED_EXACT_WITH_RESIDUE_RECOVERY_REQUIRED":
            raise StageError("QUALIFICATION_FAILED", "exact+residue state was modified")
        if _sha(orphan_marker.read_bytes()) != orphan_sha:
            raise StageError("QUALIFICATION_FAILED", "orphan residue was modified")
        _assert_sentinels(root8, before8)
        scenarios["exact_plus_residue"] = "FAIL_CLOSED_RECOVERY_REQUIRED"

    expected_scenarios = {
        "absent_to_staged_exact": "STAGED_EXACT",
        "already_staged_exact": "ALREADY_STAGED_EXACT",
        "foreign_partial": "FAIL_CLOSED_UNTOUCHED",
        "prepublication_residue": "RECOVERY_REQUIRED_UNTOUCHED",
        "postpublication_uncertainty": "STAGED_EXACT_AFTER_MATERIALIZER_UNCERTAINTY",
        "prepublication_boundary_drift": "ABORTED_BEFORE_PUBLICATION",
        "postpublication_boundary_drift": "STAGED_EXACT_BOUNDARY_DRIFT_RECONCILE_REQUIRED",
        "exact_plus_residue": "FAIL_CLOSED_RECOVERY_REQUIRED",
    }
    if scenarios != expected_scenarios:
        raise StageError("QUALIFICATION_FAILED", f"scenario evidence mismatch: {scenarios}")

    return {
        "schema": "keelaryn.operation-control-r0007-stage-qualification.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload": payload_identity,
        "materializer_git_blob": MATERIALIZER_GIT_BLOB,
        "recorded_live_boundary": recorded,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "transaction_model": "MONOTONIC_INERT_IMMUTABLE_RELEASE_PUBLICATION",
        "commit_authority": "EXACT_IMMUTABLE_RELEASE_DIRECTORY",
        "prepared_record_required": False,
        "release_deletion_on_uncertainty_allowed": False,
        "blind_retry_allowed": False,
        "activation_implemented": False,
        "production_stage_cli_exposed": False,
        "production_mutation_allowed": False,
        "drive_content_mutation_allowed": False,
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
        "fresh_mutation_boundary_revalidation_required": True,
        "disposable_only": True,
        "production_qualified": False,
        "next_action": "DESIGN_AUTHORIZED_PRODUCTION_STAGE_SURFACE",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0007-stage-qualification"
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
        if args.command != "qualify":
            raise StageError("COMMAND_INVALID", "unsupported stage qualification command")
        value = qualify(args.repository_root)
    except (StageError, OSError) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-r0007-stage-qualification-failure.v1",
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
