from __future__ import annotations

from dataclasses import dataclass

from .drive_backend import (
    DriveBackend,
    DriveItem,
    DriveNotFound,
    DriveTransportError,
    DriveUncertainMutation,
)
from .drive_bundle import DriveBundleBlocked, DriveBundleStore, DriveTransactionBundle
from .drive_change import DriveChangeRunner
from .drive_execution_rollback import (
    DriveExecutionRollbackBlocked,
    DriveExecutionRollbackMarker,
)
from .drive_master import (
    DriveMasterRecoveryBlocked,
    DriveMasterTransition,
    MASTER_NAME,
)
from .drive_postcheck import DrivePostcheckBlocked, DrivePostcheckReceipts
from .drive_snapshot import DriveSnapshotBlocked, DriveSnapshotter
from .drive_transaction import DrivePublicationTransaction, DriveRecoveryBlocked, BlobState
from .protocol import ProtocolError


class DriveCoreBlocked(ProtocolError):
    """Outer Drive Core observed a state it must not repair automatically."""


@dataclass(frozen=True)
class DriveCoreStatus:
    phase: str
    detail: str

    @property
    def terminal(self) -> bool:
        return self.phase in {"WAIT_POSTCHECK", "COMMITTED", "ROLLED_BACK", "ABORTED_SAFE"}


