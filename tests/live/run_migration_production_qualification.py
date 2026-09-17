from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider  # noqa: E402
from keelaryn_core.drive_rest import GoogleDriveBackend  # noqa: E402
from keelaryn_core.migration_production_drive_qualification import (  # noqa: E402
    DriveAuthoritativeMigrationProductionTargetQualification,
)


class LiveProductionQualificationError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise LiveProductionQualificationError(f"missing required environment: {name}")
    return value


def _path(name: str) -> Path:
    return Path(_required(name))


def main() -> int:
    phase = "preflight"
    try:
        if _required("KEELARYN_PRODUCTION_TARGET_QUALIFICATION_ENABLE") != "YES":
            raise LiveProductionQualificationError(
                "production target qualification is not explicitly enabled"
            )

        pack_dir = _path("KEELARYN_MIGRATION_PACK_DIR")
        freeze_receipt = _path("KEELARYN_MIGRATION_FREEZE_RECEIPT")
        repo_root = _path("KEELARYN_MIGRATION_REPO_ROOT")
        legacy_source_root_id = _required("KEELARYN_MIGRATION_LEGACY_SOURCE_ROOT_ID")
        target_authority = _path("KEELARYN_MIGRATION_TARGET_AUTHORITY")
        qualification_evidence = _path("KEELARYN_MIGRATION_QUALIFICATION_EVIDENCE")
        staging_root_id = _required("KEELARYN_PRODUCTION_MIGRATION_STAGING_ROOT_ID")

        phase = "oauth"
        token_provider = GoogleOAuthRefreshTokenProvider.from_environment()
        drive = GoogleDriveBackend(token_provider)

        phase = "production-target-qualification"
        evidence = DriveAuthoritativeMigrationProductionTargetQualification(
            drive,
            staging_root_id,
            legacy_source_root_id,
        ).run_drive(
            pack_dir,
            freeze_receipt,
            repo_root,
            target_authority,
            qualification_evidence,
        )

        phase = "evidence"
        value = evidence.to_json_value()
        if value["outcome"] != "TARGET_QUALIFICATION_PASS":
            raise LiveProductionQualificationError(
                "production target qualification did not reach PASS"
            )
        if value["cutover_authorized"] is not False:
            raise LiveProductionQualificationError(
                "production target evidence unexpectedly authorizes cutover"
            )

        public = {
            "schema": "keelaryn.migration-production-live-run.v1",
            "qualification": value,
            "production_selector_mutated": False,
            "cutover_authorized": False,
        }
        rendered = json.dumps(
            public,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        # The qualification contract publishes only frozen content provenance and
        # hashed target/staging identities. Raw legacy/staging Drive IDs and local
        # private paths must never be emitted by the live wrapper.
        forbidden = (
            legacy_source_root_id,
            staging_root_id,
            str(pack_dir),
            str(freeze_receipt),
            str(repo_root),
            str(target_authority),
            str(qualification_evidence),
        )
        if any(secret and secret in rendered for secret in forbidden):
            raise LiveProductionQualificationError(
                "sanitized production qualification output leaked private identity/path"
            )

        print(rendered, flush=True)
        return 0
    except Exception as exc:
        # Do not emit exception text: transport/protocol failures may contain Drive
        # IDs, object URLs, source names or workstation paths. Phase + class is
        # sufficient for first-pass classification; private evidence remains local.
        print(
            json.dumps(
                {
                    "schema": "keelaryn.migration-production-live-failure.v1",
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
