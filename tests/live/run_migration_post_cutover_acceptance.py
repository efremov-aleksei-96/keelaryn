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
LIVE = REPO / "tests" / "live"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(DEPLOY))
sys.path.insert(0, str(LIVE))

import hub_cutover  # noqa: E402
from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider  # noqa: E402
from keelaryn_core.drive_rest import GoogleDriveBackend  # noqa: E402
from keelaryn_core.migration_common import MIGRATION_SOURCE_NAME  # noqa: E402
from keelaryn_core.migration_drive_source import verify_migration_source_against_drive  # noqa: E402
from keelaryn_core.migration_post_cutover_acceptance import (  # noqa: E402
    DriveMigrationPostCutoverReadOnlyAcceptance,
)
from run_migration_pre_apply_cutover import strict_pre_apply_receipt  # noqa: E402

SCHEMA = "keelaryn.migration-post-cutover-live-finalization.v2"
RECEIPT_SCHEMA = "keelaryn.migration-post-cutover-private-finalization-receipt.v2"


class LivePostCutoverFinalizationError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise LivePostCutoverFinalizationError(f"missing required environment: {name}")
    return value


def _path(name: str) -> Path:
    return Path(_required(name))


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value))


def _private_parent(path: Path) -> Path:
    parent = path.absolute().parent
    if parent.is_symlink() or not parent.is_dir():
        raise LivePostCutoverFinalizationError(
            "private finalization receipt parent must be a real directory"
        )
    info = parent.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise LivePostCutoverFinalizationError(
            "private finalization receipt parent must be owner-controlled mode 0700"
        )
    return parent


def _strict_receipt(path: Path) -> dict[str, Any]:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise LivePostCutoverFinalizationError(
            "private finalization receipt must be one regular file"
        )
    info = path.stat(follow_symlinks=False)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise LivePostCutoverFinalizationError(
            "private finalization receipt must be owner-controlled mode 0600"
        )
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LivePostCutoverFinalizationError(
            "private finalization receipt is invalid"
        ) from exc
    expected = {
        "schema",
        "transaction_id",
        "active_transaction_sha256",
        "source_commit",
        "selector_identity_sha256",
        "acceptance_evidence_sha256",
        "pre_apply_receipt_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise LivePostCutoverFinalizationError(
            "private finalization receipt has invalid keys"
        )
    if value["schema"] != RECEIPT_SCHEMA:
        raise LivePostCutoverFinalizationError(
            "private finalization receipt schema mismatch"
        )
    txid = value["transaction_id"]
    if (
        not isinstance(txid, str)
        or len(txid) != 32
        or any(ch not in "0123456789abcdef" for ch in txid)
    ):
        raise LivePostCutoverFinalizationError(
            "private finalization receipt transaction_id is invalid"
        )
    for key in (
        "active_transaction_sha256",
        "selector_identity_sha256",
        "acceptance_evidence_sha256",
        "pre_apply_receipt_sha256",
    ):
        digest = value[key]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise LivePostCutoverFinalizationError(
                f"private finalization receipt {key} is invalid"
            )
    source = value["source_commit"]
    if (
        not isinstance(source, str)
        or len(source) != 40
        or any(ch not in "0123456789abcdef" for ch in source)
    ):
        raise LivePostCutoverFinalizationError(
            "private finalization receipt source_commit is invalid"
        )
    if raw != _canonical_json(value):
        raise LivePostCutoverFinalizationError(
            "private finalization receipt is not canonical JSON bytes"
        )
    return value


