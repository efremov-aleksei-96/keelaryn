from __future__ import annotations

import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_poller import main as poller_main
from keelaryn_core.drive_process_lock import DriveProcessLock, DriveProcessLockError


@unittest.skipUnless(os.name == "posix", "VPS process lock is a POSIX deployment primitive")
class DriveProcessLockTests(unittest.TestCase):
    def runtime(self, base: str) -> dict[str, str]:
        path = Path(base) / "runtime"
        path.mkdir(mode=0o700)
        return {"KEELARYN_RUNTIME_DIR": str(path)}

    def test_same_hub_has_exactly_one_local_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env = self.runtime(temp)
            first = DriveProcessLock("hub-secret-id", env=env)
            second = DriveProcessLock("hub-secret-id", env=env)
            with first:
                with self.assertRaises(DriveProcessLockError) as caught:
                    second.acquire()
                self.assertIn("already owns", str(caught.exception))
            with second:
                self.assertTrue(second.path.exists())

    def test_different_hubs_can_hold_distinct_locks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env = self.runtime(temp)
            left = DriveProcessLock("hub-left", env=env)
            right = DriveProcessLock("hub-right", env=env)
            with left, right:
                self.assertNotEqual(left.path, right.path)

    def test_lock_path_hashes_hub_identity_instead_of_exposing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env = self.runtime(temp)
            lock = DriveProcessLock("sensitive-drive-file-id", env=env)
            self.assertNotIn("sensitive-drive-file-id", str(lock.path))
            with lock:
                mode = stat.S_IMODE(lock.path.stat().st_mode)
                self.assertEqual(mode & 0o077, 0)
                self.assertEqual(lock.path.read_text(encoding="ascii"), f"pid={os.getpid()}\n")

    def test_runtime_directory_must_be_private_real_and_owned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            broad = Path(temp) / "broad"
            broad.mkdir(mode=0o755)
            with self.assertRaises(DriveProcessLockError):
                DriveProcessLock("hub", env={"KEELARYN_RUNTIME_DIR": str(broad)}).acquire()

            real = Path(temp) / "real"
            real.mkdir(mode=0o700)
            link = Path(temp) / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(DriveProcessLockError):
                DriveProcessLock("hub", env={"KEELARYN_RUNTIME_DIR": str(link)}).acquire()

    def test_relative_runtime_directory_is_rejected(self) -> None:
        with self.assertRaises(DriveProcessLockError):
            DriveProcessLock("hub", env={"KEELARYN_RUNTIME_DIR": "relative/runtime"})

    def test_poller_contention_blocks_before_auth_or_drive_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env = self.runtime(temp)
            holder = DriveProcessLock("hub-no-network", env=env)
            process_env = {
                **env,
                "KEELARYN_GOOGLE_ACCESS_TOKEN": "token-that-must-never-be-used",
            }
            stderr = io.StringIO()
            with holder, patch.dict(os.environ, process_env, clear=True), redirect_stderr(stderr):
                code = poller_main(["--hub-root-id", "hub-no-network", "once"])
            self.assertEqual(code, 2)
            rendered = stderr.getvalue()
            self.assertIn('"phase":"BLOCKED"', rendered)
            self.assertIn("already owns", rendered)
            self.assertNotIn("token-that-must-never-be-used", rendered)
            self.assertNotIn("hub-no-network", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
