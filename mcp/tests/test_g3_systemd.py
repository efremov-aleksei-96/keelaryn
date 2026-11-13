#!/usr/bin/env python3
"""G3 synthetic probe worker; systemd-run sets DynamicUser and StateDirectory.

Run as a transient, non-network service with a dedicated synthetic
StateDirectory. No tunnel, credentials, live registry, user project or Drive.
Usage: python -B test_g3_systemd.py init|resume|verify
"""
import hashlib
import os
import pathlib
import stat
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from owner_fs import mutate

OWNER = "G3Synthetic"
FIRST = "# G3 synthetic project\nNEXT: G3-S1\n"
SECOND = "# G3 synthetic project\nNEXT: G3-S2\n"
SHA = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("init", "resume", "verify"):
        raise SystemExit("One explicit synthetic phase required")
    if os.geteuid() == 0:
        raise RuntimeError("G3 worker must run as non-root DynamicUser")
    if os.environ.get("KEELARYN_MCP_MODE") != "local":
        raise RuntimeError("Only isolated synthetic local mode allowed")
    if os.environ.get("KEELARYN_MCP_OWNER_FS_TEST") != "1":
        raise RuntimeError("G1 synthetic opt-in required")
    state_value = os.environ.get("STATE_DIRECTORY", "")
    if not state_value or ":" in state_value:
        raise RuntimeError("One systemd StateDirectory required")
    state = pathlib.Path(state_value)
    # systemd DynamicUser StateDirectory is exposed through a managed symlink;
    # pin its resolved, verified private target rather than relaxing G1 O_NOFOLLOW.
    resolved_state = state.resolve(strict=True)
    if not resolved_state.is_dir() or resolved_state.stat().st_uid != os.geteuid():
        raise RuntimeError("StateDirectory resolved owner mismatch")
    root = resolved_state / "owner"
    if not root.exists():
        if sys.argv[1] != "init":
            raise RuntimeError("Lost owner root between phases")
        root.mkdir(mode=0o700)
    scope = {
        "backend": "owner-fs", "owner": OWNER, "root": str(root),
        "allow": ["PROJECT.md"], "access": "read-write",
        "canonical": False, "snapshot_only": False,
    }
    if (os.stat(root).st_uid != os.geteuid()
            or os.stat(root).st_mode & 0o077):
        raise RuntimeError("StateDirectory owner root not private")
    phase = sys.argv[1]
    first = {"project": OWNER, "request_id": "1"*32,
             "action": "create", "path": "PROJECT.md",
             "content": FIRST, "expected_sha256": None}
    second = {"project": OWNER, "request_id": "2"*32,
              "action": "replace", "path": "PROJECT.md",
              "content": SECOND, "expected_sha256": SHA(FIRST)}
    if phase == "init":
        created = mutate(first, scope)
        assert created["status"] == "committed"
        assert (root / "PROJECT.md").read_text() == FIRST
        assert (root / "PROJECT.md").stat().st_mode & 0o777 == 0o600
        # Force an abrupt process exit after the durable intent record.
        os.environ["KEELARYN_G1_TEST_CRASH_AFTER"] = "intent"
        mutate(second, scope)
        raise AssertionError("Intent crash should exit the worker")
    if phase == "resume":
        assert (root / "PROJECT.md").read_text() == FIRST
        recovered = mutate(second, scope)
        assert recovered["status"] == "committed"
        assert recovered["verified_readback"]
        assert (root / "PROJECT.md").read_text() == SECOND
        # A different command must not reuse a committed id.
        wrong = dict(second, content="# changed payload")
        try:
            mutate(wrong, scope)
        except ValueError:
            pass
        else:
            raise AssertionError("Reused request ID was not rejected")
        # Attempt to write outside owner scope is denied.
        traversal = dict(second, request_id="3"*32, path="../PROJECT.md")
        try:
            mutate(traversal, scope)
        except ValueError:
            pass
        else:
            raise AssertionError("Owner traversal was not denied")
        # The systemd sandbox must not allow arbitrary /etc writes.
        unexpected = pathlib.Path("/etc/keelaryn-g3-should-not-exist")
        try:
            unexpected.write_text("UNSAFE")
        except OSError:
            pass
        else:
            unexpected.unlink(missing_ok=True)
            raise AssertionError("ProtectSystem did not prevent /etc write")
        print("G3_SYSTEMD_DYNAMIC_USER_RECOVERED_AND_DENIAL_PASS", flush=True)
        return
    existing = mutate(second, scope)
    assert existing["status"] == "already_committed"
    assert existing["current_matches"] is True
    assert (root / "PROJECT.md").read_text() == SECOND
    assert (root / ".keelaryn-g1/.lock").is_file()
    print("G3_SYSTEMD_RESTART_REPLAY_AND_STATE_READBACK_PASS", flush=True)


if __name__ == "__main__":
    main()
