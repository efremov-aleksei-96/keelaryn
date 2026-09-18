from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "zero-based-vps"
sys.path.insert(0, str(DEPLOY))

import build_payload as builder  # noqa: E402
import hub_cutover as cutovermod  # noqa: E402
import materialize_payload as materializer  # noqa: E402
import release_switch as releasemod  # noqa: E402


class ZeroBasedVpsOperationExclusivityTests(unittest.TestCase):
    OLD_COMMIT = "1" * 40
    NEW_COMMIT = "2" * 40
    OLD_HUB = "OLDHubRoot_0123456789abcdef"
    NEW_HUB = "NEWHubRoot_0123456789abcdef"

    def layout(self, root: Path):
        install = root / "opt" / "keelaryn"
        releases = install / "releases"
        releases.mkdir(parents=True)
        for commit in (self.OLD_COMMIT, self.NEW_COMMIT):
            payload = root / f"{commit}.tar.gz"
            builder.build_payload(REPO, commit, payload)
            materializer.materialize_payload(payload, releases, expected_source_commit=commit)
        os.symlink(f"releases/{self.OLD_COMMIT}", install / "current")

        etc = root / "etc" / "keelaryn"
        etc.mkdir(parents=True, mode=0o755)
        selector = etc / "hub.env"
        selector.write_bytes(cutovermod._selector_bytes(self.OLD_HUB))
        os.chmod(selector, 0o600)

        # Both administrative transactions deliberately share one durable state
        # root, ACTIVE_TRANSACTION.json and LOCK. This is the global deployment
        # serialization boundary.
        state = root / "var" / "lib" / "keelaryn" / "deployment"
        gate = state.parent / "mutation-gate"
        gate.mkdir(parents=True, mode=0o2750)
        os.chmod(gate, 0o2750)
        lock = gate / "LOCK"
        lock.write_bytes(b"")
        os.chmod(lock, 0o640)
        return install, selector, state

    def hub_switch(self, selector: Path, state: Path):
        return cutovermod.HubSelectorCutover(
            selector,
            state,
            self.OLD_COMMIT,
            mutation_gate_root=state.parent / "mutation-gate",
            executing_tool=DEPLOY / "hub_cutover.py",
        )

    def test_release_and_hub_cutover_transactions_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            install, selector, state = self.layout(Path(temp))

            hub = self.hub_switch(selector, state)
            hub.prepare(self.NEW_HUB)
            with self.assertRaises(releasemod.ReleaseSwitchError):
                releasemod.ReleaseSwitch(install, state).prepare(self.NEW_COMMIT)
            self.assertEqual(hub.rollback(), {"status": "IDLE"})

            release = releasemod.ReleaseSwitch(install, state)
            release.prepare(self.NEW_COMMIT)
            with self.assertRaises(cutovermod.HubCutoverError):
                self.hub_switch(selector, state).prepare(self.NEW_HUB)
            self.assertEqual(release.rollback(), {"status": "IDLE"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
