from __future__ import annotations

from dataclasses import dataclass

from .drive_backend import DriveBackend
from .drive_control import DriveControl
from .drive_transaction import DrivePublicationTransaction, DriveRecoveryBlocked


@dataclass(frozen=True)
class DriveChangeStatus:
    states: tuple[str, ...]

    @property
    def all_old(self) -> bool:
        return all(state == "OLD" for state in self.states)

    @property
    def all_new(self) -> bool:
        return all(state == "NEW" for state in self.states)

    @property
    def has_unknown(self) -> bool:
        return any(state == "UNKNOWN" for state in self.states)


class DriveChangeRunner:
    """Sequence/recovery layer for one exact DriveControl record.

    The runner has no mutable progress counter. Every call derives progress from
    durable object identities plus actual backend state, mirroring the outer Core
    design where process memory is never recovery evidence.
    """

    def __init__(self, drive: DriveBackend, control: DriveControl):
        self.drive = drive
        self.control = control
        self.tx = DrivePublicationTransaction(
            drive,
            control.history_original_parent_id,
            control.rejected_parent_id,
        )

    def status(self) -> DriveChangeStatus:
        return DriveChangeStatus(tuple(self.tx.classify(op) for op in self.control.operations))

    def apply_all(self) -> DriveChangeStatus:
        for op in self.control.operations:
            state = self.tx.classify(op)
            if state == "NEW":
                continue
            if state not in {"OLD", "OLD_DISPLACED"}:
                raise DriveRecoveryBlocked(
                    f"change {self.control.change_id}: operation {op.operation_id} cannot apply from {state}"
                )
            self.tx.apply(op)
        result = self.status()
        if not result.all_new:
            raise DriveRecoveryBlocked(f"change {self.control.change_id}: apply did not reach all NEW")
        return result

    def rollback_all(self) -> DriveChangeStatus:
        for op in reversed(self.control.operations):
            state = self.tx.classify(op)
            if state == "OLD":
                continue
            if state not in {"NEW", "OLD_DISPLACED", "NEW_REJECTED"}:
                raise DriveRecoveryBlocked(
                    f"change {self.control.change_id}: operation {op.operation_id} cannot rollback from {state}"
                )
            self.tx.rollback(op)
        result = self.status()
        if not result.all_old:
            raise DriveRecoveryBlocked(f"change {self.control.change_id}: rollback did not reach all OLD")
        return result
