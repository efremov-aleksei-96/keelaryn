from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


GATE_REVISION = "operation-control-r0009-bootstrap-prep-r0001"
CANDIDATE = "operation-control-r0009-20260924-01"
PREDECESSOR_CANDIDATE = "operation-control-r0005-20260921-01"
REPOSITORY = "https://github.com/efremov-aleksei-96/keelaryn.git"

SOURCE_COMMIT = "e42a4f156abb048f5c8f0bd1884fcae51674a55f"
SOURCE_TREE = "4eccddde06351d91e9bb2dcffa37e77344651621"
PAYLOAD_SHA256 = "8592a314b084a2a1ccc1608168b3c0776cccb1277ffc049f42f3efd5291d4876"
PAYLOAD_SIZE = 442514
PAYLOAD_FILE_COUNT = 227

PREDECESSOR_SOURCE_COMMIT = "08f2e211f53764590f6ff0f05f86b2de62c14418"
PREDECESSOR_PAYLOAD_SHA256 = "6272afbe918d33c29a3f72354baca9e781b3960b3f0f465e1598b5bbc794a7e7"
PREDECESSOR_PAYLOAD_SIZE = 365052
PREDECESSOR_PAYLOAD_FILE_COUNT = 190

PRODUCTION_SOURCE = "e63f371d14eb9b6069cb2f1b5fad5f4b68a49d4f"
HUB_TRANSACTION_ID = "61a2bfb65c9a47d088a76eee0df89d14"
ACTIVE_TRANSACTION_SHA256 = "1d243586556019e132c454ebc8ccc252b755e5b43421434a6ff1eaf1c166ea34"
OLD_SELECTOR_IDENTITY_SHA256 = "15370553b6732a11d4e0a9a8a02066c1c089d8b0f443001cc39fe39b201c8444"
NEW_SELECTOR_IDENTITY_SHA256 = "dffc1b46b44d951b498ee7d781f6b992f0dc6356cfb38eebadbee792a847db39"
CREDENTIAL_SHA256 = "7002ed72a223dd7fc860451c53a4ec8f264d14f7144000559a295522b7cbe928"

RECORDED_EVIDENCE = (
    "docs/evidence/D0_02D_LEGACY_RUNTIME_RECONCILE_2026-09-21T201610Z.json"
)

INSTALL_ROOT = Path("/opt/keelaryn")
RELEASES_ROOT = INSTALL_ROOT / "releases"
PRODUCTION_CURRENT = INSTALL_ROOT / "current"
CONTROL_CURRENT = INSTALL_ROOT / "control-current"
SELECTOR = Path("/etc/keelaryn/hub.env")
STATE_ROOT = Path("/var/lib/keelaryn/deployment")
MUTATION_GATE_ROOT = Path("/var/lib/keelaryn/mutation-gate")
UNIT_DIR = Path("/etc/systemd/system")
CONFIG_DIR = Path("/etc/keelaryn/operation-control")
CREDENTIAL_PATH = CONFIG_DIR / "github-operations.env"
BOOTSTRAP_ROOT = Path("/var/lib/keelaryn/operation-bootstrap")

PERSISTENT_UNITS = (
    "keelaryn-operation-transport.service",
    "keelaryn-operation-agent.service",
)
SNAPSHOT_UNIT = "keelaryn-production-snapshot@.service"


