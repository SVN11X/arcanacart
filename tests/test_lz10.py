import unittest

from feunpack.lz10 import LZError, decompress, scan


class LZTests(unittest.TestCase):
    def test_literals(self):
        data = b"\x10\x04\x00\x00\x00ABCD"
        self.assertEqual(decompress(data), (b"ABCD", 9))

    def test_overlapping_copy(self):
        # A + ref length 5 / distance 1 => AAAAAA
        data = b"\x10\x06\x00\x00\x40A\x20\x00"
        self.assertEqual(decompress(data)[0], b"A" * 6)

    def test_bad_reference(self):
        with self.assertRaises(LZError):
            decompress(b"\x10\x06\x00\x00\x80\x20\x00")

    def test_scan(self):
        rom = bytes(4) + b"\x10\x04\x00\x00\x00ABCD" + bytes(8)
        found = scan(rom, max_results=5)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["rom_offset"], "0x00000004")
