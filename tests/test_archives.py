import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from feunpack.archives import inspect_zip, prepare_zip


def dummy_rom():
    data = bytearray(0x200)
    data[0xA0:0xAC] = b"FIREEMBLEM2E"
    data[0xAC:0xB0] = b"BE8E"
    data[0xB0:0xB2] = b"01"
    data[0xB2] = 0x96
    data[0xBD] = (-(sum(data[0xA0:0xBD]) + 0x19)) & 0xFF
    return bytes(data)


class ArchiveTests(unittest.TestCase):
    def test_inspect_and_prepare_only_rom(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            zpath = root / "demo.zip"
            with ZipFile(zpath, "w") as z:
                z.writestr("../../evil.txt", "should-not-extract")
                z.writestr("roms/DEMO.GBA", dummy_rom())
            result = inspect_zip(zpath)
            self.assertEqual(result["game_code"], "BE8E")
            self.assertIsNone(result["reference"])
            output = root / "workspace" / "baserom.gba"
            with self.assertRaisesRegex(ValueError, "SHA-1 desconocido"):
                prepare_zip(zpath, output)
            report = prepare_zip(zpath, output, require_known=False)
            self.assertEqual(output.read_bytes(), dummy_rom())
            self.assertTrue(Path(report["manifest"]).exists())
            self.assertFalse((root / "evil.txt").exists())
            with self.assertRaisesRegex(ValueError, "Ya existe"):
                prepare_zip(zpath, output, require_known=False)

    def test_reject_more_than_one_rom(self):
        with tempfile.TemporaryDirectory() as d:
            zpath = Path(d) / "two.zip"
            with ZipFile(zpath, "w") as z:
                z.writestr("a.gba", dummy_rom())
                z.writestr("b.gba", dummy_rom())
            with self.assertRaisesRegex(ValueError, "exactamente una"):
                inspect_zip(zpath)


if __name__ == "__main__":
    unittest.main()
