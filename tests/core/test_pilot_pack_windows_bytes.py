from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from keelaryn_core.pilot_pack import build_pilot_pack, verify_pilot_pack  # noqa: E402


class PilotPackWindowsExactBytesTests(unittest.TestCase):
    def test_crlf_manifest_and_payload_are_read_as_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()

            payload_raw = b"line-one\r\nline-two\r\n"
            (source / "windows.txt").write_bytes(payload_raw)

            # Intentionally CRLF-formatted JSON. On Windows, os.open/os.read
            # without O_BINARY can translate these bytes and make fstat size
            # disagree with the bytes actually read.
            manifest_raw = (
                b'{\r\n'
                b'  "schema": "keelaryn.pilot-source.v1",\r\n'
                b'  "pilot_id": "pilot-windows-crlf",\r\n'
                b'  "entries": [\r\n'
                b'    {"source": "windows.txt", "target": "windows.txt"}\r\n'
                b'  ]\r\n'
                b'}\r\n'
            )
            manifest = root / "PILOT_SOURCE.json"
            manifest.write_bytes(manifest_raw)

            pack = build_pilot_pack(source, manifest, root / "pack")
            self.assertEqual(len(pack.entries), 1)
            self.assertEqual(pack.payload_bytes(pack.entries[0]), payload_raw)

            verified = verify_pilot_pack(pack.root)
            self.assertEqual(verified.payload_bytes(verified.entries[0]), payload_raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
