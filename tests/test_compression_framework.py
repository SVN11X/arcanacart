import random
import struct
import unittest

from arcanacart.compression import ScanLimits, measure_rle, rle, scan_resources
from arcanacart.core.io import digest
from examples.generate_synthetic import fixture
from feunpack.lz10 import DecodeBudget, DecodeBudgetExceeded, LZError, decompress, measure, scan


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

    def test_large_false_headers_do_not_hide_a_late_valid_block(self):
        data = bytearray(b"\xff" * (1024 * 1024 + 9))
        for offset in range(0, 2400, 8):
            # Claims 2 MiB but immediately references an empty output buffer.
            data[offset : offset + 7] = b"\x10\0\0\x20\x80\0\0"
        data[1024 * 1024 :] = b"\x10\x04\0\0\0DEMO"
        resources, blobs, stats = scan_resources(
            bytes(data), ScanLimits(max_decode_bytes=4), methods=("lz10",)
        )
        self.assertEqual([r["offset"] for r in resources], [1024 * 1024])
        self.assertEqual(list(blobs.values()), [b"DEMO"])
        self.assertFalse(stats["truncated"])
        self.assertEqual(stats["search_progress_percent"], 100.0)
        self.assertEqual(stats["decode_budget_used"], 4)
        self.assertGreater(stats["attempted_declared_bytes"], 64 * 1024 * 1024)
        self.assertEqual(scan(bytes(data), max_total_bytes=4)[0]["_bytes"], b"DEMO")

    def test_rejected_lz_output_still_consumes_real_budget(self):
        budget = DecodeBudget(16)
        with self.assertRaises(LZError):
            decompress(b"\x10\x08\0\0\0AB", budget=budget)
        self.assertEqual(budget.used, 2)

    def test_rejected_rle_output_still_consumes_real_budget(self):
        budget = DecodeBudget(16)
        with self.assertRaises(LZError):
            rle(b"\x30\x08\0\0\x01AB\x05C", budget=budget)
        self.assertEqual(budget.used, 2)

    def test_budget_stops_during_valid_overlap_without_allocating_declared_size(self):
        budget = DecodeBudget(5)
        with self.assertRaises(DecodeBudgetExceeded):
            decompress(b"\x10\x06\0\0\x40A\x20\0", budget=budget)
        self.assertEqual(budget.used, 1)

    def test_rle_budget_bounds_run_allocation(self):
        budget = DecodeBudget(7)
        with self.assertRaises(DecodeBudgetExceeded):
            rle(b"\x30\x08\0\0\x85A", budget=budget)
        self.assertEqual(budget.used, 0)

    def test_structural_validation_rejects_before_allocating_output(self):
        data = b"\x30\x08\0\0\x01AB\x05C"
        _, blobs, stats = scan_resources(data, ScanLimits(max_decode_bytes=1), methods=("rle",))
        self.assertFalse(stats["truncated"])
        self.assertEqual(blobs, {})
        self.assertEqual(stats["decode_budget_used"], 0)
        self.assertGreater(stats["validation_budget_used"], 0)

    def test_validation_work_is_bounded_independently_from_output(self):
        block = b"\x30\0\x02\0" + b"\0X" * 512
        _, _, stats = scan_resources(
            block * 4, ScanLimits(max_block_bytes=512, max_candidates=4), methods=("rle",)
        )
        self.assertTrue(stats["truncated"])
        self.assertEqual(stats["stop_reason"], "validation-budget")
        self.assertLessEqual(stats["validation_budget_used"], stats["validation_budget_limit"])

    def test_measurers_match_decoders_on_valid_and_corrupt_data(self):
        rand = random.Random(103)
        corpus = [rand.randbytes(128) for _ in range(100)]
        corpus += [b"\x10\x04\0\0\0DEMO", b"\x10\x06\0\0\x40A\x20\0", b"\x30\x08\0\0\x82A\x02BCD"]
        for data in corpus:
            for measurer, decoder in [(measure, decompress), (measure_rle, rle)]:
                try:
                    blob, consumed = decoder(data)
                except LZError:
                    with self.assertRaises(LZError):
                        measurer(data)
                else:
                    self.assertEqual(measurer(data), (len(blob), consumed))

    def test_empty_and_sampled_search_progress(self):
        for data in [b"", b"abc", b"\xff" * 20]:
            _, _, stats = scan_resources(data, ScanLimits(step=4))
            self.assertEqual(stats["search_progress_percent"], 100.0)
            self.assertEqual(stats["header_positions_checked"], stats["header_positions_total"])

    def test_referenced_late_resource_is_considered_before_expensive_noise(self):
        raw, _ = fixture()
        data = bytearray(raw + b"\xff" * (0x10000 - len(raw)))
        # A large RLE declaration before the useful resource is expensive to validate.
        data[0x200:0x204] = b"\x30\0\0\x20"
        late = 0xF001
        data[late : late + 9] = b"\x10\x04\0\0\0LATE"
        struct.pack_into("<I", data, 0x180, 0x0A000000 + late)
        resources, _, stats = scan_resources(bytes(data), ScanLimits(max_results=1))
        self.assertEqual(resources[0]["offset"], 0x701)
        self.assertEqual(resources[0]["discovery"], "referenced-header")
        # Without a one-result cap both referenced, unaligned resources survive.
        resources, _, stats = scan_resources(bytes(data))
        self.assertIn(late, [r["offset"] for r in resources])
        self.assertEqual(stats["referenced_header_targets"], 2)
        self.assertEqual(stats["referenced_header_targets_checked"], 2)

    def test_reference_prioritization_preserves_linear_fallback(self):
        resources, _, stats = scan_resources(fixture()[0])
        self.assertEqual(
            [r["discovery"] for r in resources], ["referenced-header", "linear-header", "linear-header"]
        )
        self.assertEqual(stats["search_progress_percent"], 100.0)
