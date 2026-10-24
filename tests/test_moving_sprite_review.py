"""Moving table and AP review on generated ROMs; no game assets are fixtures."""

import contextlib
import csv
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from arcanacart import moving_sprite_review as mr
from arcanacart.core.io import digest, json_bytes
from arcanacart.icon_variants import _sealed, pack_variants


def literal_lz(raw):
    return (
        b"\x10"
        + len(raw).to_bytes(3, "little")
        + b"".join(b"\0" + raw[i : i + 8] for i in range(0, len(raw), 8))
    )


def synthetic_motion(*, rotations=False):
    frames = []
    for index in range(2):
        prefix = struct.pack("<4H", 0x8001, 0, 256, 256) if rotations and index == 0 else b""
        frames.append(prefix + struct.pack("<5H", 1, 0xE0, 0x81F0, 0, index * 4))
    # Two frame offsets, five animation offsets, two objects, then a shared script.
    anim_table = 8
    first_frame = anim_table + 10
    script = first_frame + sum(map(len, frames))
    return (
        struct.pack("<4H", 4, anim_table, first_frame - 4, first_frame + len(frames[0]) - 4)
        + struct.pack("<5H", *([script - anim_table] * 5))
        + b"".join(frames)
        + struct.pack("<6H", 3, 0, 4, 1, 0, 65535)
    )


