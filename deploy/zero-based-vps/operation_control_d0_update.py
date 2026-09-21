from __future__ import annotations

import argparse
import ast
import importlib.util
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

LEGACY_PATH = Path(__file__).with_name(
    "operation_control_plane_update.py"
)
LEGACY_SPEC = importlib.util.spec_from_file_location(
    "keelaryn_operation_control_legacy_primitives",
    LEGACY_PATH,
)
if LEGACY_SPEC is None or LEGACY_SPEC.loader is None:
    raise RuntimeError(
        "cannot load legacy control transaction primitives"
    )
legacy = importlib.util.module_from_spec(
    LEGACY_SPEC
)
LEGACY_SPEC.loader.exec_module(
    legacy
)


SCHEMA = "keelaryn.operation-control-d0-update.v1"
PREPARED_SCHEMA = "keelaryn.operation-control-d0-update-prepared.v1"
COMPLETED_SCHEMA = "keelaryn.operation-control-d0-update-completed.v1"
ROLLED_BACK_SCHEMA = "keelaryn.operation-control-d0-update-rolled-back.v1"

PERSISTENT_UNITS = legacy.PERSISTENT_UNITS
STATIC_UNIT = "keelaryn-production-snapshot@.service"
SERVICE_STABILITY_SECONDS = 12.0

D0ControlUpdateError = legacy.ControlPlaneUpdateError


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _optional_unit_bytes(release: Path, name: str) -> bytes | None:
    path = release / "deploy" / "zero-based-vps" / name
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise D0ControlUpdateError(
            f"qualified optional unit is not regular: {name}"
        )
    return path.read_bytes()


def _verify_snapshot_unit_policy(raw: bytes) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise D0ControlUpdateError(
            "production snapshot unit is not UTF-8"
        ) from exc
    lines = set(text.splitlines())
    required = {
        "User=root",
        "Group=root",
        "PrivateNetwork=true",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "RestrictAddressFamilies=AF_UNIX",
        "ReadWritePaths=/var/lib/keelaryn/operations/%i",
    }
    missing = sorted(required - lines)
    if missing:
        raise D0ControlUpdateError(
            f"production snapshot unit hardening is incomplete: {missing}"
        )
    inaccessible = next(
        (
            line
            for line in text.splitlines()
            if line.startswith("InaccessiblePaths=")
        ),
        "",
    )
    isolated = set(
        inaccessible.removeprefix("InaccessiblePaths=").split()
    )
    if not {
        "/etc/keelaryn/drive.env",
        "/etc/keelaryn/operation-control",
        "/var/lib/keelaryn/migration",
        "/var/lib/keelaryn-operation-transport",
    }.issubset(isolated):
        raise D0ControlUpdateError(
            "production snapshot unit secret isolation is incomplete"
        )
    expected_exec = (
        "ExecStart=/usr/bin/python3 -B -m "
        "keelaryn_core.production_snapshot --operation-id %i "
        "--output /var/lib/keelaryn/operations/%i/"
        "production-snapshot.json"
    )
    if expected_exec not in lines:
        raise D0ControlUpdateError(
            "production snapshot unit ExecStart is not exact"
        )
    if "[Install]" in lines:
        raise D0ControlUpdateError(
            "production snapshot template must remain static"
        )


