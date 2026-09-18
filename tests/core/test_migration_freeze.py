from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.migration_freeze import (  # noqa: E402
    MIGRATION_FREEZE_STATUS,
    MigrationFreezePostCommitBlocked,
    freeze_migration_candidate,
    verify_migration_candidate_freeze,
    verify_migration_candidate_freeze_identity,
)
from keelaryn_core.migration_pack import (  # noqa: E402
    MigrationPackBlocked,
    build_migration_pack,
    capture_migration_source,
    verify_migration_pack,
    verify_migration_source,
)
from keelaryn_core.protocol import canonical_json_bytes  # noqa: E402


class MigrationCandidateFreezeTests(unittest.TestCase):
    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    def _repo(self, root: Path, *, ignore_private_pack: bool = False) -> tuple[Path, str, str]:
        repo = root / "repo"
        repo.mkdir()
        self._git(repo, "init")
        self._git(repo, "config", "user.name", "Keelaryn Test")
        self._git(repo, "config", "user.email", "keelaryn-test@example.invalid")
        (repo / "tracked.txt").write_bytes(b"exact source\n")
        if ignore_private_pack:
            (repo / ".gitignore").write_bytes(b"private-pack/\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-m", "exact source")
        return repo, self._git(repo, "rev-parse", "HEAD"), self._git(repo, "rev-parse", "HEAD^{tree}")

    def _pack(self, root: Path, *, output_dir: Path | None = None):
        source = root / "source"
        source.mkdir()
        (source / "canonical.md").write_bytes(b"canonical\r\n")
        (source / "project.md").write_bytes(b"project work\r\n")
        (source / "archive.txt").write_bytes(b"archive bytes\r\n")
        (source / "router.md").write_bytes(b"legacy router\r\n")

        selection = root / "selection.json"
        selection.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-selection.v1",
                    "candidate_id": "migration-freeze-001",
                    "sources": ["router.md", "archive.txt", "canonical.md", "project.md"],
                }
            )
        )
        source_manifest = root / "source.json"
        capture_migration_source(source, selection, source_manifest)

        prepared = root / "prepared"
        prepared.mkdir()
        (prepared / "project-state.md").write_bytes(b"# Project\r\nstate=initial\r\n")
        (prepared / "INDEX.md").write_bytes(b"# Migrated router\r\n")

        mapping = root / "mapping.json"
        mapping.write_bytes(
            canonical_json_bytes(
                {
                    "schema": "keelaryn.migration-mapping.v1",
                    "candidate_id": "migration-freeze-001",
                    "source_manifest_sha256": verify_migration_source(source_manifest).digest,
                    "source_actions": [
                        {"source": "canonical.md", "classification": "CANONICAL_IMPORT"},
                        {
                            "source": "project.md",
                            "classification": "PROJECT_WORK_IMPORT",
                            "destination": "work/projects/project-1/migration-import/project.md",
                        },
                        {
                            "source": "archive.txt",
                            "classification": "ARCHIVE_ONLY",
                            "destination": "archive/migration/migration-freeze-001/archive.txt",
                        },
                        {"source": "router.md", "classification": "ROUTER_SOURCE"},
                    ],
                    "project_initial_states": [
                        {"project_id": "project-1", "prepared_path": "project-state.md"}
                    ],
                    "canonical_outputs": [
                        {
                            "target": "identity/profile.md",
                            "semantic_sources": ["canonical.md"],
                            "payload": {"kind": "SOURCE", "source": "canonical.md"},
                        }
                    ],
                    "root_index": {
                        "semantic_sources": ["router.md"],
                        "prepared_path": "INDEX.md",
                    },
                }
            )
        )
        return build_migration_pack(
            source,
            source_manifest,
            mapping,
            output_dir or (root / "pack"),
            prepared_root=prepared,
        )

    @staticmethod
    def _bytes_tree(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_freeze_binds_exact_clean_source_and_private_pack_without_mutating_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            before = self._bytes_tree(pack.root)
            receipt = root / "candidate-freeze.json"

            value = freeze_migration_candidate(pack.root, repo, commit, tree, receipt)
            self.assertEqual(value["status"], MIGRATION_FREEZE_STATUS)
            self.assertEqual(value["source_commit"], commit)
            self.assertEqual(value["source_tree"], tree)
            self.assertEqual(value["candidate_id"], pack.candidate_id)
            self.assertEqual(value["pack_sha256"], pack.pack_sha256)
            self.assertTrue(value["has_root_index"])
            self.assertEqual(value["canonical_file_count"], 1)
            self.assertEqual(value["project_state_count"], 1)
            self.assertEqual(value["preserved_file_count"], 2)
            self.assertEqual(before, self._bytes_tree(pack.root))
            self.assertEqual(verify_migration_candidate_freeze(pack.root, receipt, repo), value)

            encoded = receipt.read_text(encoding="utf-8")
            for private_name in (
                "canonical.md",
                "project.md",
                "archive.txt",
                "router.md",
                "identity/profile.md",
                "work/projects/project-1",
                "archive/migration/migration-freeze-001",
            ):
                self.assertNotIn(private_name, encoded)

            first_raw = receipt.read_bytes()
            self.assertEqual(freeze_migration_candidate(pack.root, repo, commit, tree, receipt), value)
            self.assertEqual(receipt.read_bytes(), first_raw)

    def test_identity_verifier_uses_qualified_source_without_git_worktree_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            receipt = root / "candidate-freeze.json"
            value = freeze_migration_candidate(pack.root, repo, commit, tree, receipt)

            (repo / "runtime-dirty.txt").write_bytes(b"runtime checkout no longer authoritative\n")
            self.assertEqual(
                verify_migration_candidate_freeze_identity(
                    pack.root,
                    receipt,
                    commit,
                    tree,
                ),
                value,
            )
            with self.assertRaisesRegex(MigrationPackBlocked, "source tree mismatch"):
                verify_migration_candidate_freeze_identity(
                    pack.root,
                    receipt,
                    commit,
                    "0" * 40,
                )

    def test_dirty_or_wrong_git_identity_blocks_before_receipt_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            receipt = root / "candidate-freeze.json"

            (repo / "untracked.txt").write_bytes(b"dirty\n")
            with self.assertRaisesRegex(MigrationPackBlocked, "clean Git worktree"):
                freeze_migration_candidate(pack.root, repo, commit, tree, receipt)
            self.assertFalse(receipt.exists())
            (repo / "untracked.txt").unlink()

            with self.assertRaisesRegex(MigrationPackBlocked, "source tree mismatch"):
                freeze_migration_candidate(pack.root, repo, commit, "0" * 40, receipt)
            self.assertFalse(receipt.exists())

    def test_private_pack_is_forbidden_inside_git_even_when_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root, ignore_private_pack=True)
            pack = self._pack(root, output_dir=repo / "private-pack")
            self.assertEqual(self._git(repo, "status", "--porcelain=v1", "--untracked-files=all"), "")
            receipt = root / "candidate-freeze.json"
            with self.assertRaisesRegex(MigrationPackBlocked, "private migration pack.*outside"):
                freeze_migration_candidate(pack.root, repo, commit, tree, receipt)
            self.assertFalse(receipt.exists())

    def test_receipt_cannot_contaminate_repo_or_immutable_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            with self.assertRaisesRegex(MigrationPackBlocked, "outside the Git worktree"):
                freeze_migration_candidate(pack.root, repo, commit, tree, repo / "freeze.json")
            with self.assertRaisesRegex(MigrationPackBlocked, "outside the immutable migration pack"):
                freeze_migration_candidate(
                    pack.root,
                    repo,
                    commit,
                    tree,
                    pack.root / "freeze.json",
                )

    def test_crash_after_durable_receipt_recovers_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            receipt = root / "candidate-freeze.json"

            def crash(point: str) -> None:
                if point == "freeze.after_receipt_publish":
                    raise RuntimeError("simulated process loss")

            with self.assertRaisesRegex(RuntimeError, "simulated process loss"):
                freeze_migration_candidate(
                    pack.root,
                    repo,
                    commit,
                    tree,
                    receipt,
                    fault_hook=crash,
                )
            durable = receipt.read_bytes()
            value = freeze_migration_candidate(pack.root, repo, commit, tree, receipt)
            self.assertEqual(receipt.read_bytes(), durable)
            self.assertEqual(verify_migration_candidate_freeze(pack.root, receipt, repo), value)

    def test_receipt_or_pack_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            receipt = root / "candidate-freeze.json"
            freeze_migration_candidate(pack.root, repo, commit, tree, receipt)

            value = json.loads(receipt.read_text(encoding="utf-8"))
            value["status"] = "QUALIFIED"
            receipt.write_bytes(canonical_json_bytes(value))
            with self.assertRaises(MigrationPackBlocked):
                verify_migration_candidate_freeze(pack.root, receipt, repo)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            receipt = root / "candidate-freeze.json"
            freeze_migration_candidate(pack.root, repo, commit, tree, receipt)
            payload = pack.root / "canonical" / "canonical-00001.bin"
            payload.write_bytes(b"tampered\n")
            with self.assertRaises(MigrationPackBlocked):
                verify_migration_candidate_freeze(pack.root, receipt, repo)

    def test_post_commit_failure_is_reported_as_durable_receipt_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, commit, tree = self._repo(root)
            pack = self._pack(root)
            receipt = root / "candidate-freeze.json"
            verified = verify_migration_pack(pack.root)

            with patch(
                "keelaryn_core.migration_freeze.verify_migration_pack",
                side_effect=[verified, verified, MigrationPackBlocked("post-check failure")],
            ):
                with self.assertRaises(MigrationFreezePostCommitBlocked):
                    freeze_migration_candidate(pack.root, repo, commit, tree, receipt)
            self.assertTrue(receipt.is_file())
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["status"], MIGRATION_FREEZE_STATUS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
