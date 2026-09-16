from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .drive_control import DriveControl
from .drive_execution_rollback import DriveExecutionRollbackBinding
from .drive_master import DriveMasterBinding, DriveMasterTransition
from .drive_postcheck import DrivePostcheckBinding
from .drive_recovery_block import DriveRecoveryBlockBinding
from .drive_snapshot import DriveSnapshotPlan
from .drive_transaction import BlobState
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes, validate_master


SCHEMA = "keelaryn.drive-transaction-bundle.v1"


class DriveBundleBlocked(ProtocolError):
    """The immutable Drive transaction bundle cannot be proven internally exact."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ProtocolError(f"{label}: invalid string")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ProtocolError(f"{label}: invalid sha256")
    return value


def _epoch(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProtocolError(f"{label}: invalid epoch")
    return value


@dataclass(frozen=True)
class ExactJsonComponent:
    raw: bytes

    @property
    def sha256(self) -> str:
        return sha256(self.raw).hexdigest()

    @property
    def size(self) -> int:
        return len(self.raw)

    def to_json(self) -> dict[str, Any]:
        try:
            text = self.raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("bundle JSON component is not UTF-8") from exc
        return {"sha256": self.sha256, "size": self.size, "text": text}

    @classmethod
    def from_json(cls, value: Any, label: str) -> "ExactJsonComponent":
        if not isinstance(value, dict) or set(value) != {"sha256", "size", "text"}:
            raise ProtocolError(f"{label}: invalid exact component")
        digest = _sha(value["sha256"], f"{label}.sha256")
        size = value["size"]
        text = value["text"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ProtocolError(f"{label}.size: invalid size")
        if not isinstance(text, str):
            raise ProtocolError(f"{label}.text: expected string")
        raw = text.encode("utf-8")
        if len(raw) != size or sha256(raw).hexdigest() != digest:
            raise DriveBundleBlocked(f"{label}: exact bytes do not match bound fingerprint")
        return cls(raw)


@dataclass(frozen=True)
class DriveTransactionBundle:
    change_id: str
    change_sha256: str
    base_canonical_epoch: int
    hub_root_id: str
    bundle_parent_id: str
    bundle_file_id: str
    master_transition_parent_id: str
    control_component: ExactJsonComponent
    snapshot_component: ExactJsonComponent
    postcheck_component: ExactJsonComponent
    execution_rollback_component: ExactJsonComponent
    recovery_block_component: ExactJsonComponent
    starting_ready_master_component: ExactJsonComponent
    activate_binding_component: ExactJsonComponent
    active_safe_master_component: ExactJsonComponent
    unsafe_binding_component: ExactJsonComponent
    active_unsafe_master_component: ExactJsonComponent
    commit_binding_component: ExactJsonComponent
    committed_master_component: ExactJsonComponent
    rollback_binding_component: ExactJsonComponent
    rolled_back_master_component: ExactJsonComponent
    blocked_binding_component: ExactJsonComponent
    blocked_master_component: ExactJsonComponent

    @property
    def bundle_name(self) -> str:
        return f"{self.change_id}.DRIVE_BUNDLE.json"

    @property
    def control(self) -> DriveControl:
        return DriveControl.from_bytes(self.control_component.raw)

    @property
    def snapshot_plan(self) -> DriveSnapshotPlan:
        return DriveSnapshotPlan.from_bytes(self.snapshot_component.raw)

    @property
    def postcheck_binding(self) -> DrivePostcheckBinding:
        return DrivePostcheckBinding.from_bytes(self.postcheck_component.raw)

    @property
    def execution_rollback_binding(self) -> DriveExecutionRollbackBinding:
        return DriveExecutionRollbackBinding.from_bytes(self.execution_rollback_component.raw)

    @property
    def recovery_block_binding(self) -> DriveRecoveryBlockBinding:
        return DriveRecoveryBlockBinding.from_bytes(self.recovery_block_component.raw)

    @property
    def activate_binding(self) -> DriveMasterBinding:
        return DriveMasterBinding.from_bytes(self.activate_binding_component.raw)

    @property
    def unsafe_binding(self) -> DriveMasterBinding:
        return DriveMasterBinding.from_bytes(self.unsafe_binding_component.raw)

    @property
    def commit_binding(self) -> DriveMasterBinding:
        return DriveMasterBinding.from_bytes(self.commit_binding_component.raw)

    @property
    def rollback_binding(self) -> DriveMasterBinding:
        return DriveMasterBinding.from_bytes(self.rollback_binding_component.raw)

    @property
    def blocked_binding(self) -> DriveMasterBinding:
        return DriveMasterBinding.from_bytes(self.blocked_binding_component.raw)

    @classmethod
    def plan(
        cls,
        drive: DriveBackend,
        *,
        change_sha256: str,
        base_canonical_epoch: int,
        bundle_parent_id: str,
        master_transition_parent_id: str,
        control: DriveControl,
        snapshot_plan: DriveSnapshotPlan,
        postcheck_binding: DrivePostcheckBinding,
        execution_rollback_binding: DriveExecutionRollbackBinding,
        active_safe_master_bytes: bytes,
        active_unsafe_master_bytes: bytes,
        committed_master_bytes: bytes,
        rolled_back_master_bytes: bytes,
    ) -> "DriveTransactionBundle":
        change_sha256 = _sha(change_sha256, "change_sha256")
        base_canonical_epoch = _epoch(base_canonical_epoch, "base_canonical_epoch")
        current_item, current_raw = DriveMasterTransition.read_unique_master(drive, control.hub_root_id)
        current_master = validate_master(strict_json_bytes(current_raw, label="MASTER.ready"))
        if (
            current_master["state"] != "READY"
            or current_master["canonical_read_status"] != "SAFE"
            or current_master["canonical_epoch"] != base_canonical_epoch
        ):
            raise ProtocolError("bundle planning requires exact READY/SAFE base MASTER")

        active_unsafe_value = validate_master(
            strict_json_bytes(bytes(active_unsafe_master_bytes), label="MASTER.active_unsafe")
        )
        blocked_value = dict(active_unsafe_value)
        blocked_value["state"] = "RECOVERY_BLOCKED"
        blocked_value["canonical_read_status"] = "UNSAFE"
        blocked_value["current_stage"] = "RECOVERY_BLOCKED"
        blocked_raw = canonical_json_bytes(blocked_value)

        master_raws = {
            "active_safe": bytes(active_safe_master_bytes),
            "active_unsafe": bytes(active_unsafe_master_bytes),
            "committed": bytes(committed_master_bytes),
            "rolled_back": bytes(rolled_back_master_bytes),
            "blocked": blocked_raw,
        }
        for label, raw in master_raws.items():
            validate_master(strict_json_bytes(raw, label=f"MASTER.{label}"))

        recovery_block_binding = DriveRecoveryBlockBinding.plan(
            drive,
            change_id=control.change_id,
            change_sha256=change_sha256,
            base_canonical_epoch=base_canonical_epoch,
            record_parent_id=execution_rollback_binding.marker_parent_id,
        )

        reserved = drive.generate_ids(6)
        bundle_file_id, active_safe_id, active_unsafe_id, committed_id, rolled_back_id, blocked_id = reserved
        ready_state = BlobState.from_bytes(current_raw)
        active_safe_state = BlobState.from_bytes(master_raws["active_safe"])
        active_unsafe_state = BlobState.from_bytes(master_raws["active_unsafe"])
        committed_state = BlobState.from_bytes(master_raws["committed"])
        rolled_back_state = BlobState.from_bytes(master_raws["rolled_back"])
        blocked_state = BlobState.from_bytes(master_raws["blocked"])

        activate = DriveMasterBinding(
            transition_id=f"{control.change_id}.activate",
            root_id=control.hub_root_id,
            transition_parent_id=master_transition_parent_id,
            old_master_id=current_item.file_id,
            old_state=ready_state,
            candidate_master_id=active_safe_id,
            new_state=active_safe_state,
        )
        unsafe = DriveMasterBinding(
            transition_id=f"{control.change_id}.unsafe",
            root_id=control.hub_root_id,
            transition_parent_id=master_transition_parent_id,
            old_master_id=active_safe_id,
            old_state=active_safe_state,
            candidate_master_id=active_unsafe_id,
            new_state=active_unsafe_state,
        )
        commit = DriveMasterBinding(
            transition_id=f"{control.change_id}.commit",
            root_id=control.hub_root_id,
            transition_parent_id=master_transition_parent_id,
            old_master_id=active_unsafe_id,
            old_state=active_unsafe_state,
            candidate_master_id=committed_id,
            new_state=committed_state,
        )
        rollback = DriveMasterBinding(
            transition_id=f"{control.change_id}.rollback",
            root_id=control.hub_root_id,
            transition_parent_id=master_transition_parent_id,
            old_master_id=active_unsafe_id,
            old_state=active_unsafe_state,
            candidate_master_id=rolled_back_id,
            new_state=rolled_back_state,
        )
        blocked = DriveMasterBinding(
            transition_id=f"{control.change_id}.blocked",
            root_id=control.hub_root_id,
            transition_parent_id=master_transition_parent_id,
            old_master_id=active_unsafe_id,
            old_state=active_unsafe_state,
            candidate_master_id=blocked_id,
            new_state=blocked_state,
        )

        bundle = cls(
            change_id=control.change_id,
            change_sha256=change_sha256,
            base_canonical_epoch=base_canonical_epoch,
            hub_root_id=control.hub_root_id,
            bundle_parent_id=_text(bundle_parent_id, "bundle_parent_id"),
            bundle_file_id=_text(bundle_file_id, "bundle_file_id"),
            master_transition_parent_id=_text(master_transition_parent_id, "master_transition_parent_id"),
            control_component=ExactJsonComponent(control.to_bytes()),
            snapshot_component=ExactJsonComponent(snapshot_plan.to_bytes()),
            postcheck_component=ExactJsonComponent(postcheck_binding.to_bytes()),
            execution_rollback_component=ExactJsonComponent(execution_rollback_binding.to_bytes()),
            recovery_block_component=ExactJsonComponent(recovery_block_binding.to_bytes()),
            starting_ready_master_component=ExactJsonComponent(current_raw),
            activate_binding_component=ExactJsonComponent(activate.to_bytes()),
            active_safe_master_component=ExactJsonComponent(master_raws["active_safe"]),
            unsafe_binding_component=ExactJsonComponent(unsafe.to_bytes()),
            active_unsafe_master_component=ExactJsonComponent(master_raws["active_unsafe"]),
            commit_binding_component=ExactJsonComponent(commit.to_bytes()),
            committed_master_component=ExactJsonComponent(master_raws["committed"]),
            rollback_binding_component=ExactJsonComponent(rollback.to_bytes()),
            rolled_back_master_component=ExactJsonComponent(master_raws["rolled_back"]),
            blocked_binding_component=ExactJsonComponent(blocked.to_bytes()),
            blocked_master_component=ExactJsonComponent(master_raws["blocked"]),
        )
        bundle.validate_consistency()
        return bundle

    def _master_value(self, component: ExactJsonComponent, label: str) -> dict[str, Any]:
        return validate_master(strict_json_bytes(component.raw, label=label))

    def _require_master_semantics(self) -> None:
        starting = self._master_value(self.starting_ready_master_component, "MASTER.starting_ready")
        active_safe = self._master_value(self.active_safe_master_component, "MASTER.active_safe")
        active_unsafe = self._master_value(self.active_unsafe_master_component, "MASTER.active_unsafe")
        committed = self._master_value(self.committed_master_component, "MASTER.committed")
        rolled_back = self._master_value(self.rolled_back_master_component, "MASTER.rolled_back")
        blocked = self._master_value(self.blocked_master_component, "MASTER.blocked")
        exact_active = {
            "change_id": self.change_id,
            "change_sha256": self.change_sha256,
            "base_canonical_epoch": self.base_canonical_epoch,
        }
        if not (
            starting["state"] == "READY"
            and starting["canonical_read_status"] == "SAFE"
            and starting["canonical_epoch"] == self.base_canonical_epoch
            and starting["active_change"] is None
            and starting["current_stage"] is None
        ):
            raise DriveBundleBlocked("starting READY MASTER component is inconsistent with bundle identity")
        if not (
            active_safe["state"] == "ACTIVE"
            and active_safe["canonical_read_status"] == "SAFE"
            and active_safe["canonical_epoch"] == self.base_canonical_epoch
            and active_safe["active_change"] == exact_active
            and active_safe["current_stage"] == "SNAPSHOT"
            and active_safe["last_completed_change"] == starting["last_completed_change"]
        ):
            raise DriveBundleBlocked("ACTIVE/SAFE MASTER component is inconsistent with bundle identity")
        if not (
            active_unsafe["state"] == "ACTIVE"
            and active_unsafe["canonical_read_status"] == "UNSAFE"
            and active_unsafe["canonical_epoch"] == self.base_canonical_epoch
            and active_unsafe["active_change"] == exact_active
            and active_unsafe["current_stage"] == "APPLY"
            and active_unsafe["last_completed_change"] == active_safe["last_completed_change"]
        ):
            raise DriveBundleBlocked("ACTIVE/UNSAFE MASTER component is inconsistent with bundle identity")
        if not (
            blocked["state"] == "RECOVERY_BLOCKED"
            and blocked["canonical_read_status"] == "UNSAFE"
            and blocked["canonical_epoch"] == self.base_canonical_epoch
            and blocked["active_change"] == exact_active
            and blocked["current_stage"] == "RECOVERY_BLOCKED"
            and blocked["last_completed_change"] == active_unsafe["last_completed_change"]
        ):
            raise DriveBundleBlocked("RECOVERY_BLOCKED MASTER component is inconsistent with bundle identity")
        for value, outcome, label in (
            (committed, "COMMITTED", "COMMITTED"),
            (rolled_back, "ROLLED_BACK", "ROLLED_BACK"),
        ):
            expected_completed = {
                "change_id": self.change_id,
                "change_sha256": self.change_sha256,
                "outcome": outcome,
                "completed_epoch": self.base_canonical_epoch + 1,
            }
            if not (
                value["state"] == "READY"
                and value["canonical_read_status"] == "SAFE"
                and value["canonical_epoch"] == self.base_canonical_epoch + 1
                and value["active_change"] is None
                and value["current_stage"] is None
                and value["last_completed_change"] == expected_completed
            ):
                raise DriveBundleBlocked(f"{label} READY MASTER component is inconsistent with bundle identity")

    def validate_consistency(self) -> None:
        control = self.control
        snapshots = self.snapshot_plan
        postcheck = self.postcheck_binding
        execution_rollback = self.execution_rollback_binding
        recovery_block = self.recovery_block_binding
        activate = self.activate_binding
        unsafe = self.unsafe_binding
        commit = self.commit_binding
        rollback = self.rollback_binding
        blocked = self.blocked_binding

        if control.change_id != self.change_id or control.hub_root_id != self.hub_root_id:
            raise DriveBundleBlocked("DriveControl identity/root mismatch")
        if snapshots.change_id != self.change_id:
            raise DriveBundleBlocked("DriveSnapshotPlan change identity mismatch")
        if (
            postcheck.change_id != self.change_id
            or postcheck.change_sha256 != self.change_sha256
            or postcheck.base_canonical_epoch != self.base_canonical_epoch
        ):
            raise DriveBundleBlocked("DrivePostcheckBinding transaction identity mismatch")
        if (
            execution_rollback.change_id != self.change_id
            or execution_rollback.change_sha256 != self.change_sha256
            or execution_rollback.base_canonical_epoch != self.base_canonical_epoch
        ):
            raise DriveBundleBlocked("execution rollback binding transaction identity mismatch")
        if (
            recovery_block.change_id != self.change_id
            or recovery_block.change_sha256 != self.change_sha256
            or recovery_block.base_canonical_epoch != self.base_canonical_epoch
        ):
            raise DriveBundleBlocked("recovery block binding transaction identity mismatch")

        expected_snapshot_ops = [op for op in control.operations if op.kind in {"REPLACE", "DELETE"}]
        if len(snapshots.entries) != len(expected_snapshot_ops):
            raise DriveBundleBlocked("snapshot plan does not cover exact destructive operation set")
        for entry, op in zip(snapshots.entries, expected_snapshot_ops, strict=True):
            if not (
                entry.operation_id == op.operation_id
                and entry.source_id == op.old_original_id
                and entry.source_parent_id == op.canonical_parent_id
                and entry.source_name == op.target_name
                and entry.source_state == op.old
            ):
                raise DriveBundleBlocked(f"snapshot entry mismatch for operation {op.operation_id}")

        for binding, label in (
            (activate, "activate"),
            (unsafe, "unsafe"),
            (commit, "commit"),
            (rollback, "rollback"),
            (blocked, "blocked"),
        ):
            if binding.root_id != self.hub_root_id or binding.transition_parent_id != self.master_transition_parent_id:
                raise DriveBundleBlocked(f"{label} MASTER binding structural root mismatch")

        starting_state = BlobState.from_bytes(self.starting_ready_master_component.raw)
        if activate.old_state != starting_state:
            raise DriveBundleBlocked("activation binding does not bind exact starting READY MASTER bytes")
        if activate.new_state != BlobState.from_bytes(self.active_safe_master_component.raw):
            raise DriveBundleBlocked("activation binding/candidate fingerprint mismatch")
        if not (
            unsafe.old_master_id == activate.candidate_master_id
            and unsafe.old_state == activate.new_state
            and unsafe.new_state == BlobState.from_bytes(self.active_unsafe_master_component.raw)
        ):
            raise DriveBundleBlocked("UNSAFE MASTER transition does not chain from activation")
        if not (
            commit.old_master_id == unsafe.candidate_master_id
            and rollback.old_master_id == unsafe.candidate_master_id
            and blocked.old_master_id == unsafe.candidate_master_id
            and commit.old_state == unsafe.new_state
            and rollback.old_state == unsafe.new_state
            and blocked.old_state == unsafe.new_state
            and commit.new_state == BlobState.from_bytes(self.committed_master_component.raw)
            and rollback.new_state == BlobState.from_bytes(self.rolled_back_master_component.raw)
            and blocked.new_state == BlobState.from_bytes(self.blocked_master_component.raw)
        ):
            raise DriveBundleBlocked("final/blocked MASTER transitions do not chain from ACTIVE/UNSAFE")

        reserved_ids = [
            self.bundle_file_id,
            activate.candidate_master_id,
            unsafe.candidate_master_id,
            commit.candidate_master_id,
            rollback.candidate_master_id,
            blocked.candidate_master_id,
            postcheck.pass_receipt_id,
            postcheck.fail_receipt_id,
            execution_rollback.marker_id,
            recovery_block.record_id,
            *(entry.snapshot_id for entry in snapshots.entries),
            *(op.staged_new_id for op in control.operations if op.staged_new_id is not None),
        ]
        if len(reserved_ids) != len(set(reserved_ids)):
            raise DriveBundleBlocked("Core-created Drive identities are not globally unique within bundle")
        source_ids = {op.old_original_id for op in control.operations if op.old_original_id is not None}
        if source_ids.intersection(reserved_ids):
            raise DriveBundleBlocked("Core-created identity collides with canonical OLD source identity")

        self._require_master_semantics()

    def to_bytes(self) -> bytes:
        self.validate_consistency()
        return canonical_json_bytes(
            {
                "schema": SCHEMA,
                "change_id": self.change_id,
                "change_sha256": self.change_sha256,
                "base_canonical_epoch": self.base_canonical_epoch,
                "hub_root_id": self.hub_root_id,
                "bundle_parent_id": self.bundle_parent_id,
                "bundle_file_id": self.bundle_file_id,
                "master_transition_parent_id": self.master_transition_parent_id,
                "components": {
                    "control": self.control_component.to_json(),
                    "snapshot": self.snapshot_component.to_json(),
                    "postcheck": self.postcheck_component.to_json(),
                    "execution_rollback": self.execution_rollback_component.to_json(),
                    "recovery_block": self.recovery_block_component.to_json(),
                    "starting_ready_master": self.starting_ready_master_component.to_json(),
                    "activate_binding": self.activate_binding_component.to_json(),
                    "active_safe_master": self.active_safe_master_component.to_json(),
                    "unsafe_binding": self.unsafe_binding_component.to_json(),
                    "active_unsafe_master": self.active_unsafe_master_component.to_json(),
                    "commit_binding": self.commit_binding_component.to_json(),
                    "committed_master": self.committed_master_component.to_json(),
                    "rollback_binding": self.rollback_binding_component.to_json(),
                    "rolled_back_master": self.rolled_back_master_component.to_json(),
                    "blocked_binding": self.blocked_binding_component.to_json(),
                    "blocked_master": self.blocked_master_component.to_json(),
                },
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> "DriveTransactionBundle":
        value = strict_json_bytes(raw, label="DRIVE_TRANSACTION_BUNDLE")
        expected = {
            "schema",
            "change_id",
            "change_sha256",
            "base_canonical_epoch",
            "hub_root_id",
            "bundle_parent_id",
            "bundle_file_id",
            "master_transition_parent_id",
            "components",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ProtocolError("DRIVE_TRANSACTION_BUNDLE: invalid root")
        if value["schema"] != SCHEMA:
            raise ProtocolError("DRIVE_TRANSACTION_BUNDLE.schema: unsupported schema")
        components = value["components"]
        component_names = {
            "control",
            "snapshot",
            "postcheck",
            "execution_rollback",
            "recovery_block",
            "starting_ready_master",
            "activate_binding",
            "active_safe_master",
            "unsafe_binding",
            "active_unsafe_master",
            "commit_binding",
            "committed_master",
            "rollback_binding",
            "rolled_back_master",
            "blocked_binding",
            "blocked_master",
        }
        if not isinstance(components, dict) or set(components) != component_names:
            raise ProtocolError("DRIVE_TRANSACTION_BUNDLE.components: invalid set")
        bundle = cls(
            change_id=_text(value["change_id"], "change_id"),
            change_sha256=_sha(value["change_sha256"], "change_sha256"),
            base_canonical_epoch=_epoch(value["base_canonical_epoch"], "base_canonical_epoch"),
            hub_root_id=_text(value["hub_root_id"], "hub_root_id"),
            bundle_parent_id=_text(value["bundle_parent_id"], "bundle_parent_id"),
            bundle_file_id=_text(value["bundle_file_id"], "bundle_file_id"),
            master_transition_parent_id=_text(value["master_transition_parent_id"], "master_transition_parent_id"),
            control_component=ExactJsonComponent.from_json(components["control"], "components.control"),
            snapshot_component=ExactJsonComponent.from_json(components["snapshot"], "components.snapshot"),
            postcheck_component=ExactJsonComponent.from_json(components["postcheck"], "components.postcheck"),
            execution_rollback_component=ExactJsonComponent.from_json(
                components["execution_rollback"], "components.execution_rollback"
            ),
            recovery_block_component=ExactJsonComponent.from_json(
                components["recovery_block"], "components.recovery_block"
            ),
            starting_ready_master_component=ExactJsonComponent.from_json(
                components["starting_ready_master"], "components.starting_ready_master"
            ),
            activate_binding_component=ExactJsonComponent.from_json(
                components["activate_binding"], "components.activate_binding"
            ),
            active_safe_master_component=ExactJsonComponent.from_json(
                components["active_safe_master"], "components.active_safe_master"
            ),
            unsafe_binding_component=ExactJsonComponent.from_json(
                components["unsafe_binding"], "components.unsafe_binding"
            ),
            active_unsafe_master_component=ExactJsonComponent.from_json(
                components["active_unsafe_master"], "components.active_unsafe_master"
            ),
            commit_binding_component=ExactJsonComponent.from_json(
                components["commit_binding"], "components.commit_binding"
            ),
            committed_master_component=ExactJsonComponent.from_json(
                components["committed_master"], "components.committed_master"
            ),
            rollback_binding_component=ExactJsonComponent.from_json(
                components["rollback_binding"], "components.rollback_binding"
            ),
            rolled_back_master_component=ExactJsonComponent.from_json(
                components["rolled_back_master"], "components.rolled_back_master"
            ),
            blocked_binding_component=ExactJsonComponent.from_json(
                components["blocked_binding"], "components.blocked_binding"
            ),
            blocked_master_component=ExactJsonComponent.from_json(
                components["blocked_master"], "components.blocked_master"
            ),
        )
        bundle.validate_consistency()
        return bundle


class DriveBundleStore:
    def __init__(self, drive: DriveBackend, bundle: DriveTransactionBundle):
        self.drive = drive
        self.bundle = bundle

    def _get_live(self) -> DriveItem | None:
        try:
            return self.drive.get(self.bundle.bundle_file_id, include_trashed=False)
        except DriveNotFound:
            return None

    def verify(self) -> DriveItem:
        item = self._get_live()
        if item is None:
            raise DriveBundleBlocked("transaction bundle object is missing")
        raw = self.bundle.to_bytes()
        expected = BlobState.from_bytes(raw)
        if (
            item.parent_id != self.bundle.bundle_parent_id
            or item.name != self.bundle.bundle_name
            or item.is_folder
            or item.trashed
            or not expected.matches(item)
            or self.drive.download(item.file_id) != raw
        ):
            raise DriveBundleBlocked("transaction bundle object identity/location/bytes mismatch")
        restored = DriveTransactionBundle.from_bytes(raw)
        if restored != self.bundle:
            raise DriveBundleBlocked("transaction bundle roundtrip mismatch")
        return item

    def ensure(self) -> DriveItem:
        existing = self._get_live()
        if existing is not None:
            return self.verify()
        raw = self.bundle.to_bytes()
        try:
            self.drive.create_blob(
                self.bundle.bundle_parent_id,
                self.bundle.bundle_name,
                raw,
                mime_type="application/json",
                file_id=self.bundle.bundle_file_id,
                label=f"drive.bundle.{self.bundle.change_id}.create",
            )
        except DriveAlreadyExists:
            pass
        return self.verify()


__all__ = [
    "DriveBundleBlocked",
    "DriveBundleStore",
    "DriveTransactionBundle",
    "ExactJsonComponent",
]
