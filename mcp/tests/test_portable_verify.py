#!/usr/bin/env python3
"""Offline portable verifier integration and corruption tests. Synthetic only."""
import fcntl
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "portable_verify.py"


def run(*args, success=True):
    p = subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, args)],
                       capture_output=True, text=True, timeout=20)
    if success:
        assert p.returncode == 0, (p.stderr, p.stdout)
    else:
        assert p.returncode != 0, (p.stderr, p.stdout)
    return p


def populate(root):
    root.mkdir(mode=0o700)
    owner = root / "testproject"
    owner.mkdir(mode=0o700)
    for name, contents in [
        ("PROJECT.md", "# Portable project\n"),
        ("STATE.md", "# NEXT: restore from offsite\n"),
        ("MASTERY.csv", "id,value\nA001,4\n"),
    ]:
        p = owner / name
        p.write_text(contents, encoding="utf-8")
        p.chmod(0o600)
    journal = owner / ".keelaryn-g1"
    journal.mkdir(mode=0o700)
    lock = journal / ".lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    req = "a" * 32
    receipt = {
        "status": "committed", "request_id": req, "action": "replace",
        "fingerprint": "c" * 64, "expected_sha256": "d" * 64,
        "new_sha256": hashlib.sha256((owner / "STATE.md").read_bytes()).hexdigest(),
    }
    rec = journal / (req + ".json")
    rec.write_text(json.dumps(receipt))
    rec.chmod(0o600)
    hist = journal / "history-000001.json"
    hist.write_text(json.dumps({
        "schema": "keelaryn-g1-history-v1",
        "receipts": {"b" * 32: dict(receipt, request_id="b" * 32)},
    }))
    hist.chmod(0o600)
    return owner, journal


