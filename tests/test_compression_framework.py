import random
import unittest

from arcanacart.compression import ScanLimits, rle, scan_resources
from arcanacart.core.io import digest
from examples.generate_synthetic import fixture
from feunpack.lz10 import LZError, decompress, scan


class CompressionTests(unittest.TestCase):
    def test_unaligned_lz10_legacy_default(self):
        data = b"!" + b"\x10\x04\0\0\x00ABCD"
        self.assertEqual(scan(data)[0]["rom_offset"], "0x00000001")

    def test_rle_runs_and_literals(self):
        data = b"\x30\x08\0\0\x82A\x02BCD"
        self.assertEqual(rle(data), (b"AAAAABCD", 10))

    def test_rle_truncation_and_size_limit(self):
        for blob in [b"\x30\x06\0\0\x83", b"\x30\x03\0\0\x02A", b"\x30\x02\0\0\x83A"]:
            with self.subTest(blob=blob), self.assertRaises(LZError):
                rle(blob)
        with self.assertRaises(LZError):
            rle(b"\x30\x06\0\0\x83A", max_size=5)

    def test_resource_metadata_dedup_and_references(self):
        resources, blobs, stats = scan_resources(fixture()[0])
        self.assertEqual([r["offset"] for r in resources], [0x701, 0x721, 0x741])
        self.assertEqual(stats["decoded_blocks"], 3)
        self.assertEqual(stats["unique_outputs"], 2)
        self.assertEqual(len(blobs), 2)
        first = resources[0]
        self.assertEqual(first["sha256"], digest(b"DEMO"))
        self.assertEqual(first["references"][0]["location"], 0x800)
        self.assertEqual(first["validation"], "structural")
        self.assertEqual(first["confidence"], "heuristic")
        self.assertIsNone(first["possible_type"])

    def test_result_limit_reports_truncation(self):
        resources, _, stats = scan_resources(fixture()[0], ScanLimits(max_results=1))
        self.assertEqual(len(resources), 1)
        self.assertTrue(stats["truncated"])

    def test_total_decode_budget(self):
        resources, _, stats = scan_resources(fixture()[0], ScanLimits(max_decode_bytes=4))
        self.assertEqual(len(resources), 1)
        self.assertTrue(stats["truncated"])
        self.assertLessEqual(stats["decode_budget_used"], 4)

    def test_method_selection_and_unsupported(self):
        resources, _, _ = scan_resources(fixture()[0], methods=("rle",))
        self.assertEqual(len(resources), 1)
        with self.assertRaises(ValueError):
            scan_resources(fixture()[0], methods=("huffman",))

    def test_invalid_limits(self):
        for options in [{"step": 0}, {"max_results": -1}, {"max_decode_bytes": 0}, {"max_candidates": 0}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                ScanLimits(**options)

    def test_lz_truncated_literals_flags_and_refs(self):
        for value in [b"\x10\x04\0\0", b"\x10\x04\0\0\0ABC", b"\x10\x06\0\0\x40A\x20"]:
            with self.subTest(value=value), self.assertRaises(LZError):
                decompress(value)

    def test_bounded_corrupt_corpus(self):
        rand = random.Random(42)
        for _ in range(100):
            data = rand.randbytes(128)
            resources, blobs, stats = scan_resources(
                data, ScanLimits(max_block_bytes=512, max_decode_bytes=1024, max_candidates=8)
            )
            self.assertLessEqual(stats["decode_budget_used"], 1024)
            self.assertLessEqual(sum(len(blob) for blob in blobs.values()), 1024)

    def test_lz_large_declaration_rejected_before_allocation(self):
        import tracemalloc

        tracemalloc.start()
        try:
            with self.assertRaises(LZError):
                decompress(b"\x10\xff\xff\xff", max_size=1024)
            _, peak = tracemalloc.get_traced_memory()
            self.assertLess(peak, 1024 * 1024)
        finally:
            tracemalloc.stop()

    def test_header_false_positive_excluded(self):
        data = fixture()[0]
        resources, _, stats = scan_resources(data)
        self.assertEqual(stats["excluded_header_bytes"], 0xC0)
        self.assertTrue(all(r["offset"] >= 0xC0 for r in resources))
