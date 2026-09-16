from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .drive_project import PROJECT_STATE_NAME, DriveWorkflowBlocked, _fingerprint, _identifier, _unique_blob, _verify_item_bytes
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes
from .work_state_protocol import OWNER_KINDS, validate_work_state_update, validate_work_state_update_plan

STATE_HISTORY_NAME = "state-history"
STATE_PLAN_NAME = "PLAN.json"
STATE_NEW_NAME = "NEW.md"
STATE_OLD_NAME = "OLD.md"
STATE_DONE_NAME = "DONE.json"


@dataclass(frozen=True)
class DriveWorkState:
    owner_kind: str
    owner_id: str
    owner_folder_id: str
    state_file_id: str
    raw: bytes


@dataclass(frozen=True)
class DriveWorkStateUpdate:
    owner_kind: str
    owner_id: str
    update_id: str
    update_folder_id: str
    plan_file_id: str
    done_file_id: str
    plan_raw: bytes
    done_raw: bytes
    plan: dict[str, Any]
    done: dict[str, Any]


class DriveWorkStateService:
    """Role-neutral copy-on-write STATE.md transition with exact restart recovery."""

    def __init__(
        self,
        drive: DriveBackend,
        *,
        owner_folder_id: str,
        owner_kind: str,
        owner_id: str,
        label_base: str,
    ) -> None:
        if owner_kind not in OWNER_KINDS:
            raise DriveWorkflowBlocked("invalid STATE owner kind")
        self.drive = drive
        self.owner_folder_id = owner_folder_id
        self.owner_kind = owner_kind
        self.owner_id = _identifier(owner_id, "owner_id")
        if not isinstance(label_base, str) or not label_base:
            raise DriveWorkflowBlocked("STATE label_base must be non-empty")
        self.label_base = label_base

    def _owner(self) -> DriveItem:
        try:
            owner = self.drive.get(self.owner_folder_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DriveWorkflowBlocked("STATE owner folder missing") from exc
        if owner.trashed or not owner.is_folder:
            raise DriveWorkflowBlocked("STATE owner is not a live folder")
        if owner.name != self.owner_id:
            raise DriveWorkflowBlocked("STATE owner folder name does not match owner_id")
        return owner

    def read(self) -> DriveWorkState:
        owner = self._owner()
        state = _unique_blob(self.drive, owner.file_id, PROJECT_STATE_NAME, f"{self.owner_kind} {self.owner_id} STATE.md")
        raw = self.drive.download(state.file_id)
        return DriveWorkState(self.owner_kind, self.owner_id, owner.file_id, state.file_id, raw)

    def _history(self, owner: DriveItem, *, create: bool) -> DriveItem:
        matches = self.drive.list_children(owner.file_id, name=STATE_HISTORY_NAME)
        if len(matches) > 1:
            raise DriveWorkflowBlocked("duplicate state-history folders")
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveWorkflowBlocked("state-history is not a live folder")
            return item
        if not create:
            raise DriveWorkflowBlocked("state-history folder missing")
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            owner.file_id,
            STATE_HISTORY_NAME,
            file_id=reserved,
            label=f"{self.label_base}.history.create",
        )
        matches = self.drive.list_children(owner.file_id, name=STATE_HISTORY_NAME)
        if len(matches) != 1 or matches[0].file_id != reserved or matches[0].trashed or not matches[0].is_folder:
            raise DriveWorkflowBlocked("state-history folder did not become exact")
        return matches[0]

    def _update_folder(self, history: DriveItem, update_id: str, *, create: bool) -> DriveItem:
        matches = self.drive.list_children(history.file_id, name=update_id)
        if len(matches) > 1:
            raise DriveWorkflowBlocked(f"duplicate STATE update folders for {update_id}")
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveWorkflowBlocked(f"STATE update path {update_id} is not a live folder")
            return item
        if not create:
            raise DriveWorkflowBlocked(f"STATE update folder missing: {update_id}")
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            history.file_id,
            update_id,
            file_id=reserved,
            label=f"{self.label_base}.{update_id}.folder.create",
        )
        matches = self.drive.list_children(history.file_id, name=update_id)
        if len(matches) != 1 or matches[0].file_id != reserved or matches[0].trashed or not matches[0].is_folder:
            raise DriveWorkflowBlocked("STATE update folder did not become exact")
        return matches[0]

    def _material(self, update_folder: DriveItem) -> dict[str, DriveItem]:
        allowed = {STATE_PLAN_NAME, STATE_NEW_NAME, STATE_OLD_NAME, STATE_DONE_NAME}
        material: dict[str, DriveItem] = {}
        for item in self.drive.list_children(update_folder.file_id):
            if item.name not in allowed:
                raise DriveWorkflowBlocked(f"unknown material in STATE update folder: {item.name}")
            if item.name in material:
                raise DriveWorkflowBlocked(f"duplicate STATE update material: {item.name}")
            if item.trashed or item.is_folder:
                raise DriveWorkflowBlocked(f"STATE update material is not a live blob: {item.name}")
            material[item.name] = item
        return material

    def _load_plan(self, item: DriveItem) -> tuple[bytes, dict[str, Any]]:
        raw = self.drive.download(item.file_id)
        try:
            plan = validate_work_state_update_plan(strict_json_bytes(raw, label="WORK_STATE_PLAN"))
        except ProtocolError as exc:
            raise DriveWorkflowBlocked(str(exc)) from exc
        if plan["plan_file_id"] != item.file_id:
            raise DriveWorkflowBlocked("STATE PLAN does not bind its exact Drive ID")
        return raw, plan

    def _exact_or_missing(self, file_id: str) -> DriveItem | None:
        try:
            return self.drive.get(file_id, include_trashed=False)
        except DriveNotFound:
            return None

    def _done_value(self, update_id: str, plan_item: DriveItem, plan_raw: bytes, plan: dict[str, Any]) -> dict[str, Any]:
        return validate_work_state_update(
            {
                "schema": "keelaryn.work-state-update.v1",
                "state": "APPLIED",
                "owner_kind": self.owner_kind,
                "owner_id": self.owner_id,
                "update_id": update_id,
                "plan_file_id": plan_item.file_id,
                "plan_sha256": sha256(plan_raw).hexdigest(),
                "plan_size": len(plan_raw),
                "old": plan["old"],
                "new": plan["new"],
            }
        )

    def _verify_completed_history(self, owner: DriveItem, history: DriveItem, update_folder: DriveItem) -> None:
        material = self._material(update_folder)
        required = {STATE_PLAN_NAME, STATE_OLD_NAME, STATE_DONE_NAME}
        if set(material) != required:
            raise DriveWorkflowBlocked(
                f"completed STATE update {update_folder.name} has invalid material: {sorted(material)}"
            )
        plan_item = material[STATE_PLAN_NAME]
        plan_raw, plan = self._load_plan(plan_item)
        if (
            plan["owner_kind"] != self.owner_kind
            or plan["owner_id"] != self.owner_id
            or plan["update_id"] != update_folder.name
            or plan["owner_folder_id"] != owner.file_id
            or plan["update_folder_id"] != update_folder.file_id
        ):
            raise DriveWorkflowBlocked(f"historical STATE PLAN identity mismatch: {update_folder.name}")

        old_item = material[STATE_OLD_NAME]
        if old_item.file_id != plan["old"]["file_id"]:
            raise DriveWorkflowBlocked(f"historical STATE OLD identity mismatch: {update_folder.name}")
        _verify_item_bytes(self.drive, old_item, plan["old"]["fingerprint"], f"historical STATE OLD {update_folder.name}")

        new_item = self._exact_or_missing(plan["new"]["file_id"])
        if new_item is None:
            raise DriveWorkflowBlocked(f"historical STATE NEW object missing: {update_folder.name}")
        _verify_item_bytes(self.drive, new_item, plan["new"]["fingerprint"], f"historical STATE NEW {update_folder.name}")
        if new_item.parent_id == owner.file_id and new_item.name == PROJECT_STATE_NAME:
            pass
        elif new_item.name == STATE_OLD_NAME:
            parents = {
                child.file_id
                for child in self.drive.list_children(history.file_id)
                if not child.trashed and child.is_folder
            }
            if new_item.parent_id not in parents:
                raise DriveWorkflowBlocked(f"historical STATE NEW moved outside state-history: {update_folder.name}")
        else:
            raise DriveWorkflowBlocked(f"historical STATE NEW has unknown location: {update_folder.name}")

        done_item = material[STATE_DONE_NAME]
        done_raw = self.drive.download(done_item.file_id)
        try:
            done = validate_work_state_update(strict_json_bytes(done_raw, label="WORK_STATE_DONE.history"))
        except ProtocolError as exc:
            raise DriveWorkflowBlocked(str(exc)) from exc
        expected = self._done_value(plan["update_id"], plan_item, plan_raw, plan)
        if done != expected or done_item.file_id != plan["done_marker_id"]:
            raise DriveWorkflowBlocked(f"historical STATE DONE identity mismatch: {update_folder.name}")

    def _block_other_incomplete(self, owner: DriveItem, history: DriveItem, update_id: str) -> None:
        for child in self.drive.list_children(history.file_id):
            if child.trashed or not child.is_folder:
                raise DriveWorkflowBlocked("state-history contains non-folder material")
            if child.name == update_id:
                continue
            self._verify_completed_history(owner, history, child)

    def _plan(
        self,
        owner: DriveItem,
        update_folder: DriveItem,
        update_id: str,
        new_raw: bytes,
    ) -> tuple[DriveItem, bytes, dict[str, Any]]:
        material = self._material(update_folder)
        existing = material.get(STATE_PLAN_NAME)
        expected_new = _fingerprint(new_raw)
        if existing is not None:
            raw, plan = self._load_plan(existing)
            if (
                plan["owner_kind"] != self.owner_kind
                or plan["owner_id"] != self.owner_id
                or plan["update_id"] != update_id
                or plan["owner_folder_id"] != owner.file_id
                or plan["update_folder_id"] != update_folder.file_id
                or plan["new"]["fingerprint"] != expected_new
            ):
                raise DriveWorkflowBlocked("existing STATE PLAN does not bind this exact update")
            return existing, raw, plan

        state = _unique_blob(self.drive, owner.file_id, PROJECT_STATE_NAME, f"{self.owner_kind} {self.owner_id} STATE.md")
        old_raw = self.drive.download(state.file_id)
        old_fp = _fingerprint(old_raw)
        if old_fp == expected_new:
            raise DriveWorkflowBlocked("no-op STATE update forbidden")
        new_id, plan_id, done_id = self.drive.generate_ids(3)
        plan = validate_work_state_update_plan(
            {
                "schema": "keelaryn.work-state-update-plan.v1",
                "state": "PREPARED",
                "owner_kind": self.owner_kind,
                "owner_id": self.owner_id,
                "owner_folder_id": owner.file_id,
                "update_id": update_id,
                "update_folder_id": update_folder.file_id,
                "plan_file_id": plan_id,
                "old": {"file_id": state.file_id, "fingerprint": old_fp},
                "new": {"file_id": new_id, "fingerprint": expected_new},
                "done_marker_id": done_id,
            }
        )
        raw = canonical_json_bytes(plan)
        self.drive.create_blob(
            update_folder.file_id,
            STATE_PLAN_NAME,
            raw,
            mime_type="application/json",
            file_id=plan_id,
            label=f"{self.label_base}.{update_id}.plan.create",
        )
        item = _unique_blob(self.drive, update_folder.file_id, STATE_PLAN_NAME, f"STATE update {update_id} PLAN")
        if item.file_id != plan_id or self.drive.download(item.file_id) != raw:
            raise DriveWorkflowBlocked("STATE PLAN did not become exact")
        return item, raw, plan

    def _ensure_new_candidate(self, update_id: str, update_folder: DriveItem, plan: dict[str, Any], new_raw: bytes) -> DriveItem:
        new = plan["new"]
        item = self._exact_or_missing(new["file_id"])
        if item is None:
            named = self.drive.list_children(update_folder.file_id, name=STATE_NEW_NAME)
            if named:
                raise DriveWorkflowBlocked("STATE NEW.md name occupied by unexpected Drive ID")
            try:
                self.drive.create_blob(
                    update_folder.file_id,
                    STATE_NEW_NAME,
                    new_raw,
                    file_id=new["file_id"],
                    label=f"{self.label_base}.{update_id}.new.create",
                )
            except DriveAlreadyExists:
                pass
            item = self._exact_or_missing(new["file_id"])
        if item is None:
            raise DriveWorkflowBlocked("reserved STATE NEW object missing")
        if item.parent_id == update_folder.file_id and item.name == STATE_NEW_NAME:
            _verify_item_bytes(self.drive, item, new["fingerprint"], "STATE NEW candidate")
            return item
        if item.parent_id == plan["owner_folder_id"] and item.name == PROJECT_STATE_NAME:
            _verify_item_bytes(self.drive, item, new["fingerprint"], "published STATE.md")
            return item
        raise DriveWorkflowBlocked("reserved STATE NEW object has unknown location")

    def _classify(self, owner: DriveItem, update_folder: DriveItem, plan: dict[str, Any]) -> str:
        old = self._exact_or_missing(plan["old"]["file_id"])
        new = self._exact_or_missing(plan["new"]["file_id"])
        current = self.drive.list_children(owner.file_id, name=PROJECT_STATE_NAME)
        if len(current) > 1:
            raise DriveWorkflowBlocked("multiple current STATE.md objects")
        if old is None or new is None:
            raise DriveWorkflowBlocked("STATE transition exact object missing")
        _verify_item_bytes(self.drive, old, plan["old"]["fingerprint"], "STATE old object")
        _verify_item_bytes(self.drive, new, plan["new"]["fingerprint"], "STATE new object")

        old_current = old.parent_id == owner.file_id and old.name == PROJECT_STATE_NAME
        old_archived = old.parent_id == update_folder.file_id and old.name == STATE_OLD_NAME
        new_candidate = new.parent_id == update_folder.file_id and new.name == STATE_NEW_NAME
        new_current = new.parent_id == owner.file_id and new.name == PROJECT_STATE_NAME
        current_id = current[0].file_id if current else None

        if old_current and new_candidate and current_id == old.file_id:
            return "OLD"
        if old_archived and new_candidate and current_id is None:
            return "GAP"
        if old_archived and new_current and current_id == new.file_id:
            return "NEW"
        raise DriveWorkflowBlocked("STATE transition objects are in an unknown configuration")

    def _load_done(self, owner: DriveItem, update_folder: DriveItem, plan_item: DriveItem, plan_raw: bytes, plan: dict[str, Any], done_item: DriveItem) -> DriveWorkStateUpdate:
        raw = self.drive.download(done_item.file_id)
        try:
            done = validate_work_state_update(strict_json_bytes(raw, label="WORK_STATE_DONE"))
        except ProtocolError as exc:
            raise DriveWorkflowBlocked(str(exc)) from exc
        expected = self._done_value(plan["update_id"], plan_item, plan_raw, plan)
        if done != expected or done_item.file_id != plan["done_marker_id"]:
            raise DriveWorkflowBlocked("STATE DONE does not bind exact PLAN/update identities")
        if self._classify(owner, update_folder, plan) != "NEW":
            raise DriveWorkflowBlocked("completed STATE update does not have NEW as current STATE.md")
        return DriveWorkStateUpdate(
            self.owner_kind,
            self.owner_id,
            plan["update_id"],
            update_folder.file_id,
            plan_item.file_id,
            done_item.file_id,
            plan_raw,
            raw,
            plan,
            done,
        )

    def _reject_new_noop_without_mutation(self, owner: DriveItem, new_state_markdown: bytes) -> None:
        state = _unique_blob(self.drive, owner.file_id, PROJECT_STATE_NAME, f"{self.owner_kind} {self.owner_id} STATE.md")
        if _fingerprint(self.drive.download(state.file_id)) == _fingerprint(new_state_markdown):
            raise DriveWorkflowBlocked("no-op STATE update forbidden")

    def update(self, update_id: str, new_state_markdown: bytes) -> DriveWorkStateUpdate:
        update_id = _identifier(update_id, "update_id")
        if not isinstance(new_state_markdown, bytes) or not new_state_markdown:
            raise DriveWorkflowBlocked("new STATE.md must be non-empty bytes")
        owner = self._owner()

        history_matches = self.drive.list_children(owner.file_id, name=STATE_HISTORY_NAME)
        if len(history_matches) > 1:
            raise DriveWorkflowBlocked("duplicate state-history folders")
        if not history_matches:
            self._reject_new_noop_without_mutation(owner, new_state_markdown)
            history = self._history(owner, create=True)
        else:
            history = self._history(owner, create=False)

        self._block_other_incomplete(owner, history, update_id)
        update_matches = self.drive.list_children(history.file_id, name=update_id)
        if len(update_matches) > 1:
            raise DriveWorkflowBlocked(f"duplicate STATE update folders for {update_id}")
        if not update_matches:
            self._reject_new_noop_without_mutation(owner, new_state_markdown)
        update_folder = self._update_folder(history, update_id, create=True)
        plan_item, plan_raw, plan = self._plan(owner, update_folder, update_id, new_state_markdown)

        material = self._material(update_folder)
        done = material.get(STATE_DONE_NAME)
        if done is not None:
            return self._load_done(owner, update_folder, plan_item, plan_raw, plan, done)

        self._ensure_new_candidate(update_id, update_folder, plan, new_state_markdown)
        state = self._classify(owner, update_folder, plan)
        if state == "OLD":
            old = self.drive.get(plan["old"]["file_id"], include_trashed=False)
            _verify_item_bytes(self.drive, old, plan["old"]["fingerprint"], "STATE old pre-swap")
            self.drive.move_rename(
                old.file_id,
                update_folder.file_id,
                STATE_OLD_NAME,
                label=f"{self.label_base}.{update_id}.archive-old",
            )
            state = self._classify(owner, update_folder, plan)
        if state == "GAP":
            self.drive.move_rename(
                plan["new"]["file_id"],
                owner.file_id,
                PROJECT_STATE_NAME,
                label=f"{self.label_base}.{update_id}.publish-new",
            )
            state = self._classify(owner, update_folder, plan)
        if state != "NEW":
            raise DriveWorkflowBlocked(f"STATE update did not reach NEW: {state}")

        done_value = self._done_value(update_id, plan_item, plan_raw, plan)
        done_raw = canonical_json_bytes(done_value)
        done_id = plan["done_marker_id"]
        named = self.drive.list_children(update_folder.file_id, name=STATE_DONE_NAME)
        if named and (len(named) != 1 or named[0].file_id != done_id):
            raise DriveWorkflowBlocked("STATE DONE name occupied by unexpected Drive ID")
        if not named:
            try:
                self.drive.create_blob(
                    update_folder.file_id,
                    STATE_DONE_NAME,
                    done_raw,
                    mime_type="application/json",
                    file_id=done_id,
                    label=f"{self.label_base}.{update_id}.done.create",
                )
            except DriveAlreadyExists:
                pass
        done_item = _unique_blob(self.drive, update_folder.file_id, STATE_DONE_NAME, f"STATE update {update_id} DONE")
        if done_item.file_id != done_id or self.drive.download(done_item.file_id) != done_raw:
            raise DriveWorkflowBlocked("STATE DONE did not become exact")
        return self._load_done(owner, update_folder, plan_item, plan_raw, plan, done_item)


__all__ = [
    "STATE_HISTORY_NAME",
    "STATE_PLAN_NAME",
    "STATE_NEW_NAME",
    "STATE_OLD_NAME",
    "STATE_DONE_NAME",
    "DriveWorkState",
    "DriveWorkStateUpdate",
    "DriveWorkStateService",
]