def _write_or_verify_receipt(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path = path.absolute()
    parent = _private_parent(path)
    raw = _canonical_json(value)
    if path.exists() or path.is_symlink():
        observed = _strict_receipt(path)
        if observed != value:
            raise LivePostCutoverFinalizationError(
                "private finalization receipt conflicts with current acceptance"
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
            observed = _strict_receipt(path)
            if observed != value:
                raise LivePostCutoverFinalizationError(
                    "private finalization receipt raced with conflicting identity"
                )
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temp.unlink(missing_ok=True)
    return _strict_receipt(path)


def _active_binding(
    switch: hub_cutover.HubSelectorCutover,
) -> tuple[bytes, dict[str, Any], str]:
    with switch.locked():
        record_raw, record = switch._load_active()
        terminal = switch._load_terminal(record_raw, record)
        if terminal is not None:
            raise LivePostCutoverFinalizationError(
                "terminal decision already exists during fresh acceptance"
            )
        selected, _ = hub_cutover._read_selector(switch.selector_path)
        if selected != record["new_hub_root_id"]:
            raise LivePostCutoverFinalizationError(
                "fresh acceptance requires exact NEW selector"
            )
        return record_raw, record, selected


def _verify_pre_apply_against_record(
    pre_apply: dict[str, Any],
    record_raw: bytes,
    record: dict[str, Any],
) -> None:
    if pre_apply["transaction_id"] != record["transaction_id"]:
        raise LivePostCutoverFinalizationError(
            "pre-apply receipt transaction does not match active cutover"
        )
    if pre_apply["active_transaction_sha256"] != _sha256_bytes(record_raw):
        raise LivePostCutoverFinalizationError(
            "pre-apply receipt active authority does not match cutover"
        )
    if pre_apply["source_commit"] != record["tool"]["source_commit"]:
        raise LivePostCutoverFinalizationError(
            "pre-apply receipt source commit does not match cutover"
        )
    if pre_apply["old_selector_identity_sha256"] != _sha256_bytes(
        record["old_hub_root_id"].encode("utf-8")
    ):
        raise LivePostCutoverFinalizationError(
            "pre-apply receipt OLD identity does not match cutover"
        )
    if pre_apply["new_selector_identity_sha256"] != _sha256_bytes(
        record["new_hub_root_id"].encode("utf-8")
    ):
        raise LivePostCutoverFinalizationError(
            "pre-apply receipt NEW identity does not match cutover"
        )


def _verify_pre_apply_against_acceptance(
    pre_apply: dict[str, Any],
    acceptance_value: dict[str, Any],
) -> None:
    if pre_apply["source_tree"] != acceptance_value.get("source_tree"):
        raise LivePostCutoverFinalizationError(
            "pre-apply receipt source tree disagrees with fresh NEW acceptance"
        )
    if pre_apply["pack_sha256"] != acceptance_value.get("pack_sha256"):
        raise LivePostCutoverFinalizationError(
            "pre-apply receipt pack identity disagrees with fresh NEW acceptance"
        )
    if (
        pre_apply["target_acceptance_evidence_sha256"]
        != _sha256_json(acceptance_value)
    ):
        raise LivePostCutoverFinalizationError(
            "fresh NEW acceptance changed since pre-apply verification"
        )


def _receipt_for(
    record_raw: bytes,
    record: dict[str, Any],
    selected_hub_root_id: str,
    acceptance_value: dict[str, Any],
    pre_apply_receipt_sha256: str,
) -> dict[str, Any]:
    selected_sha = _sha256_bytes(selected_hub_root_id.encode("utf-8"))
    if acceptance_value.get("outcome") != "POST_CUTOVER_READ_ONLY_PASS":
        raise LivePostCutoverFinalizationError(
            "post-cutover acceptance did not reach exact PASS"
        )
    if acceptance_value.get("drive_mutations_performed") is not False:
        raise LivePostCutoverFinalizationError(
            "post-cutover acceptance is not proven read-only"
        )
    if acceptance_value.get("hub_cutover_accept_allowed") is not True:
        raise LivePostCutoverFinalizationError(
            "post-cutover acceptance did not authorize terminal accept"
        )
    if acceptance_value.get("source_commit") != record["tool"]["source_commit"]:
        raise LivePostCutoverFinalizationError(
            "post-cutover acceptance source commit disagrees with cutover transaction"
        )
    if (
        acceptance_value.get("selector_identity_sha256") != selected_sha
        or acceptance_value.get("target_identity_sha256") != selected_sha
    ):
        raise LivePostCutoverFinalizationError(
            "post-cutover acceptance identity does not bind exact NEW selector"
        )
    return {
        "schema": RECEIPT_SCHEMA,
        "transaction_id": record["transaction_id"],
        "active_transaction_sha256": _sha256_bytes(record_raw),
        "source_commit": record["tool"]["source_commit"],
        "selector_identity_sha256": selected_sha,
        "acceptance_evidence_sha256": _sha256_json(acceptance_value),
        "pre_apply_receipt_sha256": pre_apply_receipt_sha256,
    }


def _verify_receipt_against_active(
    switch: hub_cutover.HubSelectorCutover,
    receipt: dict[str, Any],
) -> None:
    with switch.locked():
        record_raw, record = switch._load_active()
        selected, _ = hub_cutover._read_selector(switch.selector_path)
        if record["transaction_id"] != receipt["transaction_id"]:
            raise LivePostCutoverFinalizationError(
                "active cutover transaction changed after acceptance"
            )
        if _sha256_bytes(record_raw) != receipt["active_transaction_sha256"]:
            raise LivePostCutoverFinalizationError(
                "active cutover authority changed after acceptance"
            )
        if record["tool"]["source_commit"] != receipt["source_commit"]:
            raise LivePostCutoverFinalizationError(
                "active cutover source identity changed after acceptance"
            )
        if selected != record["new_hub_root_id"]:
            raise LivePostCutoverFinalizationError(
                "selector is no longer exact NEW after acceptance"
            )
        if (
            _sha256_bytes(selected.encode("utf-8"))
            != receipt["selector_identity_sha256"]
        ):
            raise LivePostCutoverFinalizationError(
                "selector identity hash changed after acceptance"
            )
        terminal = switch._load_terminal(record_raw, record)
        if terminal is not None and terminal["outcome"] != "ACCEPTED":
            raise LivePostCutoverFinalizationError(
                "opposite terminal cutover decision already exists"
            )


def _verify_terminal_recovery(
    switch: hub_cutover.HubSelectorCutover,
    receipt: dict[str, Any],
) -> None:
    txid = receipt["transaction_id"]
    history_path = switch.history_root / f"{txid}.json"
    terminal_path = switch.terminal_root / f"{txid}.json"
    if (
        history_path.is_symlink()
        or terminal_path.is_symlink()
        or not history_path.is_file()
        or not terminal_path.is_file()
    ):
        raise LivePostCutoverFinalizationError(
            "accepted cutover recovery authority is incomplete"
        )
    record_raw = history_path.read_bytes()
    record = hub_cutover._parse_record(record_raw)
    terminal = hub_cutover._parse_terminal(
        terminal_path.read_bytes(), record_raw, record
    )
    if record["transaction_id"] != txid:
        raise LivePostCutoverFinalizationError(
            "accepted cutover history transaction mismatch"
        )
    if _sha256_bytes(record_raw) != receipt["active_transaction_sha256"]:
        raise LivePostCutoverFinalizationError(
            "accepted cutover history authority mismatch"
        )
    if record["tool"]["source_commit"] != receipt["source_commit"]:
        raise LivePostCutoverFinalizationError(
            "accepted cutover history source mismatch"
        )
    if record["tool"] != switch.tool_identity:
        raise LivePostCutoverFinalizationError(
            "accepted cutover history tool identity does not match current finalizer tool"
        )
    if terminal["outcome"] != "ACCEPTED":
        raise LivePostCutoverFinalizationError(
            "accepted cutover recovery terminal is not ACCEPTED"
        )
    selected, _ = hub_cutover._read_selector(switch.selector_path)
    if selected != record["new_hub_root_id"]:
        raise LivePostCutoverFinalizationError(
            "accepted cutover recovery selector is not exact NEW"
        )
    if _sha256_bytes(selected.encode("utf-8")) != receipt["selector_identity_sha256"]:
        raise LivePostCutoverFinalizationError(
            "accepted cutover recovery selector hash mismatch"
        )


def _public_result(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source_commit": receipt["source_commit"],
        "active_transaction_sha256": receipt["active_transaction_sha256"],
        "acceptance_evidence_sha256": receipt["acceptance_evidence_sha256"],
        "pre_apply_receipt_sha256": receipt["pre_apply_receipt_sha256"],
        "selector_identity_sha256": receipt["selector_identity_sha256"],
        "outcome": "PRODUCTION_CUTOVER_ACCEPTED",
        "drive_mutations_performed": False,
        "hub_cutover_terminal_outcome": "ACCEPTED",
    }


def _render_sanitized(
    value: dict[str, Any],
    forbidden: tuple[str, ...],
) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if any(secret and secret in rendered for secret in forbidden):
        raise LivePostCutoverFinalizationError(
            "sanitized post-cutover output leaked private identity/path"
        )
    return rendered


def main() -> int:
    phase = "preflight"
    forbidden: tuple[str, ...] = ()
    try:
        if _required("KEELARYN_POST_CUTOVER_ACCEPTANCE_ENABLE") != "YES":
            raise LivePostCutoverFinalizationError(
                "post-cutover production acceptance is not explicitly enabled"
            )

        selector_path = _path("KEELARYN_HUB_SELECTOR_PATH")
        state_root = _path("KEELARYN_DEPLOYMENT_STATE_ROOT")
        mutation_gate_root = _path("KEELARYN_MUTATION_GATE_ROOT")
        source_commit = _required("KEELARYN_SOURCE_COMMIT")
        receipt_path = _path("KEELARYN_POST_CUTOVER_FINALIZATION_RECEIPT")
        pre_apply_receipt_path = _path("KEELARYN_PRE_APPLY_CUTOVER_RECEIPT")
        pack_dir = _path("KEELARYN_MIGRATION_PACK_DIR")
        freeze_receipt = _path("KEELARYN_MIGRATION_FREEZE_RECEIPT")
        repo_root = _path("KEELARYN_MIGRATION_REPO_ROOT")
        target_authority = _path("KEELARYN_MIGRATION_TARGET_AUTHORITY")
        qualification_evidence = _path(
            "KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE"
        )

        forbidden = (
            str(selector_path),
            str(state_root),
            str(mutation_gate_root),
            str(receipt_path),
            str(pre_apply_receipt_path),
            str(pack_dir),
            str(freeze_receipt),
            str(repo_root),
            str(target_authority),
            str(qualification_evidence),
        )

        pre_apply_receipt = strict_pre_apply_receipt(pre_apply_receipt_path)
        pre_apply_receipt_sha256 = _sha256_bytes(pre_apply_receipt_path.read_bytes())

        switch = hub_cutover.HubSelectorCutover(
            selector_path,
            state_root,
            source_commit,
            mutation_gate_root=mutation_gate_root,
            executing_tool=Path(hub_cutover.__file__),
        )
        status = switch.status()

        if status.get("status") in {"IDLE", "INHIBITED_IDLE"}:
            phase = "terminal-recovery"
            receipt = _strict_receipt(receipt_path)
            if receipt["pre_apply_receipt_sha256"] != pre_apply_receipt_sha256:
                raise LivePostCutoverFinalizationError(
                    "finalization receipt pre-apply provenance mismatch"
                )
            _verify_terminal_recovery(switch, receipt)
            phase = "mutation-inhibit-release"
            switch.release_mutation_inhibit_after_accept(
                receipt["transaction_id"],
                receipt["active_transaction_sha256"],
                allow_absent=status.get("status") == "IDLE",
            )
            if switch.status() != {"status": "IDLE"}:
                raise LivePostCutoverFinalizationError(
                    "accepted recovery did not release production mutation inhibit"
                )
            print(_render_sanitized(_public_result(receipt), forbidden), flush=True)
            return 0

        if status.get("status") == "FINALIZE_PENDING":
            phase = "terminal-recovery"
            receipt = _strict_receipt(receipt_path)
            if receipt["pre_apply_receipt_sha256"] != pre_apply_receipt_sha256:
                raise LivePostCutoverFinalizationError(
                    "finalization receipt pre-apply provenance mismatch"
                )
            _verify_receipt_against_active(switch, receipt)
            result = switch.accept(
                expected_active_transaction_sha256=receipt["active_transaction_sha256"]
            )
            if result.get("status") != "INHIBITED_IDLE":
                raise LivePostCutoverFinalizationError(
                    "terminal recovery did not retain production mutation inhibit"
                )
            _verify_terminal_recovery(switch, receipt)
            phase = "mutation-inhibit-release"
            switch.release_mutation_inhibit_after_accept(
                receipt["transaction_id"],
                receipt["active_transaction_sha256"],
            )
            if switch.status() != {"status": "IDLE"}:
                raise LivePostCutoverFinalizationError(
                    "terminal recovery did not release production mutation inhibit"
                )
            print(_render_sanitized(_public_result(receipt), forbidden), flush=True)
            return 0

        if status.get("status") != "APPLIED":
            raise LivePostCutoverFinalizationError(
                "post-cutover finalization requires exact APPLIED cutover transaction"
            )

        phase = "transaction-binding"
        record_raw, record, selected_hub_root_id = _active_binding(switch)
        _verify_pre_apply_against_record(pre_apply_receipt, record_raw, record)
        forbidden = forbidden + (
            selected_hub_root_id,
            record["old_hub_root_id"],
            record["new_hub_root_id"],
            record["transaction_id"],
        )

        phase = "oauth"
        token_provider = GoogleOAuthRefreshTokenProvider.from_environment()
        drive = GoogleDriveBackend(token_provider)

        phase = "read-only-acceptance"
        acceptance = DriveMigrationPostCutoverReadOnlyAcceptance(
            drive, selected_hub_root_id
        ).run(
            pack_dir,
            freeze_receipt,
            repo_root,
            target_authority,
            qualification_evidence,
        )
        acceptance_value = acceptance.to_json_value()
        _verify_pre_apply_against_acceptance(
            pre_apply_receipt,
            acceptance_value,
        )
        receipt_value = _receipt_for(
            record_raw,
            record,
            selected_hub_root_id,
            acceptance_value,
            pre_apply_receipt_sha256,
        )

        phase = "private-receipt"
        receipt = _write_or_verify_receipt(receipt_path, receipt_value)

        phase = "commit-boundary-revalidation"
        _verify_receipt_against_active(switch, receipt)

        phase = "legacy-source-revalidation"
        verify_migration_source_against_drive(
            drive,
            record["old_hub_root_id"],
            pack_dir / "authority" / MIGRATION_SOURCE_NAME,
        )

        phase = "terminal-commit-boundary-revalidation"
        _verify_receipt_against_active(switch, receipt)

        phase = "terminal-accept"
        result = switch.accept(
            expected_active_transaction_sha256=receipt["active_transaction_sha256"]
        )
        if result.get("status") != "INHIBITED_IDLE":
            raise LivePostCutoverFinalizationError(
                "Hub cutover terminal acceptance did not retain production mutation inhibit"
            )

        phase = "terminal-verification"
        _verify_terminal_recovery(switch, receipt)

        phase = "mutation-inhibit-release"
        switch.release_mutation_inhibit_after_accept(
            receipt["transaction_id"],
            receipt["active_transaction_sha256"],
        )
        if switch.status() != {"status": "IDLE"}:
            raise LivePostCutoverFinalizationError(
                "terminal acceptance did not release production mutation inhibit"
            )

        print(_render_sanitized(_public_result(receipt), forbidden), flush=True)
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.migration-post-cutover-live-failure.v1",
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