def _verify_read_only_agent_contract(release: Path) -> None:
    path = release / "core" / "keelaryn_core" / "operation_agent.py"
    if path.is_symlink() or not path.is_file():
        raise D0ControlUpdateError(
            "successor operation agent source missing"
        )
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise D0ControlUpdateError(
            "successor operation agent cannot be parsed"
        ) from exc

    handlers = None
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "HANDLERS"
        ):
            handlers = node.value
            break
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id == "HANDLERS"
            for target in node.targets
        ):
            handlers = node.value
            break
    if not isinstance(handlers, ast.Dict):
        raise D0ControlUpdateError(
            "successor operation agent HANDLERS contract missing"
        )

    expected_callbacks = {
        "RUNTIME_SELFTEST": "_runtime_selftest",
        "PRODUCTION_SNAPSHOT": "_production_snapshot",
    }
    observed: dict[str, ast.AST] = {}
    for key_node, value_node in zip(
        handlers.keys,
        handlers.values,
    ):
        if (
            not isinstance(key_node, ast.Constant)
            or not isinstance(key_node.value, str)
        ):
            raise D0ControlUpdateError(
                "successor operation handler key is not static"
            )
        if key_node.value in observed:
            raise D0ControlUpdateError(
                "successor operation handler key is duplicated"
            )
        observed[key_node.value] = value_node
    if set(observed) != set(expected_callbacks):
        raise D0ControlUpdateError(
            "successor remote operation allowlist is not exact D0 read-only"
        )

    for name, callback in expected_callbacks.items():
        call = observed[name]
        if (
            not isinstance(call, ast.Call)
            or not isinstance(call.func, ast.Name)
            or call.func.id != "OperationHandler"
            or call.args
        ):
            raise D0ControlUpdateError(
                f"successor handler declaration is invalid: {name}"
            )
        keywords = {
            item.arg: item.value
            for item in call.keywords
            if item.arg is not None
        }
        if set(keywords) != {
            "mutation_capable",
            "requires_approval",
            "callback",
        }:
            raise D0ControlUpdateError(
                f"successor handler policy keys are invalid: {name}"
            )
        for policy in (
            "mutation_capable",
            "requires_approval",
        ):
            value = keywords[policy]
            if (
                not isinstance(value, ast.Constant)
                or value.value is not False
            ):
                raise D0ControlUpdateError(
                    f"successor handler is not read-only: {name}"
                )
        callback_node = keywords["callback"]
        if (
            not isinstance(callback_node, ast.Name)
            or callback_node.id != callback
        ):
            raise D0ControlUpdateError(
                f"successor handler callback is invalid: {name}"
            )


def _installed_optional_matches(
    unit_dir: Path,
    release: Path,
) -> bool:
    expected = _optional_unit_bytes(release, STATIC_UNIT)
    path = unit_dir / STATIC_UNIT
    if expected is None:
        return not path.exists() and not path.is_symlink()
    return (
        path.is_file()
        and not path.is_symlink()
        and path.read_bytes() == expected
    )


def _transaction_digest(
    *,
    old_source: str,
    old_payload: str,
    new_source: str,
    new_payload: str,
    production_target: str,
) -> str:
    return _sha(
        _canonical(
            {
                "schema": SCHEMA,
                "old_source_commit": old_source,
                "old_payload_sha256": old_payload,
                "new_source_commit": new_source,
                "new_payload_sha256": new_payload,
                "static_unit": STATIC_UNIT,
                "production_current_target": production_target,
            }
        )
    )


def _live_boundary(
    *,
    old_release: Path,
    new_release: Path,
    old_source: str,
    new_source: str,
    control_current: Path,
    unit_dir: Path,
) -> str:
    target = legacy._readlink(
        control_current,
        "control-current",
    )
    persistent_old = all(
        (unit_dir / name).is_file()
        and not (unit_dir / name).is_symlink()
        and (unit_dir / name).read_bytes()
        == legacy._unit_bytes(old_release, name)
        for name in PERSISTENT_UNITS
    )
    persistent_new = all(
        (unit_dir / name).is_file()
        and not (unit_dir / name).is_symlink()
        and (unit_dir / name).read_bytes()
        == legacy._unit_bytes(new_release, name)
        for name in PERSISTENT_UNITS
    )
    if (
        target == f"releases/{old_source}"
        and persistent_old
        and _installed_optional_matches(unit_dir, old_release)
    ):
        return "OLD_EXACT"
    if (
        target == f"releases/{new_source}"
        and persistent_new
        and _installed_optional_matches(unit_dir, new_release)
    ):
        return "NEW_EXACT"
    return "PARTIAL"


