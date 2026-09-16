from __future__ import annotations

import gzip
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
DEPLOY = REPO / "deploy" / "zero-based-vps"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = load_module("zero_vps_payload_builder_for_materialize", DEPLOY / "build_payload.py")
materializer = load_module("zero_vps_payload_materializer", DEPLOY / "materialize_payload.py")


def rewrite_archive(raw: bytes, mutate) -> bytes:
    entries: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for info in archive:
            stream = archive.extractfile(info) if info.isreg() else None
            data = b"" if stream is None else stream.read()
            copied = tarfile.TarInfo(info.name)
            copied.size = len(data)
            copied.mode = info.mode
            copied.mtime = info.mtime
            copied.uid = info.uid
            copied.gid = info.gid
            copied.uname = info.uname
            copied.gname = info.gname
            copied.type = info.type
            copied.linkname = info.linkname
            entries.append((copied, data))
    mutate(entries)
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for info, data in entries:
                archive.addfile(info, io.BytesIO(data) if info.isreg() else None)
    return output.getvalue()


class ZeroBasedVpsMaterializeTests(unittest.TestCase):
    SOURCE = "b" * 40

    def build(self, directory: Path) -> Path:
        payload = directory / "payload.tar.gz"
        builder.build_payload(REPO, self.SOURCE, payload)
        return payload

    def test_valid_payload_materializes_exact_new_immutable_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = self.build(root)
            releases = root / "releases"
            result = materializer.materialize_payload(
                payload,
                releases,
                expected_source_commit=self.SOURCE,
            )
            release = releases / self.SOURCE
            self.assertEqual(Path(result["release_directory"]), release)
            self.assertTrue(release.is_dir())
            self.assertEqual((release / "SOURCE_COMMIT").read_text(encoding="ascii"), self.SOURCE + "\n")
            manifest = json.loads((release / "PAYLOAD_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_commit"], self.SOURCE)
            self.assertEqual(result["file_count"], len(manifest["files"]))
            for entry in manifest["files"]:
                target = release / entry["path"]
                with self.subTest(path=entry["path"]):
                    raw = target.read_bytes()
                    self.assertEqual(len(raw), entry["size"])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])

            with self.assertRaises(materializer.PayloadMaterializeError):
                materializer.materialize_payload(payload, releases, expected_source_commit=self.SOURCE)

    def test_wrong_expected_source_commit_blocks_before_release_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = self.build(root)
            releases = root / "releases"
            with self.assertRaises(materializer.PayloadMaterializeError):
                materializer.materialize_payload(payload, releases, expected_source_commit="c" * 40)
            self.assertFalse((releases / self.SOURCE).exists())

    def test_extra_unbound_regular_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = self.build(root)
            raw = payload.read_bytes()

            def add_extra(entries):
                info = tarfile.TarInfo("keelaryn-zero/EXTRA.txt")
                data = b"unbound"
                info.size = len(data)
                info.mode = 0o644
                entries.append((info, data))

            with self.assertRaises(materializer.PayloadMaterializeError):
                materializer.verify_payload(rewrite_archive(raw, add_extra), expected_source_commit=self.SOURCE)

    def test_tar_symlink_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = self.build(root)
            raw = payload.read_bytes()

            def add_link(entries):
                info = tarfile.TarInfo("keelaryn-zero/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                info.size = 0
                entries.append((info, b""))

            with self.assertRaises(materializer.PayloadMaterializeError):
                materializer.verify_payload(rewrite_archive(raw, add_link), expected_source_commit=self.SOURCE)

    def test_manifest_bound_member_content_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = self.build(root)
            raw = payload.read_bytes()

            def tamper(entries):
                for index, (info, data) in enumerate(entries):
                    if info.name not in {materializer.SOURCE_NAME, materializer.MANIFEST_NAME} and info.isreg():
                        changed = data + b"tamper"
                        info.size = len(changed)
                        entries[index] = (info, changed)
                        return
                raise AssertionError("no payload member available to tamper")

            with self.assertRaises(materializer.PayloadMaterializeError):
                materializer.verify_payload(rewrite_archive(raw, tamper), expected_source_commit=self.SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
