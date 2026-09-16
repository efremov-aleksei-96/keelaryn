from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .drive_backend import DriveAlreadyExists, DriveBackend, DriveItem, DriveNotFound
from .drive_project import (
    RESULT_MARKDOWN_NAME,
    RESULT_MARKER_NAME,
    DriveProjectResult,
    DriveWorkflowBlocked,
    _fingerprint,
    _get_live,
    _identifier,
    _unique_blob,
    _unique_folder,
    _verify_item_bytes,
)
from .protocol import ProtocolError, canonical_json_bytes, strict_json_bytes
from .workflow_protocol import (
    validate_drive_result_claim,
    validate_drive_result_claim_plan,
    validate_result_marker,
)

CLAIM_PLAN_NAME = "CLAIM_PLAN.json"
CLAIM_MARKER_NAME = "CLAIM.json"


@dataclass(frozen=True)
class DriveResultClaim:
    claim_folder_id: str
    plan_file_id: str
    claim_file_id: str
    plan_raw: bytes
    claim_raw: bytes
    plan: dict[str, Any]
    claim: dict[str, Any]


class DriveResultClaimService:
    """Copy one immutable Project RESULT into Reconciliation-owned claim authority.

    Claims are scoped by both project_id and result_id:
    work/reconciliation/claims/<project_id>/<result_id>/.
    Before CLAIM_PLAN exists, restart recovery may use unique structural names.
    After CLAIM_PLAN exists, copied RESULT objects and CLAIM.json are recovered only
    from the reserved Drive IDs recorded in that durable plan.
    """

    def __init__(self, drive: DriveBackend, claims_parent_id: str):
        self.drive = drive
        self.claims_parent_id = claims_parent_id

    def _project_folder(self, project_id: str, *, create: bool) -> DriveItem:
        project_id = _identifier(project_id, "project_id")
        matches = self.drive.list_children(self.claims_parent_id, name=project_id)
        if len(matches) > 1:
            raise DriveWorkflowBlocked(f"duplicate claim project folders for {project_id}")
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveWorkflowBlocked(f"claim project path for {project_id} is not a live folder")
            return item
        if not create:
            raise DriveWorkflowBlocked(f"claim project folder missing for {project_id}")
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            self.claims_parent_id,
            project_id,
            file_id=reserved,
            label=f"drive.claim.{project_id}.project.create",
        )
        folder = _unique_folder(self.drive, self.claims_parent_id, project_id, f"claim project {project_id}")
        if folder.file_id != reserved:
            raise DriveWorkflowBlocked("claim project folder did not become exact")
        return folder

    def _claim_folder(self, project_id: str, result_id: str, *, create: bool) -> DriveItem:
        project_id = _identifier(project_id, "project_id")
        result_id = _identifier(result_id, "result_id")
        project = self._project_folder(project_id, create=create)
        matches = self.drive.list_children(project.file_id, name=result_id)
        if len(matches) > 1:
            raise DriveWorkflowBlocked(f"duplicate claim folders for {project_id}/{result_id}")
        if matches:
            item = matches[0]
            if item.trashed or not item.is_folder:
                raise DriveWorkflowBlocked(f"claim path for {project_id}/{result_id} is not a live folder")
            return item
        if not create:
            raise DriveWorkflowBlocked(f"claim folder missing for {project_id}/{result_id}")
        reserved = self.drive.generate_ids(1)[0]
        self.drive.create_folder(
            project.file_id,
            result_id,
            file_id=reserved,
            label=f"drive.claim.{project_id}.{result_id}.folder.create",
        )
        folder = _unique_folder(self.drive, project.file_id, result_id, f"claim {project_id}/{result_id}")
        if folder.file_id != reserved:
            raise DriveWorkflowBlocked("claim result folder did not become exact")
        return folder

    def _allowed_material(self, folder_id: str) -> dict[str, DriveItem]:
        allowed = {CLAIM_PLAN_NAME, RESULT_MARKDOWN_NAME, RESULT_MARKER_NAME, CLAIM_MARKER_NAME}
        material: dict[str, DriveItem] = {}
        for item in self.drive.list_children(folder_id):
            if item.name not in allowed:
                raise DriveWorkflowBlocked(f"unknown material in claim folder: {item.name}")
            if item.name in material:
                raise DriveWorkflowBlocked(f"duplicate claim material: {item.name}")
            if item.trashed or item.is_folder:
                raise DriveWorkflowBlocked(f"claim material is not a live blob: {item.name}")
            material[item.name] = item
        return material

    def _source_identity(self, result: DriveProjectResult) -> dict[str, Any]:
        return {
            "folder_id": result.result_folder_id,
            "result_markdown_id": result.result_markdown_id,
            "result_marker_id": result.result_marker_id,
            "result_markdown": _fingerprint(result.result_markdown_raw),
            "result_marker": _fingerprint(result.result_marker_raw),
        }

    def _plan_for_result(self, result: DriveProjectResult, claim_folder: DriveItem) -> tuple[DriveItem, bytes, dict[str, Any]]:
        material = self._allowed_material(claim_folder.file_id)
        existing = material.get(CLAIM_PLAN_NAME)
        source = self._source_identity(result)
        if existing is not None:
            raw = self.drive.download(existing.file_id)
            try:
                plan = validate_drive_result_claim_plan(strict_json_bytes(raw, label="CLAIM_PLAN"))
            except ProtocolError as exc:
                raise DriveWorkflowBlocked(str(exc)) from exc
            if (
                plan["project_id"] != result.project_id
                or plan["result_id"] != result.result_id
                or plan["base_canonical_epoch"] != result.marker["base_canonical_epoch"]
                or plan["source"] != source
                or plan["claimed"]["folder_id"] != claim_folder.file_id
            ):
                raise DriveWorkflowBlocked("existing claim plan does not bind exact Project RESULT")
            return existing, raw, plan

        reserved = self.drive.generate_ids(4)
        if len(set(reserved)) != 4:
            raise DriveWorkflowBlocked("Drive returned duplicate reserved IDs for claim")
        plan = validate_drive_result_claim_plan(
            {
                "schema": "keelaryn.drive-result-claim-plan.v1",
                "state": "PREPARED",
                "project_id": result.project_id,
                "result_id": result.result_id,
                "base_canonical_epoch": result.marker["base_canonical_epoch"],
                "source": source,
                "claimed": {
                    "folder_id": claim_folder.file_id,
                    "result_markdown_id": reserved[0],
                    "result_marker_id": reserved[1],
                    "claim_marker_id": reserved[2],
                },
            }
        )
        plan_raw = canonical_json_bytes(plan)
        plan_id = reserved[3]
        self.drive.create_blob(
            claim_folder.file_id,
            CLAIM_PLAN_NAME,
            plan_raw,
            mime_type="application/json",
            file_id=plan_id,
            label=f"drive.claim.{result.project_id}.{result.result_id}.plan.create",
        )
        plan_item = _unique_blob(self.drive, claim_folder.file_id, CLAIM_PLAN_NAME, f"claim {result.project_id}/{result.result_id} plan")
        if plan_item.file_id != plan_id or self.drive.download(plan_item.file_id) != plan_raw:
            raise DriveWorkflowBlocked("claim plan did not become exact")
        return plan_item, plan_raw, plan

    def _verify_source_from_plan(self, result: DriveProjectResult, plan: dict[str, Any]) -> None:
        source = plan["source"]
        if (
            result.project_id != plan["project_id"]
            or result.result_id != plan["result_id"]
            or result.result_folder_id != source["folder_id"]
            or result.result_markdown_id != source["result_markdown_id"]
            or result.result_marker_id != source["result_marker_id"]
        ):
            raise DriveWorkflowBlocked("Project RESULT object identities changed after claim planning")
        md = _get_live(self.drive, source["result_markdown_id"], "source RESULT.md")
        marker = _get_live(self.drive, source["result_marker_id"], "source RESULT.json")
        if md.parent_id != source["folder_id"] or md.name != RESULT_MARKDOWN_NAME:
            raise DriveWorkflowBlocked("source RESULT.md moved after claim planning")
        if marker.parent_id != source["folder_id"] or marker.name != RESULT_MARKER_NAME:
            raise DriveWorkflowBlocked("source RESULT.json moved after claim planning")
        _verify_item_bytes(self.drive, md, source["result_markdown"], "source RESULT.md")
        _verify_item_bytes(self.drive, marker, source["result_marker"], "source RESULT.json")

    def _ensure_reserved_copy(
        self,
        *,
        source_id: str,
        destination_id: str,
        folder_id: str,
        name: str,
        expected: dict[str, Any],
        label: str,
    ) -> DriveItem:
        name_matches = self.drive.list_children(folder_id, name=name)
        if len(name_matches) > 1:
            raise DriveWorkflowBlocked(f"{label}: duplicate destination names")
        if name_matches and name_matches[0].file_id != destination_id:
            raise DriveWorkflowBlocked(f"{label}: destination name occupied by unexpected Drive ID")
        try:
            item = self.drive.get(destination_id, include_trashed=False)
        except DriveNotFound:
            try:
                self.drive.copy_blob(source_id, folder_id, name, file_id=destination_id, label=label)
            except DriveAlreadyExists:
                pass
            item = _get_live(self.drive, destination_id, label)
        if item.parent_id != folder_id or item.name != name or item.is_folder:
            raise DriveWorkflowBlocked(f"{label}: reserved object location/type mismatch")
        _verify_item_bytes(self.drive, item, expected, label)
        return item

    def claim(self, result: DriveProjectResult) -> DriveResultClaim:
        project_id = _identifier(result.project_id, "project_id")
        result_id = _identifier(result.result_id, "result_id")
        claim_folder = self._claim_folder(project_id, result_id, create=True)
        material = self._allowed_material(claim_folder.file_id)
        if CLAIM_MARKER_NAME in material:
            return self.load_claim(project_id, result_id)

        plan_item, plan_raw, plan = self._plan_for_result(result, claim_folder)
        self._verify_source_from_plan(result, plan)
        source = plan["source"]
        reserved = plan["claimed"]
        claimed_md = self._ensure_reserved_copy(
            source_id=source["result_markdown_id"],
            destination_id=reserved["result_markdown_id"],
            folder_id=claim_folder.file_id,
            name=RESULT_MARKDOWN_NAME,
            expected=source["result_markdown"],
            label=f"drive.claim.{project_id}.{result_id}.markdown.copy",
        )
        claimed_marker = self._ensure_reserved_copy(
            source_id=source["result_marker_id"],
            destination_id=reserved["result_marker_id"],
            folder_id=claim_folder.file_id,
            name=RESULT_MARKER_NAME,
            expected=source["result_marker"],
            label=f"drive.claim.{project_id}.{result_id}.marker.copy",
        )
        claim_value = validate_drive_result_claim(
            {
                "schema": "keelaryn.drive-result-claim.v1",
                "state": "CLAIMED",
                "project_id": plan["project_id"],
                "result_id": plan["result_id"],
                "base_canonical_epoch": plan["base_canonical_epoch"],
                "claim_plan_id": plan_item.file_id,
                "claim_plan_sha256": sha256(plan_raw).hexdigest(),
                "claim_plan_size": len(plan_raw),
                "source": source,
                "claimed": {
                    "folder_id": claim_folder.file_id,
                    "result_markdown_id": claimed_md.file_id,
                    "result_marker_id": claimed_marker.file_id,
                    "result_markdown": source["result_markdown"],
                    "result_marker": source["result_marker"],
                },
            }
        )
        claim_raw = canonical_json_bytes(claim_value)
        claim_id = reserved["claim_marker_id"]
        try:
            self.drive.create_blob(
                claim_folder.file_id,
                CLAIM_MARKER_NAME,
                claim_raw,
                mime_type="application/json",
                file_id=claim_id,
                label=f"drive.claim.{project_id}.{result_id}.authority.create",
            )
        except DriveAlreadyExists:
            pass
        authority = _get_live(self.drive, claim_id, f"claim {project_id}/{result_id} authority")
        if authority.parent_id != claim_folder.file_id or authority.name != CLAIM_MARKER_NAME or authority.is_folder:
            raise DriveWorkflowBlocked("CLAIM.json reserved identity has wrong location/type")
        if self.drive.download(authority.file_id) != claim_raw:
            raise DriveWorkflowBlocked("CLAIM.json bytes differ from exact claim authority")
        return self.load_claim(project_id, result_id)

    def load_claim(self, project_id: str, result_id: str) -> DriveResultClaim:
        project_id = _identifier(project_id, "project_id")
        result_id = _identifier(result_id, "result_id")
        folder = self._claim_folder(project_id, result_id, create=False)
        material = self._allowed_material(folder.file_id)
        required = {CLAIM_PLAN_NAME, RESULT_MARKDOWN_NAME, RESULT_MARKER_NAME, CLAIM_MARKER_NAME}
        if set(material) != required:
            raise DriveWorkflowBlocked(
                f"claim {project_id}/{result_id} incomplete/ambiguous material missing={sorted(required - set(material))}"
            )
        plan_item = material[CLAIM_PLAN_NAME]
        claim_item = material[CLAIM_MARKER_NAME]
        plan_raw = self.drive.download(plan_item.file_id)
        claim_raw = self.drive.download(claim_item.file_id)
        try:
            plan = validate_drive_result_claim_plan(strict_json_bytes(plan_raw, label="CLAIM_PLAN"))
            claim = validate_drive_result_claim(strict_json_bytes(claim_raw, label="CLAIM"))
        except ProtocolError as exc:
            raise DriveWorkflowBlocked(str(exc)) from exc
        if (
            plan["project_id"] != project_id
            or claim["project_id"] != project_id
            or plan["result_id"] != result_id
            or claim["result_id"] != result_id
        ):
            raise DriveWorkflowBlocked("claim identity does not match enclosing claim folders")
        if claim["base_canonical_epoch"] != plan["base_canonical_epoch"]:
            raise DriveWorkflowBlocked("CLAIM identity differs from CLAIM_PLAN")
        if claim["claim_plan_id"] != plan_item.file_id:
            raise DriveWorkflowBlocked("CLAIM does not bind exact CLAIM_PLAN Drive ID")
        if claim["claim_plan_sha256"] != sha256(plan_raw).hexdigest() or claim["claim_plan_size"] != len(plan_raw):
            raise DriveWorkflowBlocked("CLAIM does not bind exact CLAIM_PLAN bytes")
        if claim["source"] != plan["source"]:
            raise DriveWorkflowBlocked("CLAIM source identity differs from CLAIM_PLAN")
        if claim["claimed"]["folder_id"] != folder.file_id:
            raise DriveWorkflowBlocked("CLAIM claimed folder identity mismatch")
        if claim["claimed"]["result_markdown_id"] != plan["claimed"]["result_markdown_id"]:
            raise DriveWorkflowBlocked("CLAIM RESULT.md ID differs from reserved plan")
        if claim["claimed"]["result_marker_id"] != plan["claimed"]["result_marker_id"]:
            raise DriveWorkflowBlocked("CLAIM RESULT.json ID differs from reserved plan")
        if claim_item.file_id != plan["claimed"]["claim_marker_id"]:
            raise DriveWorkflowBlocked("CLAIM marker Drive ID differs from reserved plan")

        md_item = material[RESULT_MARKDOWN_NAME]
        marker_item = material[RESULT_MARKER_NAME]
        if md_item.file_id != claim["claimed"]["result_markdown_id"]:
            raise DriveWorkflowBlocked("claimed RESULT.md name is bound to unexpected Drive ID")
        if marker_item.file_id != claim["claimed"]["result_marker_id"]:
            raise DriveWorkflowBlocked("claimed RESULT.json name is bound to unexpected Drive ID")
        md_raw = _verify_item_bytes(self.drive, md_item, claim["claimed"]["result_markdown"], "claimed RESULT.md")
        marker_raw = _verify_item_bytes(self.drive, marker_item, claim["claimed"]["result_marker"], "claimed RESULT.json")
        try:
            result_marker = validate_result_marker(strict_json_bytes(marker_raw, label="CLAIMED_RESULT"))
        except ProtocolError as exc:
            raise DriveWorkflowBlocked(str(exc)) from exc
        if (
            result_marker["project_id"] != claim["project_id"]
            or result_marker["result_id"] != claim["result_id"]
            or result_marker["base_canonical_epoch"] != claim["base_canonical_epoch"]
            or result_marker["result_markdown"] != _fingerprint(md_raw)
        ):
            raise DriveWorkflowBlocked("claimed RESULT marker/content identity mismatch")
        return DriveResultClaim(folder.file_id, plan_item.file_id, claim_item.file_id, plan_raw, claim_raw, plan, claim)


__all__ = [
    "CLAIM_PLAN_NAME",
    "CLAIM_MARKER_NAME",
    "DriveResultClaim",
    "DriveResultClaimService",
]
