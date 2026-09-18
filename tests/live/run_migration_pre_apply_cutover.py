from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core"
DEPLOY = REPO / "deploy" / "zero-based-vps"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(DEPLOY))

import hub_cutover  # noqa: E402
from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider  # noqa: E402
from keelaryn_core.drive_rest import GoogleDriveBackend  # noqa: E402
from keelaryn_core.migration_common import MIGRATION_SOURCE_NAME, small_file  # noqa: E402
from keelaryn_core.migration_drive_source import verify_migration_source_against_drive  # noqa: E402
from keelaryn_core.migration_freeze import verify_migration_candidate_freeze  # noqa: E402
from keelaryn_core.migration_pack import verify_migration_pack  # noqa: E402
from keelaryn_core.migration_post_cutover_acceptance import (  # noqa: E402
    DriveMigrationPostCutoverReadOnlyAcceptance,
)


SCHEMA = "keelaryn.migration-pre-apply-live.v1"
RECEIPT_SCHEMA = "keelaryn.migration-pre-apply-private-receipt.v1"


class LivePreApplyCutoverError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise LivePreApplyCutoverError(f"missing required environment: {name}")
    return value


def _path(name: str) -> Path:
    return Path(_required(name))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _hex(value: Any, length: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise LivePreApplyCutoverError(f"{label} is invalid")
    return value


def _private_parent(path: Path) -> Path:
    parent = path.absolute().parent
    if parent.is_symlink() or not parent.is_dir():
        raise LivePreApplyCutoverError(
            "private pre-apply receipt parent must be a real directory"
        )
    info = parent.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise LivePreApplyCutoverError(
            "private pre-apply receipt parent must be owner-controlled mode 0700"
        )
    return parent


def strict_pre_apply_receipt(path: Path) -> dict[str, Any]:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise LivePreApplyCutoverError(
            "private pre-apply receipt must be one regular file"
        )
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise LivePreApplyCutoverError(
            "private pre-apply receipt must be owner-controlled mode 0600"
        )
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LivePreApplyCutoverError("private pre-apply receipt is invalid") from exc
    expected = {
        "schema",
        "transaction_id",
        "active_transaction_sha256",
        "source_commit",
        "source_tree",
        "pack_sha256",
        "old_selector_identity_sha256",
        "new_selector_identity_sha256",
        "qualification_evidence_sha256",
        "target_acceptance_evidence_sha256",
        "outcome",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise LivePreApplyCutoverError("private pre-apply receipt has invalid keys")
    if value["schema"] != RECEIPT_SCHEMA or value["outcome"] != "PRE_APPLY_VERIFIED":
        raise LivePreApplyCutoverError("private pre-apply receipt schema/outcome mismatch")
    _hex(value["transaction_id"], 32, "pre-apply transaction_id")
    _hex(value["source_commit"], 40, "pre-apply source_commit")
    _hex(value["source_tree"], 40, "pre-apply source_tree")
    for key in (
        "active_transaction_sha256",
        "pack_sha256",
        "old_selector_identity_sha256",
        "new_selector_identity_sha256",
        "qualification_evidence_sha256",
        "target_acceptance_evidence_sha256",
    ):
        _hex(value[key], 64, f"pre-apply {key}")
    if raw != _canonical_json(value):
        raise LivePreApplyCutoverError(
            "private pre-apply receipt is not canonical JSON bytes"
        )
    return value


def _write_or_verify_receipt(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path = path.absolute()
    parent = _private_parent(path)
    raw = _canonical_json(value)
    if path.exists() or path.is_symlink():
        observed = strict_pre_apply_receipt(path)
        if observed != value:
            raise LivePreApplyCutoverError(
                "private pre-apply receipt conflicts with current verification"
            )
        return observed

    temp = parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        try:
            os.link(temp, path)
        except FileExistsError:
            observed = strict_pre_apply_receipt(path)
            if observed != value:
                raise LivePreApplyCutoverError(
                    "private pre-apply receipt raced with conflicting identity"
                )
        try:
            fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
    finally:
        temp.unlink(missing_ok=True)
    return strict_pre_apply_receipt(path)


def _prepared_binding(
    switch: hub_cutover.HubSelectorCutover,
) -> tuple[bytes, dict[str, Any]]:
    with switch.locked():
        record_raw, record = switch._load_active()
        if switch._load_terminal(record_raw, record) is not None:
            raise LivePreApplyCutoverError(
                "pre-apply verification cannot use a terminal transaction"
            )
        selected, _ = hub_cutover._read_selector(switch.selector_path)
        if selected != record["old_hub_root_id"]:
            raise LivePreApplyCutoverError(
                "pre-apply verification requires exact OLD selector"
            )
        if switch.mutation_gate is None:
            raise LivePreApplyCutoverError(
                "pre-apply verification requires production mutation inhibit"
            )
        with switch.mutation_gate.locked():
            expected = switch._mutation_inhibit_value(record_raw, record)
            if switch.mutation_gate.read() != expected:
                raise LivePreApplyCutoverError(
                    "production mutation inhibit does not bind exact PREPARED transaction"
                )
        return record_raw, record


def _verify_receipt_for_status(
    switch: hub_cutover.HubSelectorCutover,
    receipt: dict[str, Any],
    *,
    expected_status: str,
) -> None:
    with switch.locked():
        record_raw, record = switch._load_active()
        selected, _ = hub_cutover._read_selector(switch.selector_path)
        expected_selector = (
            record["old_hub_root_id"]
            if expected_status == "PREPARED"
            else record["new_hub_root_id"]
        )
        if record["transaction_id"] != receipt["transaction_id"]:
            raise LivePreApplyCutoverError("pre-apply receipt transaction mismatch")
        if _sha256(record_raw) != receipt["active_transaction_sha256"]:
            raise LivePreApplyCutoverError("pre-apply receipt active authority mismatch")
        if record["tool"]["source_commit"] != receipt["source_commit"]:
            raise LivePreApplyCutoverError("pre-apply receipt source commit mismatch")
        if selected != expected_selector:
            raise LivePreApplyCutoverError(
                f"pre-apply recovery selector is not exact {expected_status}"
            )
        if _sha256(record["old_hub_root_id"].encode("utf-8")) != receipt[
            "old_selector_identity_sha256"
        ]:
            raise LivePreApplyCutoverError("pre-apply receipt OLD identity mismatch")
        if _sha256(record["new_hub_root_id"].encode("utf-8")) != receipt[
            "new_selector_identity_sha256"
        ]:
            raise LivePreApplyCutoverError("pre-apply receipt NEW identity mismatch")
        if switch.mutation_gate is None:
            raise LivePreApplyCutoverError("production mutation gate is missing")
        with switch.mutation_gate.locked():
            expected = switch._mutation_inhibit_value(record_raw, record)
            if switch.mutation_gate.read() != expected:
                raise LivePreApplyCutoverError(
                    "production mutation inhibit changed after pre-apply verification"
                )


def _receipt_for(
    record_raw: bytes,
    record: dict[str, Any],
    acceptance_value: dict[str, Any],
    qualification_evidence: bytes,
) -> dict[str, Any]:
    if acceptance_value.get("outcome") != "POST_CUTOVER_READ_ONLY_PASS":
        raise LivePreApplyCutoverError("fresh target verification did not reach PASS")
    if acceptance_value.get("drive_mutations_performed") is not False:
        raise LivePreApplyCutoverError("fresh target verification is not read-only")
    new_sha = _sha256(record["new_hub_root_id"].encode("utf-8"))
    if (
        acceptance_value.get("source_commit") != record["tool"]["source_commit"]
        or acceptance_value.get("selector_identity_sha256") != new_sha
        or acceptance_value.get("target_identity_sha256") != new_sha
    ):
        raise LivePreApplyCutoverError(
            "fresh target verification does not bind exact cutover transaction"
        )
    source_tree = acceptance_value.get("source_tree")
    pack_sha = acceptance_value.get("pack_sha256")
    _hex(source_tree, 40, "target acceptance source_tree")
    _hex(pack_sha, 64, "target acceptance pack_sha256")
    return {
        "schema": RECEIPT_SCHEMA,
        "transaction_id": record["transaction_id"],
        "active_transaction_sha256": _sha256(record_raw),
        "source_commit": record["tool"]["source_commit"],
        "source_tree": source_tree,
        "pack_sha256": pack_sha,
        "old_selector_identity_sha256": _sha256(
            record["old_hub_root_id"].encode("utf-8")
        ),
        "new_selector_identity_sha256": new_sha,
        "qualification_evidence_sha256": _sha256(qualification_evidence),
        "target_acceptance_evidence_sha256": _sha256_json(acceptance_value),
        "outcome": "PRE_APPLY_VERIFIED",
    }


def _verify_local_provenance(
    receipt: dict[str, Any],
    pack_dir: Path,
    freeze_receipt: Path,
    repo_root: Path,
    qualification_evidence: Path,
) -> None:
    pack = verify_migration_pack(pack_dir)
    freeze = verify_migration_candidate_freeze(
        pack.root,
        freeze_receipt,
        repo_root,
    )
    if pack.pack_sha256 != receipt["pack_sha256"]:
        raise LivePreApplyCutoverError(
            "frozen migration pack changed before selector apply"
        )
    if (
        freeze["source_commit"] != receipt["source_commit"]
        or freeze["source_tree"] != receipt["source_tree"]
    ):
        raise LivePreApplyCutoverError(
            "frozen source identity changed before selector apply"
        )
    current_qualification = small_file(
        qualification_evidence,
        "production qualification evidence at selector commit boundary",
    )
    if _sha256(current_qualification) != receipt["qualification_evidence_sha256"]:
        raise LivePreApplyCutoverError(
            "production qualification evidence changed before selector apply"
        )


def _public(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source_commit": receipt["source_commit"],
        "active_transaction_sha256": receipt["active_transaction_sha256"],
        "pre_apply_receipt_sha256": _sha256(_canonical_json(receipt)),
        "target_acceptance_evidence_sha256": receipt[
            "target_acceptance_evidence_sha256"
        ],
        "outcome": "PRODUCTION_CUTOVER_APPLIED",
        "production_selector_mutated": True,
        "drive_mutations_performed": False,
    }


def _render(value: dict[str, Any], forbidden: tuple[str, ...]) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if any(secret and secret in rendered for secret in forbidden):
        raise LivePreApplyCutoverError(
            "sanitized pre-apply output leaked private identity/path"
        )
    return rendered


def main() -> int:
    phase = "preflight"
    forbidden: tuple[str, ...] = ()
    try:
        if _required("KEELARYN_PRODUCTION_CUTOVER_ENABLE") != "YES":
            raise LivePreApplyCutoverError(
                "production cutover is not explicitly enabled"
            )
        selector = _path("KEELARYN_HUB_SELECTOR_PATH")
        state_root = _path("KEELARYN_DEPLOYMENT_STATE_ROOT")
        mutation_gate_root = _path("KEELARYN_MUTATION_GATE_ROOT")
        source_commit = _required("KEELARYN_SOURCE_COMMIT")
        receipt_path = _path("KEELARYN_PRE_APPLY_CUTOVER_RECEIPT")
        pack_dir = _path("KEELARYN_MIGRATION_PACK_DIR")
        freeze_receipt = _path("KEELARYN_MIGRATION_FREEZE_RECEIPT")
        repo_root = _path("KEELARYN_MIGRATION_REPO_ROOT")
        target_authority = _path("KEELARYN_MIGRATION_TARGET_AUTHORITY")
        qualification_evidence = _path(
            "KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE"
        )
        forbidden = (
            str(selector),
            str(state_root),
            str(mutation_gate_root),
            str(receipt_path),
            str(pack_dir),
            str(freeze_receipt),
            str(repo_root),
            str(target_authority),
            str(qualification_evidence),
        )

        switch = hub_cutover.HubSelectorCutover(
            selector,
            state_root,
            source_commit,
            mutation_gate_root=mutation_gate_root,
            executing_tool=Path(hub_cutover.__file__),
        )
        status = switch.status()
        if status.get("status") == "APPLIED":
            phase = "apply-recovery"
            receipt = strict_pre_apply_receipt(receipt_path)
            _verify_receipt_for_status(switch, receipt, expected_status="APPLIED")
            _verify_local_provenance(
                receipt,
                pack_dir,
                freeze_receipt,
                repo_root,
                qualification_evidence,
            )
            print(_render(_public(receipt), forbidden), flush=True)
            return 0
        if status.get("status") != "PREPARED":
            raise LivePreApplyCutoverError(
                "pre-apply finalizer requires exact PREPARED cutover transaction"
            )

        phase = "transaction-binding"
        record_raw, record = _prepared_binding(switch)
        forbidden = forbidden + (
            record["old_hub_root_id"],
            record["new_hub_root_id"],
            record["transaction_id"],
        )

        phase = "oauth"
        token_provider = GoogleOAuthRefreshTokenProvider.from_environment()
        drive = GoogleDriveBackend(token_provider)

        phase = "target-verification"
        acceptance = DriveMigrationPostCutoverReadOnlyAcceptance(
            drive, record["new_hub_root_id"]
        ).run(
            pack_dir,
            freeze_receipt,
            repo_root,
            target_authority,
            qualification_evidence,
        )
        acceptance_value = acceptance.to_json_value()

        phase = "legacy-source-verification"
        verify_migration_source_against_drive(
            drive,
            record["old_hub_root_id"],
            pack_dir / "authority" / MIGRATION_SOURCE_NAME,
        )

        phase = "private-receipt"
        qualification_raw = small_file(
            qualification_evidence,
            "production qualification evidence for pre-apply receipt",
        )
        receipt = _write_or_verify_receipt(
            receipt_path,
            _receipt_for(record_raw, record, acceptance_value, qualification_raw),
        )

        phase = "commit-boundary-revalidation"
        _verify_receipt_for_status(switch, receipt, expected_status="PREPARED")
        _verify_local_provenance(
            receipt,
            pack_dir,
            freeze_receipt,
            repo_root,
            qualification_evidence,
        )

        phase = "selector-apply"
        result = switch.apply(
            expected_active_transaction_sha256=receipt[
                "active_transaction_sha256"
            ]
        )
        if (
            result.get("status") != "APPLIED"
            or result.get("transaction_id") != receipt["transaction_id"]
        ):
            raise LivePreApplyCutoverError(
                "selector apply did not return exact bound APPLIED transaction"
            )
        _verify_receipt_for_status(switch, receipt, expected_status="APPLIED")

        print(_render(_public(receipt), forbidden), flush=True)
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.migration-pre-apply-live-failure.v1",
                    "phase": phase,
                    "error_class": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
