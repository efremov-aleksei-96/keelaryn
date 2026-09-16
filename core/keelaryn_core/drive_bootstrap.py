from __future__ import annotations

from dataclasses import dataclass

from .drive_backend import DriveBackend, DriveItem, DriveNotFound
from .drive_master import MASTER_NAME
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes, validate_master


class DriveBootstrapBlocked(ProtocolError):
    """A Drive Hub root cannot be initialized or verified without ambiguity."""


@dataclass(frozen=True)
class DriveBootstrapLayout:
    hub_root_id: str
    canonical_root_id: str
    changes_parent_id: str
    postcheck_parent_id: str
    control_active_id: str
    history_root_id: str


@dataclass(frozen=True)
class DriveBootstrapResult:
    state: str
    layout: DriveBootstrapLayout
    master_file_id: str
    master: dict


class DriveHubBootstrap:
    """Initialize a fresh disposable Drive Hub or verify an initialized one.

    Existing initialized Hubs are read-only to this layer: once MASTER.json exists,
    bootstrap never creates missing folders or repairs structure. For a fresh Hub
    with no MASTER, deterministic folder names may be created idempotently. The
    initial READY/SAFE MASTER is published only after all protocol-owned writable
    areas are proven empty, so bootstrap cannot bless unknown canonical/work/history
    bytes as a clean Hub.
    """

    ROOT_ALLOWED = {"canonical", "work", "control", "history", "README.md", "INDEX.md"}

    def __init__(self, drive: DriveBackend, hub_root_id: str):
        self.drive = drive
        self.hub_root_id = hub_root_id

    @staticmethod
    def initial_master_bytes() -> bytes:
        return canonical_json_bytes(
            {
                "schema": "keelaryn.master.v1",
                "state": "READY",
                "canonical_read_status": "SAFE",
                "canonical_epoch": 0,
                "active_change": None,
                "current_stage": None,
                "last_completed_change": None,
            }
        )

    def _require_root(self) -> DriveItem:
        try:
            root = self.drive.get(self.hub_root_id, include_trashed=False)
        except DriveNotFound as exc:
            raise DriveBootstrapBlocked("Hub root Drive object does not exist") from exc
        if root.trashed or not root.is_folder:
            raise DriveBootstrapBlocked("Hub root Drive object is not a live folder")
        return root

    def _master_items(self) -> list[DriveItem]:
        matches = self.drive.list_children(self.hub_root_id, name=MASTER_NAME)
        if len(matches) > 1:
            raise DriveBootstrapBlocked("multiple root MASTER.json objects")
        return matches

    def _existing_folder(self, parent_id: str, name: str) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) != 1:
            raise DriveBootstrapBlocked(f"expected exactly one initialized folder {parent_id}/{name}, found {len(matches)}")
        item = matches[0]
        if item.trashed or not item.is_folder:
            raise DriveBootstrapBlocked(f"initialized path is not a live folder: {parent_id}/{name}")
        return item

    def _ensure_fresh_folder(self, parent_id: str, name: str) -> DriveItem:
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) > 1:
            raise DriveBootstrapBlocked(f"duplicate fresh-Hub folder {parent_id}/{name}")
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveBootstrapBlocked(f"fresh-Hub path is not a live folder: {parent_id}/{name}")
            return item
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            parent_id,
            name,
            file_id=reserved,
            label=f"drive.bootstrap.{name}.create",
        )
        matches = self.drive.list_children(parent_id, name=name)
        if len(matches) != 1 or matches[0].file_id != reserved or matches[0].trashed or not matches[0].is_folder:
            raise DriveBootstrapBlocked(f"fresh-Hub folder did not become exact: {parent_id}/{name}")
        return matches[0]

    def _resolve_existing_layout(self) -> DriveBootstrapLayout:
        canonical = self._existing_folder(self.hub_root_id, "canonical")
        work = self._existing_folder(self.hub_root_id, "work")
        self._existing_folder(work.file_id, "projects")
        reconciliation = self._existing_folder(work.file_id, "reconciliation")
        self._existing_folder(reconciliation.file_id, "claims")
        changes = self._existing_folder(reconciliation.file_id, "changes")
        postcheck = self._existing_folder(reconciliation.file_id, "postcheck")
        control = self._existing_folder(self.hub_root_id, "control")
        active = self._existing_folder(control.file_id, "active")
        history = self._existing_folder(self.hub_root_id, "history")
        return DriveBootstrapLayout(
            self.hub_root_id,
            canonical.file_id,
            changes.file_id,
            postcheck.file_id,
            active.file_id,
            history.file_id,
        )

    def _ensure_fresh_layout(self) -> DriveBootstrapLayout:
        for child in self.drive.list_children(self.hub_root_id):
            if child.name == MASTER_NAME:
                continue
            if child.name not in self.ROOT_ALLOWED:
                raise DriveBootstrapBlocked(f"unexpected object in uninitialized Hub root: {child.name}")

        canonical = self._ensure_fresh_folder(self.hub_root_id, "canonical")
        work = self._ensure_fresh_folder(self.hub_root_id, "work")
        projects = self._ensure_fresh_folder(work.file_id, "projects")
        reconciliation = self._ensure_fresh_folder(work.file_id, "reconciliation")
        claims = self._ensure_fresh_folder(reconciliation.file_id, "claims")
        changes = self._ensure_fresh_folder(reconciliation.file_id, "changes")
        postcheck = self._ensure_fresh_folder(reconciliation.file_id, "postcheck")
        control = self._ensure_fresh_folder(self.hub_root_id, "control")
        active = self._ensure_fresh_folder(control.file_id, "active")
        history = self._ensure_fresh_folder(self.hub_root_id, "history")

        allowed_work = {"projects", "reconciliation"}
        if any(child.name not in allowed_work for child in self.drive.list_children(work.file_id)):
            raise DriveBootstrapBlocked("unexpected material in fresh work/")
        allowed_reconciliation = {"claims", "changes", "postcheck"}
        if any(child.name not in allowed_reconciliation for child in self.drive.list_children(reconciliation.file_id)):
            raise DriveBootstrapBlocked("unexpected material in fresh work/reconciliation/")
        allowed_control = {"active"}
        if any(child.name not in allowed_control for child in self.drive.list_children(control.file_id)):
            raise DriveBootstrapBlocked("unexpected material in fresh control/")

        for label, parent_id in (
            ("canonical", canonical.file_id),
            ("projects", projects.file_id),
            ("claims", claims.file_id),
            ("changes", changes.file_id),
            ("postcheck", postcheck.file_id),
            ("control/active", active.file_id),
            ("history", history.file_id),
        ):
            if self.drive.list_children(parent_id):
                raise DriveBootstrapBlocked(f"cannot initialize MASTER over non-empty {label}")

        return DriveBootstrapLayout(
            self.hub_root_id,
            canonical.file_id,
            changes.file_id,
            postcheck.file_id,
            active.file_id,
            history.file_id,
        )

    def _parse_master(self, item: DriveItem) -> dict:
        if item.trashed or item.is_folder:
            raise DriveBootstrapBlocked("MASTER.json is not a live blob")
        try:
            return validate_master(strict_json_bytes(self.drive.download(item.file_id), label="MASTER.bootstrap"))
        except ProtocolError as exc:
            raise DriveBootstrapBlocked(f"MASTER.json is invalid: {exc}") from exc

    def run(self) -> DriveBootstrapResult:
        self._require_root()
        masters = self._master_items()
        if masters:
            master = self._parse_master(masters[0])
            layout = self._resolve_existing_layout()
            return DriveBootstrapResult("EXISTING", layout, masters[0].file_id, master)

        layout = self._ensure_fresh_layout()
        # Re-check after all failure-prone folder creation. An externally-created
        # MASTER or new writable material must stop initial publication.
        if self._master_items():
            raise DriveBootstrapBlocked("MASTER.json appeared during fresh-Hub bootstrap")

        work = self._existing_folder(self.hub_root_id, "work")
        projects = self._existing_folder(work.file_id, "projects")
        reconciliation = self._existing_folder(work.file_id, "reconciliation")
        claims = self._existing_folder(reconciliation.file_id, "claims")
        for label, parent_id in (
            ("canonical", layout.canonical_root_id),
            ("projects", projects.file_id),
            ("claims", claims.file_id),
            ("changes", layout.changes_parent_id),
            ("postcheck", layout.postcheck_parent_id),
            ("control/active", layout.control_active_id),
            ("history", layout.history_root_id),
        ):
            if self.drive.list_children(parent_id):
                raise DriveBootstrapBlocked(f"fresh {label} changed before MASTER publication")

        raw = self.initial_master_bytes()
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_blob(
            self.hub_root_id,
            MASTER_NAME,
            raw,
            mime_type="application/json",
            file_id=reserved,
            label="drive.bootstrap.master.create",
        )
        masters = self._master_items()
        if len(masters) != 1 or masters[0].file_id != reserved:
            raise DriveBootstrapBlocked("initial MASTER did not become uniquely observable")
        if self.drive.download(masters[0].file_id) != raw:
            raise DriveBootstrapBlocked("initial MASTER bytes changed during publication")
        master = self._parse_master(masters[0])
        return DriveBootstrapResult("INITIALIZED", layout, masters[0].file_id, master)


__all__ = [
    "DriveBootstrapBlocked",
    "DriveBootstrapLayout",
    "DriveBootstrapResult",
    "DriveHubBootstrap",
]
