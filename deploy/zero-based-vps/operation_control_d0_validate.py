from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from materialize_payload import (  # noqa: E402
    PayloadMaterializeError,
    verify_release_directory,
)

UPDATE_PATH = (
    REPO
    / "deploy"
    / "zero-based-vps"
    / "operation_control_d0_update.py"
)
SPEC = importlib.util.spec_from_file_location(
    "operation_control_d0_update_exact",
    UPDATE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load D0 updater")
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


SCHEMA = "keelaryn.operation-control-d0-validation.v1"


class D0ControlValidationError(RuntimeError):
    pass


def _owned_regular(
    path: Path,
    label: str,
    expected: bytes,
) -> None:
    if path.is_symlink() or not path.is_file():
        raise D0ControlValidationError(
            f"{label} missing/not regular"
        )
    info = path.stat(
        follow_symlinks=False
    )
    if os.name == "posix" and (
        info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o644
    ):
        raise D0ControlValidationError(
            f"{label} must be owner-controlled mode 0644"
        )
    if path.read_bytes() != expected:
        raise D0ControlValidationError(
            f"{label} bytes mismatch"
        )


def validate_d0_control_release(
    release: Path,
    *,
    expected_source_commit: str,
    expected_payload_sha256: str,
    installed_unit_dir: Path | None = None,
) -> dict[str, Any]:
    release = release.absolute()
    try:
        identity = verify_release_directory(
            release,
            expected_source_commit=expected_source_commit,
            expected_payload_sha256=(
                expected_payload_sha256
            ),
        )
    except PayloadMaterializeError as exc:
        raise D0ControlValidationError(
            "D0 control release identity verification failed"
        ) from exc

    try:
        update._verify_read_only_agent_contract(
            release
        )
        static_raw = (
            update.legacy._unit_bytes(
                release,
                update.STATIC_UNIT,
            )
        )
        update._verify_snapshot_unit_policy(
            static_raw
        )
    except update.D0ControlUpdateError as exc:
        raise D0ControlValidationError(
            "D0 read-only control contract verification failed"
        ) from exc

    installed_verified = False
    if installed_unit_dir is not None:
        unit_dir = (
            installed_unit_dir.absolute()
        )
        if (
            unit_dir.is_symlink()
            or not unit_dir.is_dir()
        ):
            raise D0ControlValidationError(
                "installed unit directory must be real"
            )
        info = unit_dir.stat(
            follow_symlinks=False
        )
        if os.name == "posix" and (
            info.st_uid != os.geteuid()
            or stat.S_IMODE(
                info.st_mode
            ) & 0o022
        ):
            raise D0ControlValidationError(
                "installed unit directory ownership/mode invalid"
            )

        for name in update.PERSISTENT_UNITS:
            _owned_regular(
                unit_dir / name,
                f"installed persistent unit {name}",
                update.legacy._unit_bytes(
                    release,
                    name,
                ),
            )
        _owned_regular(
            unit_dir / update.STATIC_UNIT,
            "installed production snapshot static unit",
            static_raw,
        )
        installed_verified = True

    return {
        "schema": SCHEMA,
        "source_commit": identity[
            "source_commit"
        ],
        "payload_sha256": identity[
            "payload_sha256"
        ],
        "remote_allowlist": [
            "PRODUCTION_SNAPSHOT",
            "RUNTIME_SELFTEST",
        ],
        "remote_mutation_handlers": 0,
        "snapshot_unit_policy_verified": True,
        "installed_units_verified": (
            installed_verified
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-d0-validate"
    )
    parser.add_argument(
        "--release",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--expected-source-commit",
        required=True,
    )
    parser.add_argument(
        "--expected-payload-sha256",
        required=True,
    )
    parser.add_argument(
        "--installed-unit-dir",
        type=Path,
    )
    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    args = _parser().parse_args(
        argv
    )
    try:
        value = validate_d0_control_release(
            args.release,
            expected_source_commit=(
                args.expected_source_commit
            ),
            expected_payload_sha256=(
                args.expected_payload_sha256
            ),
            installed_unit_dir=(
                args.installed_unit_dir
            ),
        )
    except (
        D0ControlValidationError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": (
                        "keelaryn.operation-control-"
                        "d0-validation-failure.v1"
                    ),
                    "error_class": (
                        type(exc).__name__
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