class DriveCoreRunner:
    """State-derived Drive transaction orchestrator.

    No mutable progress counter exists. Every invocation revalidates the immutable
    transaction bundle and derives progress from exact MASTER/object identities,
    canonical operation states, snapshot copies and immutable decision markers.
    """

    def __init__(self, drive: DriveBackend, bundle: DriveTransactionBundle):
        self.drive = drive
        self.bundle = bundle

    def _get_live(self, file_id: str) -> DriveItem | None:
        try:
            return self.drive.get(file_id, include_trashed=False)
        except DriveNotFound:
            return None

    def _verify_exact_blob(self, item: DriveItem, raw: bytes, *, parent_id: str, name: str) -> None:
        state = BlobState.from_bytes(raw)
        if (
            item.parent_id != parent_id
            or item.name != name
            or item.is_folder
            or item.trashed
            or not state.matches(item)
            or self.drive.download(item.file_id) != raw
        ):
            raise DriveCoreBlocked(f"known Drive object changed: {item.file_id}")

    def _root_item(self) -> DriveItem | None:
        matches = self.drive.list_children(self.bundle.hub_root_id, name=MASTER_NAME)
        if len(matches) > 1:
            raise DriveCoreBlocked("multiple root MASTER.json objects")
        return matches[0] if matches else None

    def _phase_with_root(self, root: DriveItem) -> str:
        b = self.bundle
        known = {
            b.activate_binding.old_master_id: ("BASE_READY", b.starting_ready_master_component.raw),
            b.activate_binding.candidate_master_id: ("ACTIVE_SAFE", b.active_safe_master_component.raw),
            b.unsafe_binding.candidate_master_id: ("ACTIVE_UNSAFE", b.active_unsafe_master_component.raw),
            b.commit_binding.candidate_master_id: ("COMMITTED", b.committed_master_component.raw),
            b.rollback_binding.candidate_master_id: ("ROLLED_BACK", b.rolled_back_master_component.raw),
        }
        match = known.get(root.file_id)
        if match is None:
            raise DriveCoreBlocked(f"unknown object occupies root MASTER.json: {root.file_id}")
        phase, raw = match
        self._verify_exact_blob(root, raw, parent_id=b.hub_root_id, name=MASTER_NAME)
        if phase == "BASE_READY":
            activation_state = DriveMasterTransition(self.drive, b.activate_binding).classify()
            if activation_state == "OLD_ROLLED_BACK":
                return "ABORTED_SAFE"
            if activation_state not in {"OLD_UNPREPARED", "OLD_PREPARED"}:
                raise DriveCoreBlocked(f"base READY has inconsistent activation state: {activation_state}")
        return phase

    def _gap_transition(self) -> tuple[str, DriveMasterTransition, str]:
        b = self.bundle
        transitions = (
            ("activate", DriveMasterTransition(self.drive, b.activate_binding)),
            ("unsafe", DriveMasterTransition(self.drive, b.unsafe_binding)),
            ("commit", DriveMasterTransition(self.drive, b.commit_binding)),
            ("rollback", DriveMasterTransition(self.drive, b.rollback_binding)),
        )
        matches: list[tuple[str, DriveMasterTransition, str]] = []
        for name, transition in transitions:
            state = transition.classify()
            if state in {"OLD_DISPLACED", "NEW_REJECTED"}:
                matches.append((name, transition, state))
        if len(matches) != 1:
            raise DriveCoreBlocked(f"zero-MASTER gap is not uniquely recoverable: {[m[0] + ':' + m[2] for m in matches]}")
        return matches[0]

    def phase(self) -> str:
        root = self._root_item()
        if root is not None:
            return self._phase_with_root(root)
        name, _, state = self._gap_transition()
        return f"GAP_{name.upper()}_{state}"

    def _recover_master_gap(self) -> DriveCoreStatus:
        self._bundle_required()
        name, transition, state = self._gap_transition()

        if name == "activate":
            if state == "NEW_REJECTED":
                transition.rollback()
                return DriveCoreStatus("PROGRESSED", "completed SAFE activation rollback gap")
            if state != "OLD_DISPLACED":
                raise DriveCoreBlocked(f"unexpected activation MASTER gap state: {state}")
            transition.publish()
            return DriveCoreStatus("PROGRESSED", "completed activation MASTER publication gap")

        if state != "OLD_DISPLACED":
            raise DriveCoreBlocked(f"unexpected {name} MASTER gap state: {state}")

        if name == "unsafe":
            # Canonical writes have not started yet. Repeat the complete fresh
            # pre-UNSAFE proof before publishing the UNSAFE MASTER candidate.
            self._preunsafe_validate()
            transition.publish()
            return DriveCoreStatus("PROGRESSED", "completed ENTER_UNSAFE MASTER publication gap")

        self._postunsafe_verify()
        change_status = DriveChangeRunner(self.drive, self.bundle.control).status()
        receipts = DrivePostcheckReceipts(self.drive, self.bundle.postcheck_binding)
        decision = receipts.decision()
        execution_active = DriveExecutionRollbackMarker(
            self.drive, self.bundle.execution_rollback_binding
        ).active()

        if name == "commit":
            if not change_status.all_new or decision != "PASS" or execution_active:
                raise DriveCoreBlocked(
                    f"commit MASTER gap lacks exact PASS/all-NEW authority: states={change_status.states} decision={decision} execution={execution_active}"
                )
            transition.publish()
            return DriveCoreStatus("PROGRESSED", "completed COMMITTED MASTER publication gap")

        if name == "rollback":
            if not change_status.all_old or decision == "PASS" or not (decision == "FAIL" or execution_active):
                raise DriveCoreBlocked(
                    f"rollback MASTER gap lacks exact rollback/all-OLD authority: states={change_status.states} decision={decision} execution={execution_active}"
                )
            transition.publish()
            return DriveCoreStatus("PROGRESSED", "completed ROLLED_BACK MASTER publication gap")

        raise DriveCoreBlocked(f"unsupported MASTER gap transition: {name}")

    def _require_folder(self, file_id: str, label: str) -> None:
        item = self._get_live(file_id)
        if item is None or item.trashed or not item.is_folder:
            raise DriveCoreBlocked(f"required Drive folder missing/invalid: {label}={file_id}")

    def _verify_structural_folders(self, *, include_external_postcheck: bool) -> None:
        b = self.bundle
        control = b.control
        post = b.postcheck_binding
        execution = b.execution_rollback_binding
        ids = {
            "hub_root": b.hub_root_id,
            "canonical_root": control.canonical_root_id,
            "history_original": control.history_original_parent_id,
            "rejected": control.rejected_parent_id,
            "bundle_parent": b.bundle_parent_id,
            "snapshot_parent": b.snapshot_plan.snapshot_parent_id,
            "master_transition_parent": b.master_transition_parent_id,
            "postcheck_receipt_parent": post.receipt_parent_id,
            "execution_marker_parent": execution.marker_parent_id,
        }
        if include_external_postcheck:
            ids["postcheck_source_parent"] = post.source_parent_id
        for label, file_id in ids.items():
            self._require_folder(file_id, label)

    def _bundle_required(self) -> None:
        try:
            DriveBundleStore(self.drive, self.bundle).verify()
        except DriveBundleBlocked as exc:
            raise DriveCoreBlocked(str(exc)) from exc

    def _ensure_bundle_before_activation(self) -> None:
        try:
            DriveBundleStore(self.drive, self.bundle).ensure()
        except DriveBundleBlocked as exc:
            raise DriveCoreBlocked(str(exc)) from exc

    def _preunsafe_validate(self) -> None:
        self._bundle_required()
        self._verify_structural_folders(include_external_postcheck=True)
        b = self.bundle
        control = b.control
        tx = DrivePublicationTransaction(
            self.drive,
            control.history_original_parent_id,
            control.rejected_parent_id,
        )
        for op in control.operations:
            state = tx.classify(op)
            if state != "OLD":
                raise DriveCoreBlocked(f"pre-UNSAFE operation {op.operation_id} is {state}, expected OLD")
            tx.capture_old_identity(op)
            tx.verify_staged_new(op)

        snapshots = DriveSnapshotter(self.drive, b.snapshot_plan)
        snapshots.ensure_all()
        snapshots.verify_all()

        # Fresh commit-boundary pass after all failure-prone snapshot work.
        for op in control.operations:
            state = tx.classify(op)
            if state != "OLD":
                raise DriveCoreBlocked(f"fresh pre-UNSAFE operation {op.operation_id} is {state}, expected OLD")
            tx.capture_old_identity(op)
            tx.verify_staged_new(op)
        snapshots.verify_all()
        self._verify_structural_folders(include_external_postcheck=True)
        self._bundle_required()

    def _postunsafe_verify(self) -> None:
        self._bundle_required()
        # Once UNSAFE begins, only Core-owned recovery structure is required.
        # The external Reconciliation postcheck source is not authority after a
        # decision-bound receipt exists, and its later removal must not block
        # commit/rollback recovery.
        self._verify_structural_folders(include_external_postcheck=False)
        try:
            DriveSnapshotter(self.drive, self.bundle.snapshot_plan).verify_copies()
        except DriveSnapshotBlocked as exc:
            raise DriveCoreBlocked(str(exc)) from exc

    def _abort_safe(self, reason: str) -> DriveCoreStatus:
        transition = DriveMasterTransition(self.drive, self.bundle.activate_binding)
        try:
            transition.rollback()
        except DriveMasterRecoveryBlocked as exc:
            raise DriveCoreBlocked(f"SAFE abort could not restore starting MASTER: {exc}") from exc
        return DriveCoreStatus("ABORTED_SAFE", reason)

    def _activate(self) -> DriveCoreStatus:
        self._ensure_bundle_before_activation()
        self._verify_structural_folders(include_external_postcheck=True)
        transition = DriveMasterTransition(self.drive, self.bundle.activate_binding)
        transition.prepare_candidate(self.bundle.active_safe_master_component.raw)
        transition.publish()
        return DriveCoreStatus("PROGRESSED", "published ACTIVE/SAFE MASTER")

    def _enter_unsafe(self) -> DriveCoreStatus:
        transition = DriveMasterTransition(self.drive, self.bundle.unsafe_binding)
        transition.prepare_candidate(self.bundle.active_unsafe_master_component.raw)
        transition.publish()
        return DriveCoreStatus("PROGRESSED", "published ACTIVE/UNSAFE MASTER")

    def _final_candidate_conflict(self, wanted: str) -> None:
        b = self.bundle
        commit_item = self._get_live(b.commit_binding.candidate_master_id)
        rollback_item = self._get_live(b.rollback_binding.candidate_master_id)
        if wanted == "commit" and rollback_item is not None:
            raise DriveCoreBlocked("rollback READY MASTER candidate exists during PASS finalization")
        if wanted == "rollback" and commit_item is not None:
            raise DriveCoreBlocked("commit READY MASTER candidate exists during rollback finalization")

    def _finalize_commit(self) -> DriveCoreStatus:
        self._postunsafe_verify()
        status = DriveChangeRunner(self.drive, self.bundle.control).status()
        if not status.all_new:
            raise DriveCoreBlocked(f"PASS finalization requires all NEW, observed {status.states}")
        receipts = DrivePostcheckReceipts(self.drive, self.bundle.postcheck_binding)
        if receipts.decision() != "PASS":
            raise DriveCoreBlocked("commit finalization lacks exact PASS authority")
        if DriveExecutionRollbackMarker(self.drive, self.bundle.execution_rollback_binding).active():
            raise DriveCoreBlocked("PASS authority conflicts with execution rollback authority")
        self._final_candidate_conflict("commit")
        transition = DriveMasterTransition(self.drive, self.bundle.commit_binding)
        transition.prepare_candidate(self.bundle.committed_master_component.raw)
        transition.publish()
        return DriveCoreStatus("COMMITTED", "published final COMMITTED READY MASTER")

    def _finalize_rollback(self, *, semantic_fail: bool) -> DriveCoreStatus:
        self._postunsafe_verify()
        status = DriveChangeRunner(self.drive, self.bundle.control).status()
        if not status.all_old:
            raise DriveCoreBlocked(f"rollback finalization requires all OLD, observed {status.states}")
        receipts = DrivePostcheckReceipts(self.drive, self.bundle.postcheck_binding)
        execution = DriveExecutionRollbackMarker(self.drive, self.bundle.execution_rollback_binding)
        decision = receipts.decision()
        execution_active = execution.active()
        if semantic_fail:
            if decision != "FAIL":
                raise DriveCoreBlocked("semantic rollback finalization lacks exact FAIL authority")
        elif not execution_active:
            raise DriveCoreBlocked("execution rollback finalization lacks rollback marker")
        if decision == "PASS":
            raise DriveCoreBlocked("rollback authority conflicts with PASS receipt")
        self._final_candidate_conflict("rollback")
        transition = DriveMasterTransition(self.drive, self.bundle.rollback_binding)
        transition.prepare_candidate(self.bundle.rolled_back_master_component.raw)
        transition.publish()
        return DriveCoreStatus("ROLLED_BACK", "published final ROLLED_BACK READY MASTER")

    def _unsafe_step(self) -> DriveCoreStatus:
        self._postunsafe_verify()
        b = self.bundle
        change = DriveChangeRunner(self.drive, b.control)
        receipts = DrivePostcheckReceipts(self.drive, b.postcheck_binding)
        execution = DriveExecutionRollbackMarker(self.drive, b.execution_rollback_binding)

        decision = receipts.decision()
        execution_active = execution.active()
        if decision == "PASS" and execution_active:
            raise DriveCoreBlocked("PASS receipt conflicts with execution rollback marker")

        if decision == "FAIL" or execution_active:
            try:
                change.rollback_all()
            except DriveRecoveryBlocked as exc:
                raise DriveCoreBlocked(str(exc)) from exc
            return self._finalize_rollback(semantic_fail=decision == "FAIL")

        status = change.status()
        if decision == "PASS":
            if not status.all_new:
                raise DriveCoreBlocked(f"PASS receipt exists while canonical is not all NEW: {status.states}")
            return self._finalize_commit()

        if not status.all_new:
            try:
                change.apply_all()
            except (DriveUncertainMutation, DriveTransportError):
                raise
            except DriveRecoveryBlocked as exc:
                raise DriveCoreBlocked(str(exc)) from exc
            except ProtocolError as exc:
                # A deterministic execution failure becomes durable rollback
                # authority only if actual target states remain classifiable and
                # independent snapshots are still exact.
                self._postunsafe_verify()
                observed = change.status()
                if observed.has_unknown:
                    raise DriveCoreBlocked(f"execution failure left UNKNOWN state: {observed.states}") from exc
                execution.record(str(exc))
                return DriveCoreStatus("PROGRESSED", "recorded deterministic execution rollback authority")
            status = change.status()
            if not status.all_new:
                raise DriveCoreBlocked(f"apply completed without all NEW: {status.states}")

        decision = receipts.accept()
        if decision is None:
            return DriveCoreStatus("WAIT_POSTCHECK", "all operations NEW; no accepted semantic decision")
        if decision == "PASS":
            return self._finalize_commit()
        if decision == "FAIL":
            change.rollback_all()
            return self._finalize_rollback(semantic_fail=True)
        raise DriveCoreBlocked(f"unexpected accepted decision: {decision}")

    def run_once(self) -> DriveCoreStatus:
        try:
            phase = self.phase()
            if phase.startswith("GAP_"):
                return self._recover_master_gap()
            if phase == "ABORTED_SAFE":
                return DriveCoreStatus("ABORTED_SAFE", "pre-UNSAFE activation was rolled back")
            if phase == "COMMITTED":
                self._bundle_required()
                return DriveCoreStatus("COMMITTED", "final COMMITTED READY MASTER already present")
            if phase == "ROLLED_BACK":
                self._bundle_required()
                return DriveCoreStatus("ROLLED_BACK", "final ROLLED_BACK READY MASTER already present")
            if phase == "BASE_READY":
                return self._activate()
            if phase == "ACTIVE_SAFE":
                try:
                    self._preunsafe_validate()
                except (DriveUncertainMutation, DriveTransportError):
                    raise
                except (DriveCoreBlocked, DriveSnapshotBlocked, DriveRecoveryBlocked, ProtocolError) as exc:
                    return self._abort_safe(str(exc))
                return self._enter_unsafe()
            if phase == "ACTIVE_UNSAFE":
                return self._unsafe_step()
            raise DriveCoreBlocked(f"unsupported outer Drive phase: {phase}")
        except (DriveUncertainMutation, DriveTransportError):
            raise
        except DriveCoreBlocked:
            raise
        except (
            DriveBundleBlocked,
            DriveSnapshotBlocked,
            DrivePostcheckBlocked,
            DriveExecutionRollbackBlocked,
            DriveMasterRecoveryBlocked,
            DriveRecoveryBlocked,
        ) as exc:
            raise DriveCoreBlocked(str(exc)) from exc

    def run_until_quiescent(self, *, max_steps: int = 32) -> DriveCoreStatus:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        last = DriveCoreStatus("PROGRESSED", "not started")
        for _ in range(max_steps):
            last = self.run_once()
            if last.terminal:
                return last
        raise DriveCoreBlocked(f"Drive Core did not quiesce within {max_steps} state-derived steps; last={last}")


__all__ = ["DriveCoreBlocked", "DriveCoreRunner", "DriveCoreStatus"]