class MovingSpriteReview(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="arcana movimiento con espacios ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.datos = self.root / "datos"
        self.out = self.root / "revision"
        self.plan_path = self.root / "identidades.json"
        self.raw = bytes(range(256)) * 30
        self.sheet = literal_lz(self.raw)
        self.motion = synthetic_motion()
        data = bytearray(0x10000)
        data[0xAC:0xB0] = b"BE8E"
        data[0xB2] = 0x96
        struct.pack_into("<I", data, 0x180, 0x08000400)
        struct.pack_into("<I", data, 0x1C4, 0x08000400)
        struct.pack_into("<2I", data, 0x400, 0x08002000, 0x08005000)
        struct.pack_into("<2I", data, 0x408, 0x08002000, 0x08005000)
        data[0x2000 : 0x2000 + len(self.sheet)] = self.sheet
        data[0x5000 : 0x5000 + len(self.motion)] = self.motion
        self.base = bytes(data)
        self.base_path = self.datos / "resultados/fe8/fe8-usa-base.gba"
        self.base_path.parent.mkdir(parents=True)
        self.base_path.write_bytes(self.base)
        self.profile = {"rom_sha256": digest(self.base), "pointer_locations": [0x180, 0x1C4]}
        patched = patch.object(mr, "PROFILES", {"fe8": self.profile})
        patched.start()
        self.addCleanup(patched.stop)
        self.row = {
            "variant_id": "fe8-001",
            "game": "fe8",
            "variant": "001-sintetica",
            "rom_relative_path": "fe8/001-sintetica/mod.gba",
            "air_relative_path": "fe8/001-sintetica/analisis/air.json",
        }
        self.plan = {
            "format": "arcanacart-item-icon-variant-plan-1",
            "reviewed_ranges": {},
            "variants": [self.row],
        }
        data[0x300] = 1
        self.save_variant(data)

    def save_variant(self, data, *, records=None):
        self.rom = self.datos / "resultados" / self.row["rom_relative_path"]
        self.air = self.datos / "resultados" / self.row["air_relative_path"]
        self.rom.parent.mkdir(parents=True, exist_ok=True)
        self.air.parent.mkdir(parents=True, exist_ok=True)
        self.rom.write_bytes(data)
        self.row["rom_sha256"] = digest(data)
        if records is None:
            records = [
                {
                    "offset": 0x2000,
                    "compression": "lz10",
                    "compressed_bytes": len(self.sheet),
                    "decompressed_bytes": len(self.raw),
                    "sha256": digest(self.raw),
                    "references": [0x400, 0x408],
                }
            ]
        self.air.write_bytes(
            json_bytes(
                {
                    "rom": {"sha256": digest(data), "size_bytes": len(data)},
                    "scan": {"truncated": False, "methods": ["lz10"]},
                    "resources": records,
                }
            )
        )
        self.row["air_sha256"] = digest(self.air.read_bytes())
        self.plan_path.write_bytes(json_bytes(self.plan))

    def review(self, **kwargs):
        return mr.review_movement(self.datos, self.out, self.plan_path, **kwargs)

    def results(self):
        return json.loads((self.out / "revision.json").read_bytes())["results"]

    def test_complete_evidence_preserves_one_based_ids_and_both_assets(self):
        summary = self.review()
        self.assertEqual(summary["counts"], {"pending": 2, "error": 0, "approved": 0})
        self.assertEqual(summary["observed_entries"], 510)
        self.assertEqual(summary["unique_stored_sheets"], 1)
        self.assertEqual(summary["unique_native_ap_snapshots"], 1)
        row = self.results()[1]
        self.assertEqual(len(row["tables"]), 1)
        entry = row["tables"][0]["entries"][0]
        self.assertEqual((entry["table_index"], entry["class_id"], entry["class_id_hex"]), (0, 1, "0x01"))
        self.assertEqual((self.out / entry["stored_file"]).read_bytes(), self.sheet)
        self.assertEqual((self.out / entry["motion_file"]).read_bytes(), self.motion)
        self.assertEqual(entry["motion_frame_count"], 2)
        self.assertEqual(entry["motion_animation_count"], 5)
        self.assertTrue(entry["air_references_this_entry"])
        self.assertEqual(entry["air_decoded_sha256"], digest(self.raw))
        self.assertFalse(row["extraction_enabled"])
        self.assertFalse(row["class_mapping_verified"])
        self.assertFalse(row["range_approved"])
        self.assertEqual(row["base_comparison"]["table_views"][0]["identical_stored_sheets"], 2)

    def test_no_scanner_decompressor_png_or_input_mutation(self):
        before = {p: p.read_bytes() for p in (self.rom, self.air, self.base_path, self.plan_path)}
        with (
            patch("feunpack.lz10.decompress", side_effect=AssertionError("no decode")),
            patch("arcanacart.graphics.png", side_effect=AssertionError("no PNG")),
            patch("arcanacart.pipeline.scan_resources", side_effect=AssertionError("no scan")),
            patch("arcanacart.compression.scan_resources", side_effect=AssertionError("no scan")),
        ):
            summary = self.review()
        for key in (
            "rescanned",
            "sheets_decompressed",
            "animations_executed",
            "pngs_exported",
            "inputs_modified",
            "ready_for_extraction",
        ):
            self.assertFalse(summary[key])
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)
        self.assertFalse(list(self.out.rglob("*.png")))

    def test_default_collects_tail_after_empty_and_invalid_records(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into("<2I", data, 0x400 + 7 * 8, 0x02001000, 0x03005000)
        struct.pack_into("<2I", data, 0x400 + 254 * 8, 0x08002000, 0x08005000)
        self.save_variant(data)
        self.review()
        table = self.results()[1]["tables"][0]
        self.assertEqual(table["boundary_hint"], {"table_index": 2, "reason": "zero-record-hint"})
        last = table["entries"][-1]
        self.assertEqual(
            (last["class_id"], last["status"], last["post_boundary_hint"]), (255, "candidate", True)
        )
        self.assertEqual(table["table_window_bytes"], 255 * 8)

    def test_distinct_referenced_tables_are_all_retained_and_correlated(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into("<I", data, 0x1C4, 0x08007000)
        struct.pack_into("<2I", data, 0x7000, 0x08002000, 0x08005000)
        self.save_variant(data)
        self.review()
        row = self.results()[1]
        self.assertEqual({t["table_offset"] for t in row["tables"]}, {0x400, 0x7000})
        self.assertIn("conflicting-access-pointers-all-table-views-retained", row["issues"])
        comparisons = row["base_comparison"]["table_views"]
        self.assertEqual([c["comparable_sheets"] for c in comparisons], [2, 1])
        self.assertEqual(comparisons[-1]["base_table_offset"], 0x400)

    def test_unusable_first_reference_does_not_hide_the_other_known_reference(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into("<I", data, 0x180, 0x02000400)
        self.save_variant(data)
        self.review()
        row = self.results()[1]
        self.assertEqual(row["tables"][0]["access_locations"], [0x1C4])
        self.assertIn("unusable-access-pointer", row["issues"])

    def test_no_usable_reference_reports_pending_without_whole_rom_search(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into("<I", data, 0x180, 0)
        struct.pack_into("<I", data, 0x1C4, 0)
        self.save_variant(data)
        self.review()
        row = self.results()[1]
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["tables"], [])
        self.assertIn("no-usable-known-table-reference-no-search", row["issues"])

    def test_wrong_rom_exact_hash_fails_and_does_not_publish_candidate(self):
        data = bytearray(self.rom.read_bytes())
        data[0x300] ^= 1
        self.rom.write_bytes(data)
        self.assertEqual(self.review()["counts"]["error"], 1)
        self.assertFalse((self.out / "candidatas/fe8-001.json").exists())

    def test_air_crlf_is_rejected_but_plan_crlf_keeps_canonical_identity(self):
        first = self.review()["plan_canonical_sha256"]
        self.out = self.root / "revision-plan-crlf"
        self.plan_path.write_bytes(self.plan_path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.review()["plan_canonical_sha256"], first)
        self.out = self.root / "revision-air-crlf"
        self.air.write_bytes(self.air.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.review()["counts"]["error"], 1)
        self.assertIn("AIR", self.results()[1]["error"])

    def test_air_rom_identity_and_declared_length_must_match(self):
        air = json.loads(self.air.read_bytes())
        air["rom"]["sha256"] = "f" * 64
        self.air.write_bytes(json_bytes(air))
        self.row["air_sha256"] = digest(self.air.read_bytes())
        self.plan_path.write_bytes(json_bytes(self.plan))
        self.assertEqual(self.review()["counts"]["error"], 1)

    def test_missing_air_candidate_and_mismatched_air_metadata_stay_unapproved(self):
        self.save_variant(self.rom.read_bytes(), records=[])
        self.review()
        self.assertEqual(
            self.results()[1]["tables"][0]["entries"][0]["air_correlation"], "no-existing-candidate"
        )
        self.out = self.root / "revision-mismatch"
        self.save_variant(self.rom.read_bytes())
        air = json.loads(self.air.read_bytes())
        air["resources"][0]["decompressed_bytes"] += 32
        self.air.write_bytes(json_bytes(air))
        self.row["air_sha256"] = digest(self.air.read_bytes())
        self.plan_path.write_bytes(json_bytes(self.plan))
        self.review()
        entry = self.results()[1]["tables"][0]["entries"][0]
        self.assertEqual(entry["status"], "needs-review")
        self.assertIn("air-metadata-mismatch", entry["issues"])

    def test_unknown_compression_preserves_small_header_and_skips_ap_parse(self):
        data = bytearray(self.rom.read_bytes())
        data[0x2000] = 0x30
        self.save_variant(data, records=[])
        self.review()
        entry = self.results()[1]["tables"][0]["entries"][0]
        self.assertEqual(entry["sheet_status"], "unsupported")
        self.assertEqual(len((self.out / entry["header_file"]).read_bytes()), 64)
        self.assertNotIn("motion_file", entry)

    def test_unknown_ap_keeps_incomplete_window_without_approval(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into("<2H", data, 0x5000, 0, 0)
        self.save_variant(data)
        self.review()
        entry = self.results()[1]["tables"][0]["entries"][0]
        self.assertEqual(entry["motion_status"], "unparsed-window")
        self.assertFalse(entry["motion_complete"])
        self.assertEqual((self.out / entry["motion_file"]).stat().st_size, mr.AP_FALLBACK_BYTES)
        self.assertNotIn("motion_layout_file", entry)

    def test_two_byte_aligned_ap_and_short_table_window_are_retained(self):
        data = bytearray(self.rom.read_bytes())
        data[0x5002 : 0x5002 + len(self.motion)] = self.motion
        struct.pack_into("<2I", data, 0xFFF8, 0x08002000, 0x08005002)
        for position in self.profile["pointer_locations"]:
            struct.pack_into("<I", data, position, 0x0800FFF8)
        self.save_variant(data)
        self.review()
        row = self.results()[1]
        table = row["tables"][0]
        self.assertEqual(table["slots_observed"], 1)
        self.assertFalse(table["observation_complete"])
        self.assertIn("table-window-truncated-by-rom-bound", row["issues"])
        entry = table["entries"][0]
        self.assertEqual(entry["motion_offset"], 0x5002)
        self.assertEqual((self.out / entry["motion_file"]).read_bytes(), self.motion)

    def test_packet_budget_failure_does_not_publish_a_partial_output(self):
        with patch.object(mr, "MAX_PACKET_BYTES", 128), self.assertRaises(ValueError):
            self.review()
        self.assertFalse(self.out.exists())

    def test_invalid_lz_backreference_and_oversized_sheet_remain_headers(self):
        for stored in (b"\x10\x80\x01\0\x80\0\0", b"\x10\x01\x80\0"):
            with self.subTest(header=stored):
                data = bytearray(self.base)
                data[0x2000 : 0x2000 + len(stored)] = stored
                meta, payloads = mr._sheet(data, 0x2000, None, False)
                self.assertEqual(meta["sheet_status"], "unsupported")
                self.assertEqual(len(payloads[meta["header_file"]]), 64)

    def test_ap_native_offsets_scripts_oam_and_rotations_are_preserved(self):
        for rotate in (False, True):
            raw = synthetic_motion(rotations=rotate)
            layout = mr._motion_layout(raw)
            self.assertEqual(layout["captured_bytes"], len(raw))
            self.assertEqual(layout["frames"][0]["rotations"], [[0, 256, 256]] if rotate else [])
            self.assertEqual(layout["frames"][1]["tiles"], [4])
            self.assertEqual(layout["animations"][0]["commands"], [[3, 0], [4, 1], [0, 65535]])
            self.assertFalse(layout["executed"])
            self.assertFalse(layout["allocation_size_confirmed"])

    def test_ap_rejects_truncation_backward_offsets_and_invalid_commands(self):
        raw = synthetic_motion()
        for size in (0, 3, 8, len(raw) - 1):
            with self.subTest(size=size), self.assertRaises(ValueError):
                mr._motion_layout(raw[:size])
        for position, value in [(0, 3), (2, 2), (4, 1), (8, 1), (len(raw) - 2, 2), (len(raw) - 6, 2)]:
            changed = bytearray(raw)
            struct.pack_into("<H", changed, position, value)
            with self.subTest(position=position), self.assertRaises(ValueError):
                mr._motion_layout(changed)

    def test_ap_iteration_object_and_window_budgets_are_enforced(self):
        raw = bytearray(synthetic_motion())
        struct.pack_into("<H", raw, 18, 129)
        with self.assertRaisesRegex(ValueError, "128 objetos"):
            mr._motion_layout(raw)
        raw = bytearray(synthetic_motion(rotations=True))
        struct.pack_into("<H", raw, 18, 0x8021)
        with self.assertRaisesRegex(ValueError, "32 transformaciones"):
            mr._motion_layout(raw)
        raw = synthetic_motion()[:-4] + struct.pack("<2H", 1, 0) * 4100
        with self.assertRaisesRegex(ValueError, "4096 comandos"):
            mr._motion_layout(raw)

    def test_mirror_alignment_and_rom_bounds_are_specific_to_each_pointer_kind(self):
        self.assertEqual(mr._offset(0x0A005002, 4, len(self.base), alignment=2), 0x5002)
        for pointer in (0x08005002, 0x0E005000, 0x02000000, 0x0800FFFC):
            with self.assertRaises(ValueError):
                mr._offset(pointer, 8, len(self.base))

    def test_csv_manifest_zip_and_repack_preserve_all_assets(self):
        self.review()
        files = _sealed(self.out, state_name=mr.STATE)
        rows = list(csv.DictReader(io.StringIO(files["entradas.csv"].decode("utf-8-sig"))))
        self.assertEqual(len(rows), 510)
        packed = self.root / "revision.zip"
        summary = pack_variants(self.out, packed, state_name=mr.STATE)
        self.assertTrue(summary["crc_verified"])
        with ZipFile(packed) as z:
            self.assertEqual(set(z.namelist()), set(files))
            for name, raw in files.items():
                self.assertEqual(z.read(name), raw)
        (self.out / "entradas.csv").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            pack_variants(self.out, self.root / "changed.zip", state_name=mr.STATE)

    def test_existing_output_input_ancestors_and_symlinks_are_preserved(self):
        self.out.mkdir()
        marker = self.out / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(ValueError):
            self.review()
        self.assertEqual(marker.read_text(), "keep")
        self.out = self.root
        with self.assertRaises(ValueError):
            self.review()
        link = self.root / "linked"
        try:
            link.symlink_to(self.datos, target_is_directory=True)
        except (OSError, NotImplementedError):
            return
        with self.assertRaises(ValueError):
            mr.review_movement(link, self.root / "symlink-output", self.plan_path)

    def test_bases_only_and_reduced_budget_do_not_open_variant_inputs(self):
        self.rom.unlink()
        self.air.unlink()
        summary = self.review(scope="bases", slots=3)
        self.assertEqual((summary["roms"], summary["variants"], summary["observed_entries"]), (1, 0, 3))
        for slots in (0, 256, True):
            with self.assertRaises(ValueError):
                self.review(scope="bases", slots=slots)

    def test_full_roster_covers_two_bases_and_43_variants(self):
        base7 = bytearray(self.base)
        base7[0xAC:0xB0] = b"BE7E"
        path = self.datos / "resultados/fe7/fe7-usa-base.gba"
        path.parent.mkdir(parents=True)
        path.write_bytes(base7)
        profiles = {
            game: {**self.profile, "rom_sha256": digest(raw)}
            for game, raw in (("fe7", base7), ("fe8", self.base))
        }
        self.plan["variants"] = []
        for game, count, raw in (("fe7", 8, base7), ("fe8", 35, self.base)):
            for index in range(1, count + 1):
                self.row = {
                    "variant_id": f"{game}-{index:03}",
                    "game": game,
                    "variant": f"{index:03}-sintetica",
                    "rom_relative_path": f"{game}/{index:03}-sintetica/mod.gba",
                    "air_relative_path": f"{game}/{index:03}-sintetica/analisis/air.json",
                }
                self.plan["variants"].append(self.row)
                data = bytearray(raw)
                data[0x300] = index
                self.save_variant(data)
        with patch.object(mr, "PROFILES", profiles):
            summary = self.review(slots=3)
        self.assertEqual((summary["roms"], summary["bases"], summary["variants"]), (45, 2, 43))
        self.assertEqual(summary["counts"], {"pending": 45, "error": 0, "approved": 0})
        self.assertEqual(
            {r["variant_id"] for r in self.results()},
            {r["variant_id"] for r in self.plan["variants"]} | {"fe7-base", "fe8-base"},
        )

    def test_cli_success_error_exit_codes_and_no_clobber(self):
        args = [
            "review",
            "--datos",
            str(self.datos),
            "--out",
            str(self.out),
            "--identities",
            str(self.plan_path),
            "--zip",
            str(self.root / "review.zip"),
        ]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(mr.main(args), 0)
        self.assertEqual(json.loads(stdout.getvalue())["counts"]["error"], 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mr.main(args), 2)
        data = bytearray(self.rom.read_bytes())
        data[0x300] ^= 1
        self.rom.write_bytes(data)
        args = [
            "review",
            "--datos",
            str(self.datos),
            "--out",
            str(self.root / "errors"),
            "--identities",
            str(self.plan_path),
        ]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(mr.main(args), 2)
        self.assertEqual(json.loads(stdout.getvalue())["counts"]["error"], 1)


if __name__ == "__main__":
    unittest.main()
