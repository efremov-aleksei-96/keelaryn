from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BUILDER_PATH = REPO / "deploy" / "zero-based-vps" / "build_payload.py"
spec = importlib.util.spec_from_file_location("zero_vps_payload_builder", BUILDER_PATH)
assert spec is not None and spec.loader is not None
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)


class ZeroBasedVpsPayloadTests(unittest.TestCase):
    def test_same_source_commit_builds_byte_identical_payload_and_exact_manifest(self) -> None:
        source_commit = "a" * 40
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first.tar.gz"
            second = Path(temp) / "second.tar.gz"
            one = builder.build_payload(REPO, source_commit, first)
            two = builder.build_payload(REPO, source_commit, second)

            first_raw = first.read_bytes()
            second_raw = second.read_bytes()
            self.assertEqual(first_raw, second_raw)
            self.assertEqual(one["payload_sha256"], two["payload_sha256"])
            self.assertEqual(one["payload_sha256"], hashlib.sha256(first_raw).hexdigest())
            self.assertGreater(one["file_count"], 10)

            with tarfile.open(fileobj=io.BytesIO(first_raw), mode="r:gz") as archive:
                names = archive.getnames()
                self.assertEqual(len(names), len(set(names)))
                self.assertIn("keelaryn-zero/SOURCE_COMMIT", names)
                self.assertIn("keelaryn-zero/PAYLOAD_MANIFEST.json", names)
                self.assertNotIn(
                    "keelaryn-zero/tests/ci/operation_relay_cross_user.py",
                    names,
                )
                source = archive.extractfile("keelaryn-zero/SOURCE_COMMIT")
                manifest_file = archive.extractfile("keelaryn-zero/PAYLOAD_MANIFEST.json")
                assert source is not None and manifest_file is not None
                self.assertEqual(source.read(), (source_commit + "\n").encode("ascii"))
                manifest = json.loads(manifest_file.read().decode("utf-8"))

                self.assertEqual(manifest["schema"], builder.SCHEMA)
                self.assertEqual(manifest["source_commit"], source_commit)
                self.assertEqual(len(manifest["files"]), one["file_count"])
                self.assertFalse(
                    any(
                        entry["path"].startswith("tests/ci/")
                        for entry in manifest["files"]
                    )
                )
                for entry in manifest["files"]:
                    with self.subTest(path=entry["path"]):
                        self.assertFalse(entry["path"].startswith("manager/"))
                        self.assertFalse(entry["path"].startswith("hub/"))
                        member = archive.extractfile("keelaryn-zero/" + entry["path"])
                        self.assertIsNotNone(member)
                        raw = member.read()
                        self.assertEqual(len(raw), entry["size"])
                        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])

    def test_invalid_source_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "payload.tar.gz"
            for value in ("", "A" * 40, "g" * 40, "a" * 39, "a" * 41):
                with self.subTest(value=value):
                    with self.assertRaises(builder.PayloadBuildError):
                        builder.build_payload(REPO, value, output)

    def test_symlink_file_or_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            for name in builder.INCLUDED_ROOTS:
                (root / name).mkdir(parents=True, exist_ok=True)
                (root / name / "payload.txt").write_text(name, encoding="utf-8")

            target = root / "outside.txt"
            target.write_text("outside", encoding="utf-8")
            file_link = root / builder.INCLUDED_ROOTS[0] / "linked.txt"
            try:
                file_link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(builder.PayloadBuildError):
                builder.collect_files(root)

            file_link.unlink()
            real_dir = root / "real-dir"
            real_dir.mkdir()
            (real_dir / "x.txt").write_text("x", encoding="utf-8")
            dir_link = root / builder.INCLUDED_ROOTS[0] / "linked-dir"
            dir_link.symlink_to(real_dir, target_is_directory=True)
            with self.assertRaises(builder.PayloadBuildError):
                builder.collect_files(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