def _verify_persistent_services(
    *,
    active_probe: Callable[[str], bool],
    enabled_probe: Callable[[str], str],
    restart_probe: Callable[[str], int],
    restart_anchor: dict[str, int] | None = None,
) -> dict[str, int]:
    observed: dict[str, int] = {}
    for unit in PERSISTENT_UNITS:
        if not active_probe(unit):
            raise D0ControlUpdateError(
                f"persistent operation-control unit is inactive: {unit}"
            )
        if enabled_probe(unit) not in {
            "enabled",
            "enabled-runtime",
        }:
            raise D0ControlUpdateError(
                f"persistent operation-control unit is not enabled: {unit}"
            )
        observed[unit] = restart_probe(unit)
        if (
            restart_anchor is not None
            and observed[unit] != restart_anchor[unit]
        ):
            raise D0ControlUpdateError(
                f"operation-control unit restarted unexpectedly: {unit}"
            )
    return observed


def _verify_services(
    *,
    active_probe: Callable[[str], bool],
    enabled_probe: Callable[[str], str],
    restart_probe: Callable[[str], int],
    restart_anchor: dict[str, int] | None = None,
) -> dict[str, int]:
    observed = _verify_persistent_services(
        active_probe=active_probe,
        enabled_probe=enabled_probe,
        restart_probe=restart_probe,
        restart_anchor=restart_anchor,
    )
    if enabled_probe(STATIC_UNIT) != "static":
        raise D0ControlUpdateError(
            "production snapshot template must be systemd-static"
        )
    if active_probe(STATIC_UNIT):
        raise D0ControlUpdateError(
            "production snapshot template must be inactive outside request"
        )
    return observed