def main():
    with tempfile.TemporaryDirectory(prefix="keelaryn-portable-verify-") as d:
        top = Path(d)
        original = top / "original"
        owner, journal = populate(original)
        marker = json.loads(run("manifest", original).stdout)
        assert marker["schema"] == "keelaryn-vps-project-tree-v1"
        assert marker["version"].startswith("tree-")
        assert len(marker["files"]) == 6
        # Cross-check the identity format used by drive_tree_backup.py,
        # independently from the portable CLI implementation.
        without_version = {"schema": marker["schema"], "files": marker["files"]}
        canonical = (json.dumps(without_version, sort_keys=True,
                                separators=(",", ":")) + "\n").encode()
        assert marker["version"] == "tree-" + hashlib.sha256(canonical).hexdigest()[:24]
        # Compare against the REAL production backup implementation, with
        # its Drive transport modules replaced by inert import-only stubs.
        sender = types.ModuleType("drive_plain_sender")
        sender.BackupError = ValueError
        sender.FOLDER = "application/vnd.google-apps.folder"
        sys.modules["drive_plain_sender"] = sender
        sys.modules["drive_real_backup"] = types.ModuleType("drive_real_backup")
        spec = importlib.util.spec_from_file_location(
            "offline_backup_identity", SCRIPT.parent / "drive_tree_backup.py")
        backup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backup)
        actual = {path: (original / path).read_bytes() for path in marker["files"]}
        assert backup._identity(actual) == marker["version"]
        assert backup._manifest(actual) == without_version
        print("PORTABLE_BACKUP_MARKER_FORMAT_COMPATIBLE_PASS", flush=True)
        marker_path = top / "marker.json"
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        restored = top / "new-host-restored-files"
        shutil.copytree(original, restored)
        verified = json.loads(run("verify", restored, marker_path).stdout)
        assert verified["status"] == "verified_bytes"
        assert verified["version"] == marker["version"]
        print("PORTABLE_DIFFERENT_ROOT_BYTE_VERIFICATION_PASS", flush=True)

        state = restored / "testproject" / "STATE.md"
        state.write_text("# altered\n")
        run("verify", restored, marker_path, success=False)
        state.write_bytes((owner / "STATE.md").read_bytes())
        run("verify", restored, marker_path)
        print("PORTABLE_TAMPERED_BYTES_DENIED_PASS", flush=True)

        changed = dict(marker, version="tree-" + "0" * 24)
        marker_path.write_text(json.dumps(changed))
        run("verify", restored, marker_path, success=False)
        marker_path.write_text(json.dumps(marker))
        print("PORTABLE_MARKER_IDENTITY_DENIED_PASS", flush=True)

        extra = restored / "testproject" / "secret.json"
        extra.write_text("{}")
        run("verify", restored, marker_path, success=False)
        extra.unlink()
        print("PORTABLE_EXTRA_FILE_DENIED_PASS", flush=True)

        wrong = restored / "testproject" / "STATE.md"
        wrong.unlink()
        wrong.symlink_to(owner / "STATE.md")
        run("verify", restored, marker_path, success=False)
        wrong.unlink()
        wrong.write_bytes((owner / "STATE.md").read_bytes())
        wrong.chmod(0o600)
        print("PORTABLE_SYMLINK_DENIED_PASS", flush=True)

        alias = top / "root-alias"
        alias.symlink_to(restored, target_is_directory=True)
        run("verify", alias, marker_path, success=False)
        print("PORTABLE_SYMLINK_ROOT_DENIED_PASS", flush=True)

        wrong.chmod(0o644)
        run("verify", restored, marker_path, success=False)
        wrong.chmod(0o600)
        run("verify", restored, marker_path)
        print("PORTABLE_EXPOSED_FILE_DENIED_PASS", flush=True)

        lock = restored / "testproject" / ".keelaryn-g1" / ".lock"
        with lock.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run("verify", restored, marker_path, success=False)
        run("verify", restored, marker_path)
        print("PORTABLE_ACTIVE_G1_WRITER_DENIED_PASS", flush=True)

        receipt = restored / "testproject" / ".keelaryn-g1" / ("a" * 32 + ".json")
        original_receipt = receipt.read_bytes()
        obj = json.loads(original_receipt)
        obj["status"] = "pending"
        receipt.write_text(json.dumps(obj))
        run("manifest", restored, success=False)
        receipt.write_bytes(original_receipt)
        run("verify", restored, marker_path)
        print("PORTABLE_PENDING_RECEIPT_DENIED_PASS", flush=True)

        archive = restored / "testproject" / ".keelaryn-g1" / "history-000001.json"
        broken_seq = archive.with_name("history-000002.json")
        archive.rename(broken_seq)
        run("manifest", restored, success=False)
        broken_seq.rename(archive)
        run("verify", restored, marker_path)
        print("PORTABLE_NONCONTIGUOUS_HISTORY_DENIED_PASS", flush=True)

        # The marker is independent from the UID allocated on another host.
        if os.geteuid() == 0:
            import pwd
            new_uid, new_gid = pwd.getpwnam("nobody").pw_uid, pwd.getpwnam("nobody").pw_gid
            for entry in [restored / "testproject",
                          *list((restored / "testproject").rglob("*"))]:
                os.chown(entry, new_uid, new_gid, follow_symlinks=False)
            run("verify", restored, marker_path)
            print("PORTABLE_UID_REBIND_BYTE_VERIFICATION_PASS", flush=True)
        # The published tree backup permits up to 400 files. Long valid
        # owner/document names may produce a marker larger than 64 KiB.
        big = top / "large-manifest-source"
        big.mkdir(mode=0o700)
        for owner_index in range(10):
            name = "owner" + str(owner_index) + ("x" * 50)
            owner_dir = big / name
            owner_dir.mkdir(mode=0o700)
            for n in range(40):
                path = owner_dir / ("long" + f"{n:02d}" + ("y" * 64) + ".md")
                path.write_text("# x\\n", encoding="utf-8")
                path.chmod(0o600)
        huge = run("manifest", big).stdout
        assert len(huge.encode()) > 65536
        huge_marker = top / "huge-marker.json"
        huge_marker.write_text(huge, encoding="utf-8")
        result = json.loads(run("verify", big, huge_marker).stdout)
        assert result["files"] == 400
        print("PORTABLE_MAX_FILES_LONG_MARKER_PASS", flush=True)
        print("ALL_PORTABLE_VERIFY_TESTS_PASS", flush=True)


if __name__ == "__main__":
    main()
