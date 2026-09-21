from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


OLD_SOURCE = "08f2e211f53764590f6ff0f05f86b2de62c14418"
OLD_PAYLOAD = "6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7"
NEW_SOURCE = "833123b6a7ad2c61087ee8a86700bb9ad8a46298"
NEW_PAYLOAD = "c833a385e03d313497f865a669dbce8050fa4b296dc587836dad2fa5d3f560e9"
PRODUCTION_SOURCE = "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
CANDIDATE = "operation-control-r0007-20260921-01"
PREDECESSOR = "operation-control-r0005-20260921-01"
PERSISTENT_UNITS = (
    "keelaryn-operation-transport.service",
    "keelaryn-operation-agent.service",
)
STATIC_UNIT = "keelaryn-production-snapshot@.service"
SCHEMA = "keelaryn.operation-control-r0007-transition-qualification.v1"


class QualificationError(RuntimeError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _load_updater(template_releases: Path):
    release = template_releases / NEW_SOURCE
    deploy = release / "deploy" / "zero-based-vps"
    core = release / "core"
    for path in (str(deploy), str(core)):
        if path not in sys.path:
            sys.path.insert(0, path)
    module_path = deploy / "operation_control_d0_update.py"
    spec = importlib.util.spec_from_file_location(
        "keelaryn_r0007_transition_updater",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load exact frozen r0007 updater")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.STATIC_UNIT != STATIC_UNIT:
        raise QualificationError("r0007 static-unit contract mismatch")
    if tuple(module.PERSISTENT_UNITS) != PERSISTENT_UNITS:
        raise QualificationError("r0007 persistent-unit contract mismatch")
    module.legacy._require_root = lambda: None
    return module


class Runtime:
    def __init__(
        self,
        *,
        initially_active: bool = True,
        fail_successor_agent_once: bool = False,
        crash_mode: str | None = None,
    ) -> None:
        self.active = set(PERSISTENT_UNITS) if initially_active else set()
        self.enabled = set(PERSISTENT_UNITS)
        self.calls: list[list[str]] = []
        self.fail_successor_agent_once = fail_successor_agent_once
        self.crash_mode = crash_mode
        self._agent_failure_remaining = 1 if fail_successor_agent_once else 0

    def systemctl(self, args: list[str]) -> None:
        self.calls.append(list(args))
        action = args[0]
        if self.crash_mode == "PREPARED_OLD" and action == "stop":
            os._exit(91)
        if action == "stop":
            self.active.discard(args[1])
            return
        if self.crash_mode == "PREPARED_NEW" and action == "daemon-reload":
            os._exit(92)
        if action == "daemon-reload":
            return
        if action == "start":
            unit = args[1]
            if (
                self._agent_failure_remaining
                and unit == "keelaryn-operation-agent.service"
            ):
                self._agent_failure_remaining -= 1
                raise RuntimeError("injected successor agent start failure")
            self.active.add(unit)
            return
        raise QualificationError(f"unexpected fake systemctl action: {args!r}")

    def active_probe(self, unit: str) -> bool:
        return unit in self.active

    def enabled_probe(self, unit: str) -> str:
        if unit in self.enabled:
            return "enabled"
        if unit == STATIC_UNIT:
            return "static"
        return "disabled"

    def restart_probe(self, unit: str) -> int:
        if unit not in PERSISTENT_UNITS:
            raise QualificationError("restart probe requested for unexpected unit")
        return 0


def _copy_release(template_releases: Path, releases: Path, source: str) -> None:
    source_dir = template_releases / source
    destination = releases / source
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise QualificationError(f"template release missing: {source}")
    shutil.copytree(source_dir, destination, copy_function=shutil.copy2)


def _layout(template_releases: Path, root: Path) -> dict[str, Path]:
    install = root / "opt" / "keelaryn"
    releases = install / "releases"
    releases.mkdir(parents=True)
    _copy_release(template_releases, releases, OLD_SOURCE)
    _copy_release(template_releases, releases, NEW_SOURCE)

    os.symlink(f"releases/{PRODUCTION_SOURCE}", install / "current")
    os.symlink(f"releases/{OLD_SOURCE}", install / "control-current")

    unit_dir = root / "systemd"
    unit_dir.mkdir(mode=0o755)
    old_deploy = releases / OLD_SOURCE / "deploy" / "zero-based-vps"
    for name in PERSISTENT_UNITS:
        target = unit_dir / name
        target.write_bytes((old_deploy / name).read_bytes())
        os.chmod(target, 0o644)

    config = root / "etc" / "keelaryn" / "operation-control"
    config.mkdir(parents=True, mode=0o700)
    os.chmod(config, 0o700)
    credential = config / "github-operations.env"
    credential.write_bytes(b"GITHUB_TOKEN=disposable-qualification-only\n")
    os.chmod(credential, 0o600)

    operations = root / "var" / "lib" / "keelaryn" / "operations"
    operations.mkdir(parents=True, mode=0o700)
    os.chmod(operations, 0o700)

    transport = root / "var" / "lib" / "keelaryn-operation-transport"
    (transport / "inbox").mkdir(parents=True, mode=0o770)
    (transport / "outbox").mkdir(mode=0o770)
    os.chmod(transport, 0o750)

    sentinels = root / "sentinels"
    sentinels.mkdir()
    hub = sentinels / "hub.env"
    drive = sentinels / "drive-authority.json"
    hub.write_bytes(b"KEELARYN_HUB_ROOT_ID=DISPOSABLE_OLD_SENTINEL\n")
    drive.write_bytes(b'{"drive_mutation_allowed":false}\n')

    return {
        "root": root,
        "install": install,
        "releases": releases,
        "unit_dir": unit_dir,
        "credential": credential,
        "operations": operations,
        "transport": transport,
        "updates": root / "var" / "lib" / "keelaryn" / "operation-control-d0-updates",
        "hub": hub,
        "drive": drive,
    }


def _anchors(layout: dict[str, Path]) -> dict[str, Any]:
    return {
        "production_current": os.readlink(layout["install"] / "current"),
        "credential_sha256": _file_sha(layout["credential"]),
        "hub_sha256": _file_sha(layout["hub"]),
        "drive_sha256": _file_sha(layout["drive"]),
    }


def _assert_anchors(layout: dict[str, Path], before: dict[str, Any]) -> None:
    after = _anchors(layout)
    if after != before:
        raise QualificationError(
            f"non-control boundary mutated: before={before}; after={after}"
        )


def _unit_bytes(layout: dict[str, Path], source: str, name: str) -> bytes:
    return (
        layout["releases"]
        / source
        / "deploy"
        / "zero-based-vps"
        / name
    ).read_bytes()


def _assert_old_boundary(layout: dict[str, Path]) -> None:
    if os.readlink(layout["install"] / "control-current") != f"releases/{OLD_SOURCE}":
        raise QualificationError("control-current is not exact r0005 predecessor")
    for name in PERSISTENT_UNITS:
        path = layout["unit_dir"] / name
        if path.is_symlink() or path.read_bytes() != _unit_bytes(layout, OLD_SOURCE, name):
            raise QualificationError(f"predecessor unit bytes mismatch: {name}")
        if stat.S_IMODE(path.stat().st_mode) != 0o644:
            raise QualificationError(f"predecessor unit mode mismatch: {name}")
    static = layout["unit_dir"] / STATIC_UNIT
    if static.exists() or static.is_symlink():
        raise QualificationError("r0005 boundary unexpectedly contains snapshot unit")


def _assert_new_boundary(layout: dict[str, Path]) -> None:
    if os.readlink(layout["install"] / "control-current") != f"releases/{NEW_SOURCE}":
        raise QualificationError("control-current is not exact r0007 successor")
    for name in PERSISTENT_UNITS:
        path = layout["unit_dir"] / name
        if path.is_symlink() or path.read_bytes() != _unit_bytes(layout, NEW_SOURCE, name):
            raise QualificationError(f"successor unit bytes mismatch: {name}")
        if stat.S_IMODE(path.stat().st_mode) != 0o644:
            raise QualificationError(f"successor unit mode mismatch: {name}")
    static = layout["unit_dir"] / STATIC_UNIT
    if (
        static.is_symlink()
        or not static.is_file()
        or static.read_bytes() != _unit_bytes(layout, NEW_SOURCE, STATIC_UNIT)
        or stat.S_IMODE(static.stat().st_mode) != 0o644
    ):
        raise QualificationError("r0007 snapshot static-unit boundary mismatch")


def _invoke(module, layout: dict[str, Path], runtime: Runtime):
    return module.update_d0_control_plane(
        install_root=layout["install"],
        unit_dir=layout["unit_dir"],
        credential_path=layout["credential"],
        operation_root=layout["operations"],
        transport_root=layout["transport"],
        update_root=layout["updates"],
        expected_old_source_commit=OLD_SOURCE,
        expected_old_payload_sha256=OLD_PAYLOAD,
        expected_new_source_commit=NEW_SOURCE,
        expected_new_payload_sha256=NEW_PAYLOAD,
        systemctl=runtime.systemctl,
        active_probe=runtime.active_probe,
        enabled_probe=runtime.enabled_probe,
        restart_probe=runtime.restart_probe,
        sleeper=lambda seconds: None,
    )


def _transaction(layout: dict[str, Path]) -> dict[str, Path]:
    root = layout["updates"]
    if root.is_symlink() or not root.is_dir():
        raise QualificationError("transaction root missing")
    entries = [item for item in root.iterdir() if item.is_dir() and not item.is_symlink()]
    if len(entries) != 1:
        raise QualificationError("expected exactly one D0 update transaction")
    tx = entries[0]
    return {
        "root": tx,
        "prepared": tx / "PREPARED.json",
        "completed": tx / "COMPLETED.json",
        "rolled": tx / "ROLLED_BACK.json",
    }


def _assert_transaction(
    layout: dict[str, Path],
    *,
    completed: bool,
    rolled: bool,
) -> dict[str, Path]:
    tx = _transaction(layout)
    if not tx["prepared"].is_file():
        raise QualificationError("PREPARED authority missing")
    if tx["completed"].exists() is not completed:
        raise QualificationError("COMPLETED authority presence mismatch")
    if tx["rolled"].exists() is not rolled:
        raise QualificationError("ROLLED_BACK authority presence mismatch")
    return tx


def _publication_hashes(layout: dict[str, Path]) -> dict[str, str]:
    result = {
        "control_target": os.readlink(layout["install"] / "control-current"),
    }
    for name in PERSISTENT_UNITS:
        result[f"unit:{name}"] = _file_sha(layout["unit_dir"] / name)
    static = layout["unit_dir"] / STATIC_UNIT
    result[f"unit:{STATIC_UNIT}"] = _file_sha(static) if static.is_file() else "ABSENT"
    return result


def _forbid_republication(module):
    old_file = module.legacy._atomic_file
    old_link = module.legacy._atomic_symlink

    def denied_file(*args, **kwargs):
        raise QualificationError("unexpected unit republish during recovery/replay")

    def denied_link(*args, **kwargs):
        raise QualificationError("unexpected control-current republish during recovery/replay")

    module.legacy._atomic_file = denied_file
    module.legacy._atomic_symlink = denied_link
    return old_file, old_link


def _restore_republication(module, original) -> None:
    module.legacy._atomic_file, module.legacy._atomic_symlink = original


def _run_child(
    *,
    mode: str,
    layout: dict[str, Path],
    template_releases: Path,
) -> int:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--child-crash",
            mode,
            "--scenario-root",
            str(layout["root"]),
            "--template-releases",
            str(template_releases),
        ],
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return completed.returncode


def _scenario_success(module, template_releases: Path, root: Path) -> dict[str, Any]:
    layout = _layout(template_releases, root)
    before = _anchors(layout)
    _assert_old_boundary(layout)
    runtime = Runtime()

    result = _invoke(module, layout, runtime)

    if result.get("schema") != module.COMPLETED_SCHEMA:
        raise QualificationError("success scenario did not return COMPLETED")
    if result.get("remote_mutation_handlers") != "ABSENT":
        raise QualificationError("success scenario retained mutation handler")
    _assert_new_boundary(layout)
    _assert_transaction(layout, completed=True, rolled=False)
    _assert_anchors(layout, before)
    if runtime.active != set(PERSISTENT_UNITS):
        raise QualificationError("success scenario persistent services not active")
    if STATIC_UNIT in runtime.active:
        raise QualificationError("snapshot template became active")
    return {"result": "COMPLETED", "anchors_unchanged": True}


def _scenario_rollback(module, template_releases: Path, root: Path) -> dict[str, Any]:
    layout = _layout(template_releases, root)
    before = _anchors(layout)
    _assert_old_boundary(layout)
    runtime = Runtime(fail_successor_agent_once=True)
    try:
        _invoke(module, layout, runtime)
    except module.D0ControlUpdateError as exc:
        if "rolled back exactly" not in str(exc):
            raise QualificationError("rollback scenario returned wrong failure") from exc
    else:
        raise QualificationError("rollback scenario unexpectedly succeeded")

    _assert_old_boundary(layout)
    _assert_transaction(layout, completed=False, rolled=True)
    _assert_anchors(layout, before)
    if runtime.active != set(PERSISTENT_UNITS):
        raise QualificationError("rollback did not restore active predecessor services")
    return {"result": "ROLLED_BACK", "anchors_unchanged": True}


def _scenario_prepared_old(module, template_releases: Path, root: Path) -> dict[str, Any]:
    layout = _layout(template_releases, root)
    before = _anchors(layout)
    code = _run_child(
        mode="PREPARED_OLD",
        layout=layout,
        template_releases=template_releases,
    )
    if code != 91:
        raise QualificationError(f"PREPARED/OLD crash exit mismatch: {code}")
    _assert_old_boundary(layout)
    _assert_transaction(layout, completed=False, rolled=False)

    runtime = Runtime(initially_active=False)
    result = _invoke(module, layout, runtime)
    if result.get("schema") != module.COMPLETED_SCHEMA:
        raise QualificationError("PREPARED/OLD recovery did not complete")
    _assert_new_boundary(layout)
    _assert_transaction(layout, completed=True, rolled=False)
    _assert_anchors(layout, before)
    return {"result": "RECOVERED_TO_COMPLETED", "anchors_unchanged": True}


def _scenario_prepared_new(module, template_releases: Path, root: Path) -> dict[str, Any]:
    layout = _layout(template_releases, root)
    before = _anchors(layout)
    code = _run_child(
        mode="PREPARED_NEW",
        layout=layout,
        template_releases=template_releases,
    )
    if code != 92:
        raise QualificationError(f"PREPARED/NEW crash exit mismatch: {code}")
    _assert_new_boundary(layout)
    _assert_transaction(layout, completed=False, rolled=False)
    published = _publication_hashes(layout)

    runtime = Runtime(initially_active=False)
    original = _forbid_republication(module)
    try:
        result = _invoke(module, layout, runtime)
    finally:
        _restore_republication(module, original)
    if result.get("schema") != module.COMPLETED_SCHEMA:
        raise QualificationError("PREPARED/NEW recovery did not complete")
    if _publication_hashes(layout) != published:
        raise QualificationError("PREPARED/NEW recovery changed published bytes")
    _assert_new_boundary(layout)
    _assert_transaction(layout, completed=True, rolled=False)
    _assert_anchors(layout, before)
    return {
        "result": "TERMINALIZED_WITHOUT_REPUBLICATION",
        "anchors_unchanged": True,
    }


def _scenario_partial_foreign(module, template_releases: Path, root: Path) -> dict[str, Any]:
    layout = _layout(template_releases, root)
    before = _anchors(layout)
    code = _run_child(
        mode="PREPARED_OLD",
        layout=layout,
        template_releases=template_releases,
    )
    if code != 91:
        raise QualificationError(f"PARTIAL seed crash exit mismatch: {code}")
    tx = _assert_transaction(layout, completed=False, rolled=False)

    foreign = layout["unit_dir"] / "keelaryn-operation-agent.service"
    foreign.write_bytes(b"FOREIGN-NON-TRANSACTION-BYTES\n")
    os.chmod(foreign, 0o644)
    foreign_sha = _file_sha(foreign)

    runtime = Runtime(initially_active=False)
    try:
        _invoke(module, layout, runtime)
    except module.D0ControlUpdateError as exc:
        if "partial; reconcile first" not in str(exc):
            raise QualificationError("PARTIAL boundary returned wrong failure") from exc
    else:
        raise QualificationError("PARTIAL foreign boundary unexpectedly succeeded")

    if _file_sha(foreign) != foreign_sha:
        raise QualificationError("PARTIAL recovery overwrote foreign bytes")
    if os.readlink(layout["install"] / "control-current") != f"releases/{OLD_SOURCE}":
        raise QualificationError("PARTIAL recovery moved control-current")
    if tx["completed"].exists() or tx["rolled"].exists():
        raise QualificationError("PARTIAL recovery wrote terminal authority")
    _assert_anchors(layout, before)
    return {
        "result": "FAIL_CLOSED_RECONCILE_REQUIRED",
        "foreign_bytes_untouched": True,
        "anchors_unchanged": True,
    }


def _scenario_completed_replay(module, template_releases: Path, root: Path) -> dict[str, Any]:
    layout = _layout(template_releases, root)
    before = _anchors(layout)
    runtime = Runtime()
    first = _invoke(module, layout, runtime)
    if first.get("schema") != module.COMPLETED_SCHEMA:
        raise QualificationError("COMPLETED replay seed did not complete")
    _assert_new_boundary(layout)
    tx = _assert_transaction(layout, completed=True, rolled=False)
    completed_raw = tx["completed"].read_bytes()
    published = _publication_hashes(layout)

    runtime.active.clear()
    original = _forbid_republication(module)
    try:
        second = _invoke(module, layout, runtime)
    finally:
        _restore_republication(module, original)

    if second != first:
        raise QualificationError("COMPLETED replay authority changed")
    if tx["completed"].read_bytes() != completed_raw:
        raise QualificationError("COMPLETED replay rewrote terminal authority")
    if _publication_hashes(layout) != published:
        raise QualificationError("COMPLETED replay changed published bytes")
    if runtime.active != set(PERSISTENT_UNITS):
        raise QualificationError("COMPLETED replay did not restore services")
    _assert_anchors(layout, before)
    return {
        "result": "IDEMPOTENT_SERVICE_RECOVERY",
        "republished": False,
        "anchors_unchanged": True,
    }


def _child_crash(
    *,
    mode: str,
    scenario_root: Path,
    template_releases: Path,
) -> int:
    module = _load_updater(template_releases)
    layout = {
        "root": scenario_root,
        "install": scenario_root / "opt" / "keelaryn",
        "releases": scenario_root / "opt" / "keelaryn" / "releases",
        "unit_dir": scenario_root / "systemd",
        "credential": (
            scenario_root
            / "etc"
            / "keelaryn"
            / "operation-control"
            / "github-operations.env"
        ),
        "operations": (
            scenario_root
            / "var"
            / "lib"
            / "keelaryn"
            / "operations"
        ),
        "transport": (
            scenario_root
            / "var"
            / "lib"
            / "keelaryn-operation-transport"
        ),
        "updates": (
            scenario_root
            / "var"
            / "lib"
            / "keelaryn"
            / "operation-control-d0-updates"
        ),
    }
    runtime = Runtime(crash_mode=mode)
    _invoke(module, layout, runtime)
    raise QualificationError("crash child unexpectedly returned")


def qualify(template_releases: Path, work_root: Path) -> dict[str, Any]:
    template_releases = template_releases.resolve()
    work_root = work_root.resolve()
    for source in (OLD_SOURCE, NEW_SOURCE):
        release = template_releases / source
        if release.is_symlink() or not release.is_dir():
            raise QualificationError(f"exact template release missing: {source}")
    work_root.mkdir(parents=True, exist_ok=True)

    module = _load_updater(template_releases)
    scenarios: dict[str, Any] = {}
    definitions = (
        ("success", _scenario_success),
        ("rollback", _scenario_rollback),
        ("prepared_old_exact", _scenario_prepared_old),
        ("prepared_new_exact", _scenario_prepared_new),
        ("partial_foreign", _scenario_partial_foreign),
        ("completed_replay", _scenario_completed_replay),
    )
    for name, callback in definitions:
        root = work_root / name
        if root.exists() or root.is_symlink():
            raise QualificationError(f"scenario root already exists: {name}")
        root.mkdir()
        scenarios[name] = callback(module, template_releases, root)

    return {
        "schema": SCHEMA,
        "candidate": CANDIDATE,
        "predecessor_candidate": PREDECESSOR,
        "predecessor_source_commit": OLD_SOURCE,
        "predecessor_payload_sha256": OLD_PAYLOAD,
        "candidate_source_commit": NEW_SOURCE,
        "candidate_payload_sha256": NEW_PAYLOAD,
        "production_source_commit": PRODUCTION_SOURCE,
        "scenarios": scenarios,
        "scenario_count": len(scenarios),
        "all_non_control_anchors_unchanged": True,
        "production_current_mutated": False,
        "credential_mutated": False,
        "hub_selector_mutated": False,
        "drive_mutations_performed": False,
        "production_vps_mutations_performed": False,
        "disposable_only": True,
        "qualification_result": "PASS",
        "production_qualified": False,
        "next_action": "FRESH_READ_ONLY_VPS_RECONCILE",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0007-transition"
    )
    parser.add_argument("--template-releases", required=True, type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--child-crash",
        choices=("PREPARED_OLD", "PREPARED_NEW"),
    )
    parser.add_argument("--scenario-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.child_crash is not None:
            if args.scenario_root is None:
                raise QualificationError("--scenario-root required for child crash")
            return _child_crash(
                mode=args.child_crash,
                scenario_root=args.scenario_root.resolve(),
                template_releases=args.template_releases.resolve(),
            )

        if args.work_root is None:
            raise QualificationError("--work-root is required")
        value = qualify(
            args.template_releases,
            args.work_root,
        )
        raw = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(raw, encoding="utf-8", newline="\n")
        print(raw, end="")
        return 0
    except (QualificationError, OSError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-r0007-transition-failure.v1",
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