class PrepError(RuntimeError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _strict_json(raw: bytes, label: str) -> Any:
    def hook(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise PrepError(f"{label}: duplicate JSON key")
            value[key] = item
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=hook)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrepError(f"{label}: invalid JSON") from exc
    if raw != _canonical(value):
        raise PrepError(f"{label}: non-canonical JSON bytes")
    return value


def _run(
    args: list[str],
    *,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            args,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrepError(f"command execution failed: {args[0]}") from exc
    if completed.returncode != 0:
        raise PrepError(
            f"command failed: {args[0]}: {completed.stderr.strip()}"
        )
    return completed


def _json_command(
    args: list[str],
    *,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = _run(args, timeout=timeout, env=env)
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PrepError(f"command returned invalid JSON: {args[0]}") from exc
    if not isinstance(value, dict):
        raise PrepError(f"command JSON is not an object: {args[0]}")
    return value


def _require_root() -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise PrepError("live reconcile must run as root on the VPS")


def _readlink_exact(path: Path, expected: str, label: str) -> None:
    if not path.is_symlink():
        raise PrepError(f"{label}: not a symlink")
    observed = os.readlink(path)
    if observed != expected:
        raise PrepError(f"{label}: unexpected target")


def _regular(path: Path, *, mode: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PrepError(f"{label}: missing/not regular")
    info = path.stat(follow_symlinks=False)
    if os.name == "posix" and (
        info.st_uid != 0 or stat.S_IMODE(info.st_mode) != mode
    ):
        raise PrepError(f"{label}: owner/mode mismatch")
    return path.read_bytes()


def _systemd_show(unit: str) -> dict[str, Any]:
    completed = _run(
        [
            "systemctl",
            "show",
            unit,
            "--property=ActiveState",
            "--property=MainPID",
        ],
        timeout=30,
    )
    parsed: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key] = value
    if set(parsed) != {"ActiveState", "MainPID"}:
        raise PrepError(f"systemd response incomplete: {unit}")
    try:
        pid = int(parsed["MainPID"])
    except ValueError as exc:
        raise PrepError(f"systemd MainPID invalid: {unit}") from exc
    return {
        "active_state": parsed["ActiveState"].upper(),
        "main_pid": pid,
    }


def _enabled_state(unit: str) -> str:
    completed = _run(["systemctl", "is-enabled", unit], timeout=30)
    state = completed.stdout.strip()
    if state not in {"enabled", "enabled-runtime", "static"}:
        raise PrepError(f"unexpected enabled state: {unit}")
    return state


def _load_predecessor_materialize():
    path = (
        RELEASES_ROOT
        / PREDECESSOR_SOURCE_COMMIT
        / "deploy"
        / "zero-based-vps"
        / "materialize_payload.py"
    )
    spec = importlib.util.spec_from_file_location(
        "keelaryn_r0005_materialize_exact",
        path,
    )
    if spec is None or spec.loader is None:
        raise PrepError("cannot load exact predecessor release verifier")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
        raise
    return module


def _credential_anchor() -> dict[str, Any]:
    raw = _regular(
        CREDENTIAL_PATH,
        mode=0o600,
        label="GitHub operations credential",
    )
    if _sha(raw) != CREDENTIAL_SHA256:
        raise PrepError("credential SHA-256 differs from fresh D0-02D evidence")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise PrepError("credential is not ASCII") from exc

    expected_keys = (
        "KEELARYN_GITHUB_OPERATIONS_TOKEN",
        "KEELARYN_GITHUB_OPERATIONS_REPOSITORY",
        "KEELARYN_GITHUB_OPERATIONS_ISSUE",
        "KEELARYN_GITHUB_OPERATIONS_ACTORS",
        "KEELARYN_GITHUB_OPERATIONS_STATUS_ACTOR",
    )
    lines = text.splitlines()
    if (
        len(lines) != len(expected_keys)
        or raw != ("\n".join(lines) + "\n").encode("ascii")
    ):
        raise PrepError("credential format is not canonical")
    values: dict[str, str] = {}
    for line, key in zip(lines, expected_keys):
        prefix = key + "="
        if not line.startswith(prefix):
            raise PrepError("credential key/order mismatch")
        values[key] = line[len(prefix):]
    if re.fullmatch(r"[A-Za-z0-9_]{20,255}", values[expected_keys[0]]) is None:
        raise PrepError("credential token format invalid")
    if values[expected_keys[1]] != "efremov-aleksei-96/keelaryn":
        raise PrepError("credential repository mismatch")
    if values[expected_keys[2]] != "65":
        raise PrepError("credential issue mismatch")
    if values[expected_keys[3]] != "efremov-aleksei-96":
        raise PrepError("credential actor mismatch")
    if values[expected_keys[4]] != "efremov-aleksei-96":
        raise PrepError("credential status actor mismatch")

    receipt = _strict_json(
        _regular(
            BOOTSTRAP_ROOT / "bootstrap-receipt.json",
            mode=0o600,
            label="bootstrap receipt",
        ),
        "bootstrap receipt",
    )
    expected_receipt = {
        "schema": "keelaryn.operation-control-bootstrap-receipt.v1",
        "source_commit": PREDECESSOR_SOURCE_COMMIT,
        "payload_sha256": PREDECESSOR_PAYLOAD_SHA256,
        "repository": "efremov-aleksei-96/keelaryn",
        "issue": 65,
        "actors": "efremov-aleksei-96",
        "status_actor": "efremov-aleksei-96",
        "production_current_unchanged": True,
        "control_current_exact": True,
        "transport_active": True,
        "agent_active": True,
    }
    if receipt != expected_receipt:
        raise PrepError("bootstrap receipt mismatch")
    return {
        "sha256": CREDENTIAL_SHA256,
        "bootstrap_receipt_exact": True,
        "repository": "efremov-aleksei-96/keelaryn",
        "issue": 65,
    }


def _legacy_hub_anchor() -> dict[str, Any]:
    selector_raw = _regular(SELECTOR, mode=0o600, label="legacy Hub selector")
    try:
        selector_text = selector_raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise PrepError("legacy Hub selector is not ASCII") from exc
    prefix = "KEELARYN_HUB_ROOT_ID="
    if (
        not selector_text.startswith(prefix)
        or not selector_text.endswith("\n")
        or selector_text.count("\n") != 1
    ):
        raise PrepError("legacy Hub selector is not canonical")
    selector = selector_text[len(prefix):-1]

    active_path = STATE_ROOT / "ACTIVE_TRANSACTION.json"
    active_raw = _regular(
        active_path,
        mode=0o600,
        label="legacy ACTIVE_TRANSACTION",
    )
    active = _strict_json(active_raw, "legacy ACTIVE_TRANSACTION")
    if set(active) != {
        "schema",
        "transaction_id",
        "tool",
        "finalizers",
        "old_hub_root_id",
        "new_hub_root_id",
    }:
        raise PrepError("legacy ACTIVE_TRANSACTION keys mismatch")
    if active.get("schema") != "keelaryn.zero-vps-hub-cutover.v2":
        raise PrepError("legacy ACTIVE_TRANSACTION schema mismatch")
    if active.get("transaction_id") != HUB_TRANSACTION_ID:
        raise PrepError("legacy Hub transaction id mismatch")
    if _sha(active_raw) != ACTIVE_TRANSACTION_SHA256:
        raise PrepError("legacy ACTIVE_TRANSACTION SHA mismatch")

    old_id = active.get("old_hub_root_id")
    new_id = active.get("new_hub_root_id")
    if not isinstance(old_id, str) or not isinstance(new_id, str):
        raise PrepError("legacy Hub identity type invalid")
    if _sha(old_id.encode("utf-8")) != OLD_SELECTOR_IDENTITY_SHA256:
        raise PrepError("legacy OLD selector identity mismatch")
    if _sha(new_id.encode("utf-8")) != NEW_SELECTOR_IDENTITY_SHA256:
        raise PrepError("legacy NEW selector identity mismatch")
    if selector != old_id:
        raise PrepError("legacy Hub selector is not exact OLD")

    tool = active.get("tool")
    if not isinstance(tool, dict) or set(tool) != {"source_commit", "sha256"}:
        raise PrepError("legacy Hub tool identity invalid")
    if tool["source_commit"] != PRODUCTION_SOURCE:
        raise PrepError("legacy Hub tool source mismatch")

    production_release = RELEASES_ROOT / PRODUCTION_SOURCE
    hub_tool = production_release / "deploy" / "zero-based-vps" / "hub_cutover.py"
    if _sha(hub_tool.read_bytes()) != tool["sha256"]:
        raise PrepError("legacy Hub tool bytes mismatch")

    finalizers = active.get("finalizers")
    expected_finalizers = {
        "pre_apply_sha256": _sha(
            (
                production_release
                / "tests"
                / "live"
                / "run_migration_pre_apply_cutover.py"
            ).read_bytes()
        ),
        "post_cutover_sha256": _sha(
            (
                production_release
                / "tests"
                / "live"
                / "run_migration_post_cutover_acceptance.py"
            ).read_bytes()
        ),
    }
    if finalizers != expected_finalizers:
        raise PrepError("legacy Hub finalizer identity mismatch")

    terminal = STATE_ROOT / "terminal" / (HUB_TRANSACTION_ID + ".json")
    if terminal.exists() or terminal.is_symlink():
        raise PrepError("legacy Hub transaction unexpectedly terminal")

    status = _json_command(
        [
            sys.executable,
            "-B",
            str(hub_tool),
            "--selector-path",
            str(SELECTOR),
            "--state-root",
            str(STATE_ROOT),
            "--mutation-gate-root",
            str(MUTATION_GATE_ROOT),
            "--source-commit",
            PRODUCTION_SOURCE,
            "status",
        ],
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if status != {
        "status": "PREPARED",
        "transaction_id": HUB_TRANSACTION_ID,
    }:
        raise PrepError("legacy Hub status is not exact PREPARED")

    core = production_release / "core"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    from keelaryn_core.drive_mutation_gate import (  # type: ignore
        INHIBIT_NAME,
        read_mutation_inhibit,
    )

    inhibit = read_mutation_inhibit(MUTATION_GATE_ROOT)
    if inhibit is None:
        raise PrepError("legacy mutation inhibit is absent")
    inhibit_raw = _regular(
        MUTATION_GATE_ROOT / INHIBIT_NAME,
        mode=0o640,
        label="legacy Drive mutation inhibit",
    )
    expected_old_selector = _sha(
        ("KEELARYN_HUB_ROOT_ID=" + old_id + "\n").encode("ascii")
    )
    expected_new_selector = _sha(
        ("KEELARYN_HUB_ROOT_ID=" + new_id + "\n").encode("ascii")
    )
    if not (
        inhibit["transaction_id"] == HUB_TRANSACTION_ID
        and inhibit["active_transaction_sha256"] == ACTIVE_TRANSACTION_SHA256
        and inhibit["source_commit"] == PRODUCTION_SOURCE
        and inhibit["tool_sha256"] == tool["sha256"]
        and inhibit["old_selector_sha256"] == expected_old_selector
        and inhibit["new_selector_sha256"] == expected_new_selector
    ):
        raise PrepError("legacy mutation inhibit authority mismatch")

    return {
        "status": "PREPARED",
        "transaction_id": HUB_TRANSACTION_ID,
        "active_transaction_sha256": ACTIVE_TRANSACTION_SHA256,
        "selector_role": "OLD",
        "old_selector_identity_sha256": OLD_SELECTOR_IDENTITY_SHA256,
        "new_selector_identity_sha256": NEW_SELECTOR_IDENTITY_SHA256,
        "mutation_inhibit": {
            "state": "PRESENT",
            "sha256": _sha(inhibit_raw),
            "authority_matches": True,
        },
        "authority_scope": "RUNTIME_SAFETY_ONLY",
    }


def _production_anchor() -> dict[str, Any]:
    _require_root()
    _readlink_exact(
        PRODUCTION_CURRENT,
        f"releases/{PRODUCTION_SOURCE}",
        "production current",
    )
    _readlink_exact(
        CONTROL_CURRENT,
        f"releases/{PREDECESSOR_SOURCE_COMMIT}",
        "control current",
    )

    predecessor_release = RELEASES_ROOT / PREDECESSOR_SOURCE_COMMIT
    verifier = _load_predecessor_materialize()
    try:
        identity = verifier.verify_release_directory(
            predecessor_release,
            expected_source_commit=PREDECESSOR_SOURCE_COMMIT,
            expected_payload_sha256=PREDECESSOR_PAYLOAD_SHA256,
        )
    except Exception as exc:
        raise PrepError("exact predecessor release verification failed") from exc
    expected_identity = {
        "payload_sha256": PREDECESSOR_PAYLOAD_SHA256,
        "payload_size": PREDECESSOR_PAYLOAD_SIZE,
        "file_count": PREDECESSOR_PAYLOAD_FILE_COUNT,
    }
    observed_identity = {
        key: identity.get(key)
        for key in expected_identity
    }
    if observed_identity != expected_identity:
        raise PrepError("predecessor release size/count identity mismatch")

    deploy = predecessor_release / "deploy" / "zero-based-vps"
    units: dict[str, Any] = {}
    for name in PERSISTENT_UNITS:
        installed = _regular(UNIT_DIR / name, mode=0o644, label=name)
        expected = (deploy / name).read_bytes()
        if installed != expected:
            raise PrepError(f"installed predecessor unit bytes mismatch: {name}")
        state = _systemd_show(name)
        enabled = _enabled_state(name)
        if state["active_state"] != "ACTIVE" or state["main_pid"] <= 0:
            raise PrepError(f"predecessor service is not active: {name}")
        if enabled not in {"enabled", "enabled-runtime"}:
            raise PrepError(f"predecessor service is not enabled: {name}")
        units[name] = {
            "sha256": _sha(installed),
            "exact_release_bytes": True,
            "enabled": enabled,
            **state,
        }

    snapshot = UNIT_DIR / SNAPSHOT_UNIT
    if snapshot.exists() or snapshot.is_symlink():
        raise PrepError("partial r0009 snapshot unit is already present")

    writer = _systemd_show("keelaryn-drive.service")
    if writer != {"active_state": "INACTIVE", "main_pid": 0}:
        raise PrepError("writer is not exact INACTIVE/MainPID=0")

    return {
        "production_source_commit": PRODUCTION_SOURCE,
        "control_source_commit": PREDECESSOR_SOURCE_COMMIT,
        "control_release": {
            "exact": True,
            **observed_identity,
        },
        "services": {
            "writer": writer,
            "operation_units": units,
        },
        "legacy_hub": _legacy_hub_anchor(),
        "credential": _credential_anchor(),
        "r0009_snapshot_unit": "ABSENT",
    }


def reconcile() -> dict[str, Any]:
    first = _production_anchor()
    second = _production_anchor()
    if first != second:
        raise PrepError("production boundary changed between read-only passes")
    return {
        "schema": "keelaryn.operation-control-r0009-bootstrap-reconcile.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "predecessor_candidate": PREDECESSOR_CANDIDATE,
        "production_boundary": second,
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
        "production_mutations_performed": False,
        "drive_mutations_performed": False,
        "production_authorized": False,
        "next_action": "QUALIFY_BOOTSTRAP_INPUTS",
    }


def _checkout_frozen(work: Path) -> Path:
    source = work / "source"
    _run(["git", "init", "-q", str(source)])
    _run(["git", "-C", str(source), "remote", "add", "origin", REPOSITORY])
    _run(
        [
            "git",
            "-C",
            str(source),
            "fetch",
            "-q",
            "--depth",
            "1",
            "origin",
            SOURCE_COMMIT,
        ],
        timeout=300,
    )
    _run(["git", "-C", str(source), "checkout", "-q", "--detach", "FETCH_HEAD"])
    head = _run(["git", "-C", str(source), "rev-parse", "HEAD"]).stdout.strip()
    tree = _run(
        ["git", "-C", str(source), "rev-parse", "HEAD^{tree}"]
    ).stdout.strip()
    dirty = _run(["git", "-C", str(source), "status", "--porcelain"]).stdout
    if head != SOURCE_COMMIT or tree != SOURCE_TREE or dirty:
        raise PrepError("frozen r0009 source identity mismatch")
    return source


def _rebuild_frozen(source: Path, work: Path) -> dict[str, Any]:
    builder = source / "deploy" / "zero-based-vps" / "build_payload.py"
    first = work / "first.tar.gz"
    second = work / "second.tar.gz"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    first_meta = _json_command(
        [
            sys.executable,
            "-B",
            str(builder),
            "--repo-root",
            str(source),
            "--source-commit",
            SOURCE_COMMIT,
            "--output",
            str(first),
        ],
        timeout=600,
        env=env,
    )
    second_meta = _json_command(
        [
            sys.executable,
            "-B",
            str(builder),
            "--repo-root",
            str(source),
            "--source-commit",
            SOURCE_COMMIT,
            "--output",
            str(second),
        ],
        timeout=600,
        env=env,
    )
    first_raw = first.read_bytes()
    if first_raw != second.read_bytes():
        raise PrepError("frozen r0009 payload rebuild is not deterministic")
    observed = {
        "source_commit": first_meta.get("source_commit"),
        "payload_sha256": _sha(first_raw),
        "payload_size": len(first_raw),
        "file_count": first_meta.get("file_count"),
    }
    expected = {
        "source_commit": SOURCE_COMMIT,
        "payload_sha256": PAYLOAD_SHA256,
        "payload_size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }
    if observed != expected:
        raise PrepError(f"frozen r0009 payload identity mismatch: {observed}")
    for key in expected:
        if second_meta.get(key) != first_meta.get(key):
            raise PrepError("second frozen payload metadata differs")
    return observed


def _recorded_boundary(repository_root: Path) -> dict[str, Any]:
    state_path = repository_root / "DEVELOPMENT_STATE.json"
    candidate_path = (
        repository_root
        / "docs"
        / "candidates"
        / "operation-control-r0009-20260924-01.json"
    )
    for path, label in (
        (state_path, "development state"),
        (candidate_path, "r0009 candidate receipt"),
    ):
        if path.is_symlink() or not path.is_file():
            raise PrepError(f"{label} missing/not regular")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))

    architecture = state.get("architecture", {})
    if architecture.get("model") != "CORPUS_FIRST":
        raise PrepError("development state is not Corpus-first")
    if architecture.get("authority_model") != "LAYERED_CORPUS_FIRST":
        raise PrepError("development state authority model is not layered Corpus-first")
    if architecture.get("legacy_hub_authority") != (
        "PROVENANCE_AND_TEMPORARY_PRE_CUTOVER_RUNTIME_BOUNDARY_ONLY"
    ):
        raise PrepError("legacy Hub authority boundary is not exact")

    production = state.get("production_boundary", {})
    if production.get("freshness") != "LIVE_VERIFIED_READ_ONLY_D0":
        raise PrepError("production boundary is not live-verified read-only D0")
    if production.get("source_commit") != PRODUCTION_SOURCE:
        raise PrepError("production source boundary mismatch")
    installed = production.get("installed_operation_control", {})
    if installed != {
        "candidate": PREDECESSOR_CANDIDATE,
        "source_commit": PREDECESSOR_SOURCE_COMMIT,
        "state": "INSTALLED_RUNTIME_ACCEPTED",
    }:
        raise PrepError("recorded predecessor control boundary mismatch")
    if production.get("hub_cutover_status") != "PREPARED":
        raise PrepError("recorded legacy Hub status mismatch")
    if production.get("hub_transaction_id") != HUB_TRANSACTION_ID:
        raise PrepError("recorded legacy Hub transaction mismatch")
    if production.get("selector") != "OLD":
        raise PrepError("recorded legacy Hub selector role mismatch")
    if production.get("writer") != "INACTIVE_MAINPID_0":
        raise PrepError("recorded writer boundary mismatch")

    evidence_ref = production.get("evidence_path")
    if (
        not isinstance(evidence_ref, str)
        or not evidence_ref.startswith("docs/evidence/")
        or not evidence_ref.endswith(".json")
        or evidence_ref.startswith("/")
        or "\\" in evidence_ref
        or ".." in evidence_ref.split("/")
    ):
        raise PrepError("production boundary evidence path unsafe")
    evidence_path = repository_root / evidence_ref
    if evidence_path.is_symlink() or not evidence_path.is_file():
        raise PrepError("production boundary evidence missing/not regular")

    evidence_raw = evidence_path.read_bytes()
    evidence = json.loads(evidence_raw.decode("utf-8"))
    if evidence.get("observed_at_utc") != production.get("observed_at_utc"):
        raise PrepError("production boundary evidence timestamp mismatch")

    evidence_schema = evidence.get("schema")
    if evidence_schema == "keelaryn.d0-vps-reconcile-evidence.v1":
        if evidence.get("evidence_class") != (
            "production-read-only-legacy-runtime-safety"
        ):
            raise PrepError("recorded D0-02D evidence class mismatch")
        if evidence.get("conclusion") != "PASS":
            raise PrepError("recorded D0-02D evidence is not PASS")
        if evidence.get("production_authorization") is not False:
            raise PrepError("recorded D0-02D evidence improperly authorizes production")
        observation = evidence.get("observation", {})
        if observation.get("production_source_commit") != PRODUCTION_SOURCE:
            raise PrepError("D0-02D observed production source mismatch")
        if observation.get("control_source_commit") != PREDECESSOR_SOURCE_COMMIT:
            raise PrepError("D0-02D observed control source mismatch")
        if observation.get("r0007_snapshot_unit") != "ABSENT":
            raise PrepError("D0-02D observed partial successor residue")
        if observation.get("legacy_hub", {}).get("selector_role") != "OLD":
            raise PrepError("D0-02D observed legacy selector mismatch")
        if observation.get("legacy_hub", {}).get("status") != "PREPARED":
            raise PrepError("D0-02D observed legacy status mismatch")
        if observation.get("legacy_hub", {}).get("mutation_inhibit", {}).get(
            "authority_matches"
        ) is not True:
            raise PrepError("D0-02D mutation inhibit authority mismatch")
        if observation.get("credential", {}).get("sha256") != CREDENTIAL_SHA256:
            raise PrepError("D0-02D credential identity mismatch")
        if observation.get("production_mutations_performed") is not False:
            raise PrepError("D0-02D evidence claims production mutation")
        if observation.get("drive_mutations_performed") is not False:
            raise PrepError("D0-02D evidence claims Drive mutation")
    elif evidence_schema in (
        "keelaryn.operation-control-r0007-stage-boundary-evidence.v1",
        "keelaryn.operation-control-r0008-stage-boundary-evidence.v1",
        "keelaryn.operation-control-r0009-stage-boundary-evidence.v1",
    ):
        canonical_stage_boundary = (
            json.dumps(
                evidence,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if evidence_raw != canonical_stage_boundary:
            raise PrepError("stage boundary evidence is not canonical JSON")
        expected_keys = {
            "schema",
            "observed_at_utc",
            "conclusion",
            "production_source_commit",
            "control_source_commit",
            "legacy_hub_status",
            "legacy_hub_transaction_id",
            "selector_role",
            "writer",
            "mutation_inhibit_authority_matches",
            "credential_sha256",
            "legacy_hub_authority_scope",
            "production_mutations_performed",
            "drive_mutations_performed",
        }
        if set(evidence) != expected_keys:
            raise PrepError("stage boundary evidence keys mismatch")
        expected_stage_boundary = {
            "schema": evidence_schema,
            "observed_at_utc": production.get("observed_at_utc"),
            "conclusion": "PASS",
            "production_source_commit": PRODUCTION_SOURCE,
            "control_source_commit": PREDECESSOR_SOURCE_COMMIT,
            "legacy_hub_status": "PREPARED",
            "legacy_hub_transaction_id": HUB_TRANSACTION_ID,
            "selector_role": "OLD",
            "writer": "INACTIVE_MAINPID_0",
            "mutation_inhibit_authority_matches": True,
            "credential_sha256": CREDENTIAL_SHA256,
            "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
            "production_mutations_performed": False,
            "drive_mutations_performed": False,
        }
        if evidence != expected_stage_boundary:
            raise PrepError("stage boundary evidence identity mismatch")
    else:
        raise PrepError("production boundary evidence schema unsupported")

    if candidate.get("candidate") != CANDIDATE or candidate.get("frozen") is not True:
        raise PrepError("r0009 candidate receipt identity mismatch")
    if candidate.get("frozen_source_commit") != SOURCE_COMMIT:
        raise PrepError("r0009 frozen source mismatch")
    if candidate.get("source_tree") != SOURCE_TREE:
        raise PrepError("r0009 frozen tree mismatch")
    if candidate.get("payload") != {
        "schema": "keelaryn.zero-vps-payload.v1",
        "sha256": PAYLOAD_SHA256,
        "size": PAYLOAD_SIZE,
        "file_count": PAYLOAD_FILE_COUNT,
    }:
        raise PrepError("r0009 frozen payload identity mismatch")
    security = candidate.get("security_contract", {})
    if security.get("remote_allowlist") != [
        "PRODUCTION_SNAPSHOT",
        "RUNTIME_SELFTEST",
    ]:
        raise PrepError("r0009 remote allowlist mismatch")
    if security.get("remote_mutation_handlers") != 0:
        raise PrepError("r0009 exposes remote mutation handler")
    if security.get("old_hub_mutation_authorized") is not False:
        raise PrepError("r0009 authorizes old Hub mutation")
    fix = candidate.get("defect_fix_contract", {})
    if fix != {
        "predecessor_defect_candidate": "operation-control-r0008-20260923-01",
        "predecessor_defect_evidence": "docs/evidence/R0008_SYSTEMD_TEMPLATE_DIAGNOSIS_20260924.json",
        "generic_active_probe_semantics_changed": False,
        "template_probe": "SYSTEMD_ACTIVE_INSTANCE_PATTERN",
        "template_pattern": "keelaryn-production-snapshot@*.service",
        "template_probe_fail_closed": True,
        "bare_template_is_active_forbidden": True,
    }:
        raise PrepError("r0009 defect-fix contract mismatch")
    if candidate.get("control_update_transaction", {}) != {
        "deterministic_id": "24e9df7d9d305450acd11a8dc8f638769ad87444a9b5d16c8befed76a89c52ce",
        "predecessor_source_commit": PREDECESSOR_SOURCE_COMMIT,
        "successor_source_commit": SOURCE_COMMIT,
        "distinct_from_rejected_r0007": True,
        "distinct_from_rejected_r0008": True,
    }:
        raise PrepError("r0009 control-update transaction contract mismatch")

    constrained = {
        item.get("candidate"): item
        for item in state.get("constrained_candidates", [])
        if isinstance(item, dict)
    }
    r0009_state = constrained.get(CANDIDATE, {})
    if r0009_state.get("state") != "FROZEN_TRANSITION_GATE_PASS":
        raise PrepError("r0009 transition qualification is not durably PASS")

    return {
        "observed_at_utc": production.get("observed_at_utc"),
        "evidence_path": evidence_ref,
        "production_source_commit": PRODUCTION_SOURCE,
        "predecessor_source_commit": PREDECESSOR_SOURCE_COMMIT,
        "predecessor_payload_sha256": PREDECESSOR_PAYLOAD_SHA256,
        "legacy_hub": {
            "status": "PREPARED",
            "transaction_id": HUB_TRANSACTION_ID,
            "selector_role": "OLD",
            "authority_scope": "RUNTIME_SAFETY_ONLY",
        },
        "credential_sha256": CREDENTIAL_SHA256,
        "r0009_transition_gate": "PASS",
    }

def _qualify_materialized_release(
    source: Path,
    work: Path,
) -> dict[str, Any]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    releases = work / "materialized" / "releases"
    payload = work / "first.tar.gz"
    materializer = source / "deploy" / "zero-based-vps" / "materialize_payload.py"
    materialized = _json_command(
        [
            sys.executable,
            "-B",
            str(materializer),
            "--payload",
            str(payload),
            "--releases-root",
            str(releases),
            "--expected-source-commit",
            SOURCE_COMMIT,
            "--expected-payload-sha256",
            PAYLOAD_SHA256,
        ],
        timeout=300,
        env=env,
    )
    release = releases / SOURCE_COMMIT

    target = _json_command(
        [
            sys.executable,
            "-B",
            str(release / "deploy" / "zero-based-vps" / "target_host_validate.py"),
            "--release",
            str(release),
            "--expected-source-commit",
            SOURCE_COMMIT,
            "--expected-payload-sha256",
            PAYLOAD_SHA256,
        ],
        timeout=300,
        env=env,
    )

    unit_dir = work / "systemd"
    unit_dir.mkdir(mode=0o755)
    for name in (*PERSISTENT_UNITS, SNAPSHOT_UNIT):
        src = release / "deploy" / "zero-based-vps" / name
        dst = unit_dir / name
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o644)

    d0 = _json_command(
        [
            sys.executable,
            "-B",
            str(
                release
                / "deploy"
                / "zero-based-vps"
                / "operation_control_d0_validate.py"
            ),
            "--release",
            str(release),
            "--expected-source-commit",
            SOURCE_COMMIT,
            "--expected-payload-sha256",
            PAYLOAD_SHA256,
            "--installed-unit-dir",
            str(unit_dir),
        ],
        timeout=300,
        env=env,
    )
    if d0.get("remote_allowlist") != [
        "PRODUCTION_SNAPSHOT",
        "RUNTIME_SELFTEST",
    ]:
        raise PrepError("materialized r0009 D0 allowlist mismatch")
    if d0.get("remote_mutation_handlers") != 0:
        raise PrepError("materialized r0009 exposes remote mutation handler")
    if d0.get("snapshot_unit_policy_verified") is not True:
        raise PrepError("materialized r0009 snapshot policy not verified")
    if d0.get("installed_units_verified") is not True:
        raise PrepError("materialized r0009 unit bytes not verified")

    forbidden = [
        path
        for path in release.rglob("*")
        if path.name == "__pycache__"
        or (path.is_file() and path.suffix in {".pyc", ".pyo"})
    ]
    if forbidden:
        raise PrepError("qualification mutated the materialized frozen release")
    dirty = _run(["git", "-C", str(source), "status", "--porcelain"]).stdout
    if dirty:
        raise PrepError("qualification mutated frozen source checkout")

    return {
        "materialized": materialized,
        "target_host_validation": target,
        "d0_control_validation": d0,
        "release_path_class": "DISPOSABLE_TEMP_ONLY",
    }


def qualify(repository_root: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    recorded = _recorded_boundary(repository_root)
    with tempfile.TemporaryDirectory(prefix="keelaryn-r0009-bootstrap-prep-") as td:
        work = Path(td)
        source = _checkout_frozen(work)
        payload = _rebuild_frozen(source, work)
        release = _qualify_materialized_release(source, work)

    return {
        "schema": "keelaryn.operation-control-r0009-bootstrap-prep.v1",
        "gate_revision": GATE_REVISION,
        "candidate": CANDIDATE,
        "predecessor_candidate": PREDECESSOR_CANDIDATE,
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "payload": payload,
        "recorded_live_boundary": recorded,
        "disposable_release_qualification": release,
        "supported_commands": ["qualify", "reconcile"],
        "stage_implemented": False,
        "upgrade_implemented": False,
        "production_mutation_allowed": False,
        "drive_content_mutation_allowed": False,
        "legacy_hub_authority_scope": "RUNTIME_SAFETY_ONLY",
        "requires_fresh_mutation_boundary_revalidation": True,
        "production_qualified": False,
        "next_action": "DESIGN_SEPARATE_STAGE_TRANSACTION",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keelaryn-operation-control-r0009-bootstrap-prep"
    )
    parser.add_argument(
        "command",
        choices=("reconcile", "qualify"),
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "reconcile":
            value = reconcile()
        elif args.command == "qualify":
            value = qualify(args.repository_root)
        else:
            raise PrepError("unsupported command")
    except (PrepError, OSError) as exc:
        print(
            json.dumps(
                {
                    "schema": "keelaryn.operation-control-r0009-bootstrap-prep-failure.v1",
                    "command": args.command,
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

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


if __name__ == "__main__":
    raise SystemExit(main())
