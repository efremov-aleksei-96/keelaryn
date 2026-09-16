from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import stat
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


def thaw_tree(root: Path) -> None:
    if not root.exists():
        return
    root.chmod(0o755)
    for path in root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
        elif path.is_file() and not path.is_symlink():
            path.chmod(0o644)


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
            payload_raw = payload.read_bytes()
            payload_sha = hashlib.sha256(payload_raw).hexdigest()
            releases = root / "releases"
            release = releases / self.SOURCE
            try:
                result = materializer.materialize_payload(
                    payload,
                    releases,
                    expected_source_commit=self.SOURCE,
                    expected_payload_sha256=payload_sha,
                )
                self.assertEqual(Path(result["release_directory"]), release)
                self.assertEqual(result["payload_sha256"], payload_sha)
                self.assertEqual(result["payload_size"], len(payload_raw))
                self.assertTrue(release.is_dir())
                self.assertEqual(stat.S_IMODE(release.stat().st_mode), 0o555)
                self.assertEqual((release / "SOURCE_COMMIT").read_text(encoding="ascii"), self.SOURCE + "\n")
                manifest = json.loads((release / "PAYLOAD_MANIFEST.json").read_text(encoding="utf-8"))
                identity = json.loads((release / "PAYLOAD_IDENTITY.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["source_commit"], self.SOURCE)
                self.assertEqual(identity["schema"], materializer.RELEASE_SCHEMA)
                self.assertEqual(identity["source_commit"], self.SOURCE)
                self.assertEqual(identity["payload_sha256"], payload_sha)
                self.assertEqual(identity["payload_size"], len(payload_raw))
                self.assertEqual(identity["file_count"], len(manifest["files"]))
                self.assertEqual(result["file_count"], len(manifest["files"]))
                verified = materializer.verify_release_directory(
                    release,
                    expected_source_commit=self.SOURCE,
                    expected_payload_sha256=payload_sha,
                )
                self.assertEqual(verified, identity)
                for path in release.rglob("*"):
                    with self.subTest(mode_path=str(path.relative_to(release))):
                        if path.is_file():
                            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
                        elif path.is_dir():
                            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o555)
                        else:
                            self.fail("materialized release contains unsupported filesystem object")
                for entry in manifest["files"]:
                    target = release / entry["path"]
                    with self.subTest(path=entry["path"]):
                        raw = target.read_bytes()
                        self.assertEqual(len(raw), entry["size"])
                        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])

                with self.assertRaises(materializer.PayloadMaterializeError):
                    materializer.materialize_payload(
                        payload,
                        releases,
                        expected_source_commit=self.SOURCE,
                        expected_payload_sha256=payload_sha,
                    )
            finally:
                thaw_tree(release)

    def test_wrong_expected_source_or_payload_identity_blocks_before_release_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = self.build(root)
            releases = root / "releases"
            with self.assertRaises(materializer.PayloadMaterializeError):
                materializer.materialize_payload(payload, releases, expected_source_commit="c" * 40)
            self.assertFalse((releases / self.SOURCE).exists())
            with self.assertRaises(materializer.PayloadMaterializeError):
                materializer.materialize_payload(
                    payload,
                    releases,
                    expected_source_commit=self.SOURCE,
                    expected_payload_sha256="0" * 64,
                )
            self.assertFalse((releases / self.SOURCE).exists())

    def test_materialized_release_tamper_mode_extra_and_identity_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = self.build(root)
            payload_sha = hashlib.sha256(payload.read_bytes()).hexdigest()
            releases = root / "releases"
            release = releases / self.SOURCE
            try:
                materializer.materialize_payload(
                    payload,
                    releases,
                    expected_source_commit=self.SOURCE,
                    expected_payload_sha256=payload_sha,
                )
                manifest = json.loads((release / "PAYLOAD_MANIFEST.json").read_text(encoding="utf-8"))
                payload_file = release / manifest["files"][0]["path"]

                payload_file.chmod(0o644)
                with self.assertRaises(materializer.PayloadMaterializeError):
                    materializer.verify_release_directory(release)
                payload_file.chmod(0o444)

                release.chmod(0o755)
                extra = release / "EXTRA.txt"
                extra.write_bytes(b"extra")
                extra.chmod(0o444)
                release.chmod(0o555)
                with self.assertRaises(materializer.PayloadMaterializeError):
                    materializer.verify_release_directory(release)
                release.chmod(0o755)
                extra.chmod(0o644)
                extra.unlink()
                release.chmod(0o555)

                identity_path = release / "PAYLOAD_IDENTITY.json"
                identity = json.loads(identity_path.read_text(encoding="utf-8"))
                identity["payload_sha256"] = "0" * 64
                identity_path.chmod(0o644)
                identity_path.write_text(
                    json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                identity_path.chmod(0o444)
                with self.assertRaises(materializer.PayloadMaterializeError):
                    materializer.verify_release_directory(
                        release,
                        expected_source_commit=self.SOURCE,
                        expected_payload_sha256=payload_sha,
                    )

                # Restore identity, then corrupt one manifest-bound file.
                identity["payload_sha256"] = payload_sha
                identity_path.chmod(0o644)
                identity_path.write_text(
                    json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                identity_path.chmod(0o444)
                original = payload_file.read_bytes()
                payload_file.chmod(0o644)
                payload_file.write_bytes(original + b"tamper")
                payload_file.chmod(0o444)
                with self.assertRaises(materializer.PayloadMaterializeError):
                    materializer.verify_release_directory(release)
            finally:
                thaw_tree(release)

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