def update_d0_control_plane(
    *,
    install_root: Path,
    unit_dir: Path,
    credential_path: Path,
    operation_root: Path,
    transport_root: Path,
    update_root: Path,
    expected_old_source_commit: str,
    expected_old_payload_sha256: str,
    expected_new_source_commit: str,
    expected_new_payload_sha256: str,
    systemctl: Callable[[list[str]], None] = legacy._must_systemctl,
    active_probe: Callable[[str], bool] = legacy._is_active,
    enabled_probe: Callable[[str], str] = legacy._enabled_state,
    restart_probe: Callable[[str], int] = legacy._restart_count,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    legacy._require_root()
    old_source = legacy._validate_oid(
        expected_old_source_commit,
        "expected old source commit",
    )
    new_source = legacy._validate_oid(
        expected_new_source_commit,
        "expected new source commit",
    )
    old_payload = legacy._validate_sha(
        expected_old_payload_sha256,
        "expected old payload SHA-256",
    )
    new_payload = legacy._validate_sha(
        expected_new_payload_sha256,
        "expected new payload SHA-256",
    )
    if old_source == new_source:
        raise D0ControlUpdateError(
            "D0 control update requires distinct successor source"
        )

    install_root = legacy._owned_dir(
        install_root,
        "install root",
    )
    releases = legacy._owned_dir(
        install_root / "releases",
        "release root",
    )
    old_release = releases / old_source
    new_release = releases / new_source
    legacy._release_identity(
        old_release,
        old_source,
        old_payload,
    )
    legacy._release_identity(
        new_release,
        new_source,
        new_payload,
    )
    _verify_read_only_agent_contract(new_release)
    new_static_raw = legacy._unit_bytes(
        new_release,
        STATIC_UNIT,
    )
    _verify_snapshot_unit_policy(new_static_raw)
    old_static_raw = _optional_unit_bytes(
        old_release,
        STATIC_UNIT,
    )

    production_current = install_root / "current"
    control_current = install_root / "control-current"
    production_before = legacy._production_target(
        production_current
    )
    unit_dir = legacy._owned_dir(
        unit_dir,
        "systemd unit directory",
    )
    credential_sha = _sha(
        legacy._regular(
            credential_path,
            "GitHub operations credential",
            mode=0o600,
        ).read_bytes()
    )

    update_root = update_root.absolute()
    update_root_exists = (
        update_root.exists()
        or update_root.is_symlink()
    )
    if update_root_exists:
        update_root = legacy._owned_dir(
            update_root,
            "control update root",
            exact_mode=0o700,
        )

    digest = _transaction_digest(
        old_source=old_source,
        old_payload=old_payload,
        new_source=new_source,
        new_payload=new_payload,
        production_target=production_before,
    )
    if update_root_exists:
        legacy._assert_no_foreign_incomplete(
            update_root,
            digest,
        )
    (
        tx,
        prepared_path,
        completed_path,
        rolled_path,
    ) = legacy._transaction_paths(
        update_root,
        digest,
    )
    tx_exists = tx.exists() or tx.is_symlink()
    if tx_exists:
        legacy._owned_dir(
            tx,
            "D0 control update transaction",
            exact_mode=0o700,
        )

    prepared = {
        "schema": PREPARED_SCHEMA,
        "transaction_id": digest,
        "old_source_commit": old_source,
        "old_payload_sha256": old_payload,
        "new_source_commit": new_source,
        "new_payload_sha256": new_payload,
        "production_current_target": production_before,
        "credential_sha256": credential_sha,
        "old_unit_sha256": {
            name: _sha(
                legacy._unit_bytes(
                    old_release,
                    name,
                )
            )
            for name in PERSISTENT_UNITS
        },
        "new_unit_sha256": {
            name: _sha(
                legacy._unit_bytes(
                    new_release,
                    name,
                )
            )
            for name in PERSISTENT_UNITS
        },
        "static_unit": STATIC_UNIT,
        "old_static_unit_sha256": (
            None
            if old_static_raw is None
            else _sha(old_static_raw)
        ),
        "new_static_unit_sha256": _sha(
            new_static_raw
        ),
        "remote_allowlist": [
            "PRODUCTION_SNAPSHOT",
            "RUNTIME_SELFTEST",
        ],
        "remote_mutation_handlers": 0,
    }
    prepared_raw = _canonical(prepared)

    if rolled_path.exists() or rolled_path.is_symlink():
        raise D0ControlUpdateError(
            "same D0 control update previously rolled back"
        )
    prepared_exists = (
        prepared_path.exists()
        or prepared_path.is_symlink()
    )
    completed_exists = (
        completed_path.exists()
        or completed_path.is_symlink()
    )
    if (
        tx_exists
        and not (
            prepared_exists
            or completed_exists
        )
        and any(tx.iterdir())
    ):
        raise D0ControlUpdateError(
            "orphan D0 control transaction contains unexpected material"
        )
    if prepared_exists:
        if _canonical(
            legacy._json_private(
                prepared_path,
                "prepared D0 control authority",
            )
        ) != prepared_raw:
            raise D0ControlUpdateError(
                "prepared D0 control authority mismatch"
            )
    elif completed_exists:
        raise D0ControlUpdateError(
            "completed D0 control update exists without PREPARED authority"
        )

    live = _live_boundary(
        old_release=old_release,
        new_release=new_release,
        old_source=old_source,
        new_source=new_source,
        control_current=control_current,
        unit_dir=unit_dir,
    )

    def completed_value() -> dict[str, Any]:
        return {
            "schema": COMPLETED_SCHEMA,
            "transaction_id": digest,
            "production_current_unchanged": True,
            "control_current": "SUCCESSOR",
            "persistent_services": "ACTIVE_STABLE",
            "static_unit": "STATIC_INACTIVE",
            "remote_mutation_handlers": "ABSENT",
            "credential_unchanged": True,
        }

    if completed_exists:
        completed = legacy._json_private(
            completed_path,
            "completed D0 control authority",
        )
        if (
            completed != completed_value()
            or live != "NEW_EXACT"
        ):
            raise D0ControlUpdateError(
                "completed D0 control update conflicts with live state"
            )
        if legacy._production_target(
            production_current
        ) != production_before:
            raise D0ControlUpdateError(
                "production current changed after D0 control update"
            )
        if _sha(
            legacy._regular(
                credential_path,
                "GitHub operations credential",
                mode=0o600,
            ).read_bytes()
        ) != credential_sha:
            raise D0ControlUpdateError(
                "GitHub credential changed after completed D0 update"
            )
        if not all(
            active_probe(unit)
            for unit in PERSISTENT_UNITS
        ):
            systemctl(["daemon-reload"])
            for unit in PERSISTENT_UNITS:
                if not active_probe(unit):
                    systemctl(["start", unit])
        anchors = _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
        )
        sleeper(SERVICE_STABILITY_SECONDS)
        _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
            restart_anchor=anchors,
        )
        return completed

    if prepared_exists and live == "NEW_EXACT":
        for unit in reversed(PERSISTENT_UNITS):
            if active_probe(unit):
                systemctl(["stop", unit])
        if any(
            active_probe(unit)
            for unit in PERSISTENT_UNITS
        ):
            raise D0ControlUpdateError(
                "cannot quiesce exact D0 successor during recovery"
            )
        legacy._operation_runtime_idle(operation_root)
        legacy._transport_inbox_idle(transport_root)
        if legacy._production_target(
            production_current
        ) != production_before:
            raise D0ControlUpdateError(
                "production current changed during D0 successor recovery"
            )
        if _sha(
            legacy._regular(
                credential_path,
                "GitHub operations credential",
                mode=0o600,
            ).read_bytes()
        ) != credential_sha:
            raise D0ControlUpdateError(
                "GitHub credential changed during D0 successor recovery"
            )
        systemctl(["daemon-reload"])
        for unit in PERSISTENT_UNITS:
            systemctl(["start", unit])
        anchors = _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
        )
        sleeper(SERVICE_STABILITY_SECONDS)
        _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
            restart_anchor=anchors,
        )
        completed = completed_value()
        legacy._write_record(
            completed_path,
            completed,
        )
        return completed

    if (
        prepared_exists
        and live != "OLD_EXACT"
    ):
        raise D0ControlUpdateError(
            "incomplete D0 control update is partial; reconcile first"
        )

    legacy._operation_runtime_idle(
        operation_root
    )
    legacy._transport_inbox_idle(
        transport_root
    )
    if live != "OLD_EXACT":
        raise D0ControlUpdateError(
            "D0 control update requires exact predecessor boundary"
        )
    if not prepared_exists and not all(
        active_probe(unit)
        for unit in PERSISTENT_UNITS
    ):
        raise D0ControlUpdateError(
            "predecessor control services must be active before PREPARED"
        )
    if any(
        enabled_probe(unit)
        not in {
            "enabled",
            "enabled-runtime",
        }
        for unit in PERSISTENT_UNITS
    ):
        raise D0ControlUpdateError(
            "predecessor control services must remain enabled"
        )

    if not prepared_exists:
        if not update_root_exists:
            update_root = legacy._owned_dir(
                update_root,
                "control update root",
                exact_mode=0o700,
                create=True,
            )
        if not tx_exists:
            tx.mkdir(mode=0o700)
            if os.name == "posix":
                os.chmod(tx, 0o700)
            legacy._fsync_dir(update_root)
        legacy._write_record(
            prepared_path,
            prepared,
        )

    completed_written = False
    try:
        for unit in reversed(
            PERSISTENT_UNITS
        ):
            if active_probe(unit):
                systemctl(
                    ["stop", unit]
                )
        if any(
            active_probe(unit)
            for unit in PERSISTENT_UNITS
        ):
            raise D0ControlUpdateError(
                "predecessor control services did not stop"
            )

        legacy._operation_runtime_idle(
            operation_root
        )
        legacy._transport_inbox_idle(
            transport_root
        )
        if legacy._production_target(
            production_current
        ) != production_before:
            raise D0ControlUpdateError(
                "production current changed at D0 commit boundary"
            )
        if legacy._readlink(
            control_current,
            "control-current",
        ) != f"releases/{old_source}":
            raise D0ControlUpdateError(
                "control-current changed at D0 commit boundary"
            )
        if _sha(
            legacy._regular(
                credential_path,
                "GitHub operations credential",
                mode=0o600,
            ).read_bytes()
        ) != credential_sha:
            raise D0ControlUpdateError(
                "GitHub credential changed at D0 commit boundary"
            )
        if _live_boundary(
            old_release=old_release,
            new_release=new_release,
            old_source=old_source,
            new_source=new_source,
            control_current=control_current,
            unit_dir=unit_dir,
        ) != "OLD_EXACT":
            raise D0ControlUpdateError(
                "predecessor boundary changed before D0 publication"
            )

        legacy._atomic_file(
            unit_dir / STATIC_UNIT,
            new_static_raw,
            0o644,
        )
        for name in PERSISTENT_UNITS:
            legacy._atomic_file(
                unit_dir / name,
                legacy._unit_bytes(
                    new_release,
                    name,
                ),
                0o644,
            )
        legacy._atomic_symlink(
            control_current,
            f"releases/{new_source}",
        )

        systemctl(["daemon-reload"])
        for unit in PERSISTENT_UNITS:
            systemctl(
                ["start", unit]
            )
        anchors = _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
        )
        sleeper(
            SERVICE_STABILITY_SECONDS
        )
        _verify_services(
            active_probe=active_probe,
            enabled_probe=enabled_probe,
            restart_probe=restart_probe,
            restart_anchor=anchors,
        )
        if _live_boundary(
            old_release=old_release,
            new_release=new_release,
            old_source=old_source,
            new_source=new_source,
            control_current=control_current,
            unit_dir=unit_dir,
        ) != "NEW_EXACT":
            raise D0ControlUpdateError(
                "successor D0 control boundary is not exact"
            )

        completed = completed_value()
        legacy._write_record(
            completed_path,
            completed,
        )
        completed_written = True
        return completed

    except BaseException as original:
        if completed_written:
            raise
        rollback_error = None
        try:
            for unit in reversed(
                PERSISTENT_UNITS
            ):
                try:
                    if active_probe(unit):
                        systemctl(
                            ["stop", unit]
                        )
                except BaseException:
                    pass
            if any(
                active_probe(unit)
                for unit in PERSISTENT_UNITS
            ):
                raise D0ControlUpdateError(
                    "cannot prove successor services stopped"
                )
            if legacy._production_target(
                production_current
            ) != production_before:
                raise D0ControlUpdateError(
                    "production current changed before D0 rollback"
                )
            if _sha(
                legacy._regular(
                    credential_path,
                    "GitHub operations credential",
                    mode=0o600,
                ).read_bytes()
            ) != credential_sha:
                raise D0ControlUpdateError(
                    "credential changed before D0 rollback"
                )
            current_target = legacy._readlink(
                control_current,
                "control-current",
            )
            if current_target not in {
                f"releases/{old_source}",
                f"releases/{new_source}",
            }:
                raise D0ControlUpdateError(
                    "control-current is not transaction-owned"
                )
            for name in PERSISTENT_UNITS:
                observed = legacy._regular(
                    unit_dir / name,
                    f"transaction unit {name}",
                    mode=0o644,
                ).read_bytes()
                if observed not in {
                    legacy._unit_bytes(old_release, name),
                    legacy._unit_bytes(new_release, name),
                }:
                    raise D0ControlUpdateError(
                        f"unit is not transaction-owned before rollback: {name}"
                    )
            static_path = unit_dir / STATIC_UNIT
            if static_path.exists() or static_path.is_symlink():
                observed_static = legacy._regular(
                    static_path,
                    "transaction snapshot static unit",
                    mode=0o644,
                ).read_bytes()
                allowed_static = {new_static_raw}
                if old_static_raw is not None:
                    allowed_static.add(old_static_raw)
                if observed_static not in allowed_static:
                    raise D0ControlUpdateError(
                        "snapshot unit is not transaction-owned before rollback"
                    )
            elif old_static_raw is not None:
                raise D0ControlUpdateError(
                    "predecessor snapshot unit disappeared before rollback"
                )

            legacy._atomic_symlink(
                control_current,
                f"releases/{old_source}",
            )
            for name in PERSISTENT_UNITS:
                legacy._atomic_file(
                    unit_dir / name,
                    legacy._unit_bytes(
                        old_release,
                        name,
                    ),
                    0o644,
                )
            if old_static_raw is None:
                legacy._remove_exact(
                    unit_dir / STATIC_UNIT,
                    new_static_raw,
                    0o644,
                    "D0 production snapshot unit",
                )
            else:
                legacy._atomic_file(
                    unit_dir / STATIC_UNIT,
                    old_static_raw,
                    0o644,
                )

            systemctl(
                ["daemon-reload"]
            )
            for unit in PERSISTENT_UNITS:
                systemctl(
                    ["start", unit]
                )
            rollback_anchors = _verify_persistent_services(
                active_probe=active_probe,
                enabled_probe=enabled_probe,
                restart_probe=restart_probe,
            )
            sleeper(SERVICE_STABILITY_SECONDS)
            _verify_persistent_services(
                active_probe=active_probe,
                enabled_probe=enabled_probe,
                restart_probe=restart_probe,
                restart_anchor=rollback_anchors,
            )
            if _live_boundary(
                old_release=old_release,
                new_release=new_release,
                old_source=old_source,
                new_source=new_source,
                control_current=control_current,
                unit_dir=unit_dir,
            ) != "OLD_EXACT":
                raise D0ControlUpdateError(
                    "D0 rollback did not restore predecessor"
                )
            legacy._write_record(
                rolled_path,
                {
                    "schema": ROLLED_BACK_SCHEMA,
                    "transaction_id": digest,
                    "production_current_unchanged": True,
                    "control_current": "PREDECESSOR",
                    "persistent_services": "ACTIVE_STABLE",
                    "static_unit": (
                        "ABSENT"
                        if old_static_raw is None
                        else "PREDECESSOR_EXACT"
                    ),
                    "credential_unchanged": True,
                    "failure_class": type(
                        original
                    ).__name__,
                },
            )
        except BaseException as exc:
            rollback_error = exc
        if rollback_error is not None:
            raise D0ControlUpdateError(
                "D0 control rollback incomplete; read-only reconcile required"
            ) from original
        raise D0ControlUpdateError(
            "D0 control update failed and rolled back exactly"
        ) from original


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-d0-update"
    )
    parser.add_argument(
        "--install-root",
        type=Path,
        default=Path("/opt/keelaryn"),
    )
    parser.add_argument(
        "--unit-dir",
        type=Path,
        default=Path("/etc/systemd/system"),
    )
    parser.add_argument(
        "--credential-path",
        type=Path,
        default=Path(
            "/etc/keelaryn/operation-control/"
            "github-operations.env"
        ),
    )
    parser.add_argument(
        "--operation-root",
        type=Path,
        default=Path(
            "/var/lib/keelaryn/operations"
        ),
    )
    parser.add_argument(
        "--transport-root",
        type=Path,
        default=Path(
            "/var/lib/keelaryn-operation-transport"
        ),
    )
    parser.add_argument(
        "--update-root",
        type=Path,
        default=Path(
            "/var/lib/keelaryn/"
            "operation-control-d0-updates"
        ),
    )
    parser.add_argument(
        "--expected-old-source-commit",
        required=True,
    )
    parser.add_argument(
        "--expected-old-payload-sha256",
        required=True,
    )
    parser.add_argument(
        "--expected-new-source-commit",
        required=True,
    )
    parser.add_argument(
        "--expected-new-payload-sha256",
        required=True,
    )
    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    args = _parser().parse_args(
        argv
    )
    try:
        value = update_d0_control_plane(
            install_root=args.install_root,
            unit_dir=args.unit_dir,
            credential_path=args.credential_path,
            operation_root=args.operation_root,
            transport_root=args.transport_root,
            update_root=args.update_root,
            expected_old_source_commit=(
                args.expected_old_source_commit
            ),
            expected_old_payload_sha256=(
                args.expected_old_payload_sha256
            ),
            expected_new_source_commit=(
                args.expected_new_source_commit
            ),
            expected_new_payload_sha256=(
                args.expected_new_payload_sha256
            ),
        )
    except (
        D0ControlUpdateError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": (
                        "keelaryn.operation-control-"
                        "d0-update-failure.v1"
                    ),
                    "error_class": type(
                        exc
                    ).__name__,
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
    raise SystemExit(main())
