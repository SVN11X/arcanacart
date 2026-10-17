import struct
import unittest

from arcanacart.core.memory import Reader, align, find_references, interval_coverage, resolve, rom_offset


class MemoryTests(unittest.TestCase):
    def test_rom_waitstate_windows(self):
        for address in [0x08000100, 0x0A000100, 0x0C000100]:
            with self.subTest(address=address):
                self.assertEqual(rom_offset(address, 0x1000), 0x100)
        self.assertEqual(rom_offset(0x09000000, 0x2000000), 0x1000000)

    def test_no_short_rom_mirroring(self):
        with self.assertRaises(ValueError):
            rom_offset(0x08001000, 0x1000)

    def test_thumb_bit_explicit(self):
        self.assertEqual(rom_offset(0x08000101, 0x1000), 0x101)
        resolved = resolve(0x08000101, 0x1000, kind="function")
        self.assertTrue(resolved.thumb)
        self.assertEqual(resolved.file_offset, 0x100)

    def test_ram_mirrors(self):
        for address, canonical in [
            (0x02040010, 0x02000010),
            (0x03FF8010, 0x03000010),
            (0x05000402, 0x05000002),
            (0x07001002, 0x07000002),
        ]:
            with self.subTest(address=address):
                self.assertEqual(resolve(address, 0x1000).canonical, canonical)

    def test_vram_special_mirror(self):
        self.assertEqual(resolve(0x06018000, 0x1000).canonical, 0x06010000)
        self.assertEqual(resolve(0x06028000, 0x1000).canonical, 0x06008000)

    def test_io_and_invalid(self):
        self.assertEqual(resolve(0x04000130, 0x1000).region, "IO")
        for address in [-1, 0x04000400, 0x0F000000, 0x100000000]:
            with self.subTest(address=address), self.assertRaises(ValueError):
                resolve(address, 0x1000)

    def test_alignment(self):
        self.assertEqual(align(5, 4), 8)
        self.assertEqual(align(8, 4), 8)
        for value, boundary in [(-1, 4), (1, 3), (1, 0)]:
            with self.assertRaises(ValueError):
                align(value, boundary)

    def test_reader_little_endian_and_bounds(self):
        reader = Reader(b"\x01\x02\x03\x04")
        self.assertEqual(reader.unpack("<I", 0), (0x04030201,))
        for offset, size in [(-1, 1), (1, 4), (0, -1)]:
            with self.assertRaises(ValueError):
                reader.read(offset, size)
        with self.assertRaises(ValueError):
            reader.unpack(">I", 0)

    def test_selected_references_not_arbitrary_values(self):
        data = bytearray(512)
        struct.pack_into("<III", data, 0, 0x08000100, 0x08000110, 0x0A000100)
        refs = find_references(bytes(data), [0x100])
        self.assertEqual(len(refs["references"]), 2)
        self.assertTrue(all(r["validation"] == "inferred" for r in refs["references"]))
        limited = find_references(bytes(data), [0x100], max_results=1)
        self.assertTrue(limited["truncated"])

    def test_interval_union_and_denominator(self):
        result = interval_coverage([(0, 10), (5, 10), (30, 5)], 100)
        self.assertEqual(result["classified_bytes"], 20)
        self.assertEqual(result["overlap_bytes"], 5)
        self.assertEqual(result["unknown_bytes"], 80)
        self.assertEqual(result["unknown_ranges"], [[15, 30], [35, 100]])
        with self.assertRaises(ValueError):
            interval_coverage([(99, 2)], 100)

    def test_three_way_overlap_counts_unique_bytes(self):
        coverage = interval_coverage([(0, 10), (0, 10), (0, 10)], 20)
        self.assertEqual(coverage["overlap_bytes"], 10)
        self.assertEqual(coverage["duplicated_classification_bytes"], 20)
        self.assertEqual(coverage["overlap_ranges"], [[0, 10]])
