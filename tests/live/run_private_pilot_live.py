from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider  # noqa: E402
from keelaryn_core.drive_rest import GoogleDriveBackend  # noqa: E402
from keelaryn_core.pilot_live import (  # noqa: E402
    DrivePrivatePilotLiveService,
    PILOT_HUB_PREFIX,
    PILOT_ROOT_PREFIX,
    SENTINEL_BYTES,
    SENTINEL_NAME,
)
from keelaryn_core.pilot_pack import build_pilot_pack  # noqa: E402
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class LiveCheckError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise LiveCheckError(f"missing required environment: {name}")
    return value


def _write_evidence(value: dict) -> None:
    path = _required("KEELARYN_PRIVATE_PILOT_EVIDENCE")
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def main() -> int:
    phase = "preflight"
    try:
        if _required("KEELARYN_DISPOSABLE_ENABLE") != "YES":
            raise LiveCheckError("disposable live execution is not enabled")
        run_id = _required("GITHUB_RUN_ID")
        attempt = _required("GITHUB_RUN_ATTEMPT")
        source_sha = _required("GITHUB_SHA")
        pilot_id = f"pilot-live-{run_id}-{attempt}"
        payload = b"synthetic private-pilot bytes\r\nsecond line\r\n"

        phase = "pack"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "legacy-structural.md").write_bytes(payload)
            manifest = root / "PILOT_SOURCE.json"
            manifest.write_bytes(
                canonical_json_bytes(
                    {
                        "schema": "keelaryn.pilot-source.v1",
                        "pilot_id": pilot_id,
                        "entries": [
                            {
                                "source": "legacy-structural.md",
                                "target": "legacy-structural.md",
                            }
                        ],
                    }
                )
            )
            pack = build_pilot_pack(source, manifest, root / "pack")

            phase = "oauth"
            token_provider = GoogleOAuthRefreshTokenProvider.from_environment()
            drive = GoogleDriveBackend(token_provider)

            phase = "live-import"
            evidence = DrivePrivatePilotLiveService(drive).run(pack)
            value = evidence.to_json_value()
            pilot = value["pilot"]
            if pilot["outcome"] != "COMMITTED" or pilot["canonical_epoch"] != 1:
                raise LiveCheckError("live pilot did not reach COMMITTED epoch 1")
            if not all(
                value[key]
                for key in (
                    "safety_root_verified",
                    "sentinel_verified",
                    "disposable_hub_verified",
                )
            ):
                raise LiveCheckError("live pilot safety evidence is incomplete")

            phase = "independent-reobserve"
            roots = drive.list_children("root", name=PILOT_ROOT_PREFIX + pilot_id)
            if len(roots) != 1:
                raise LiveCheckError("fresh safety root is not uniquely re-observable through root alias")
            safety_root = roots[0]
            sentinel = drive.list_children(safety_root.file_id, name=SENTINEL_NAME)
            hubs = drive.list_children(safety_root.file_id, name=PILOT_HUB_PREFIX + pilot_id + "_PILOT")
            if len(sentinel) != 1 or drive.download(sentinel[0].file_id) != SENTINEL_BYTES:
                raise LiveCheckError("sentinel failed independent exact-byte re-observation")
            if len(hubs) != 1 or not hubs[0].is_folder:
                raise LiveCheckError("fresh disposable Hub failed independent re-observation")
            canonical = drive.exact_name(hubs[0].file_id, "canonical")
            if canonical is None:
                raise LiveCheckError("canonical folder missing after live import")
            imported = drive.exact_name(canonical.file_id, "legacy-structural.md")
            if imported is None or drive.download(imported.file_id) != payload:
                raise LiveCheckError("imported canonical bytes differ from synthetic private pack")

            phase = "evidence"
            public = {
                "schema": "keelaryn.private-pilot-live-github-evidence.v1",
                "source_sha": source_sha,
                "github_run_id": run_id,
                "github_run_attempt": attempt,
                "runner_os": os.environ.get("RUNNER_OS", ""),
                "pilot": value,
                "independent_reobserve_verified": True,
                "synthetic_private_subset_only": True,
                "contains_drive_ids": False,
                "contains_credentials": False,
            }
            rendered = json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if "legacy-structural.md" in rendered or payload.decode("ascii").strip() in rendered:
                raise LiveCheckError("public live evidence leaked synthetic private material")
            _write_evidence(public)
            print(rendered, flush=True)
            return 0
    except Exception as exc:
        # Intentionally do not print exception text: transport exceptions may
        # contain Drive object IDs/URLs. Phase + class is sufficient for remote
        # classification while preserving the sanitized-evidence contract.
        print(
            json.dumps(
                {
                    "schema": "keelaryn.private-pilot-live-failure.v1",
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
