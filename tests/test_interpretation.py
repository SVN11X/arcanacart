"""Independent rendering vectors and the reuse/review workflow; no game content."""

import base64
import copy
import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from arcanacart import graphics
from arcanacart.cli import main
from arcanacart.core.io import digest
from arcanacart.gallery import SCRIPT
from arcanacart.interpret import check_recipes, inspect_blob, interpret
from arcanacart.reporting import resource_metrics


class GraphicsVectors(unittest.TestCase):
    def test_rgb555_channels_and_unused_high_bit(self):
        self.assertEqual(
            graphics.palette(struct.pack("<4H", 31, 31 << 5, 31 << 10, 0xFFFF)),
            [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)],
        )

    def test_4bpp_low_nibble_is_left_pixel(self):
        w, h, rgba = graphics.tiles(b"\x21" + bytes(31), width_tiles=1)
        self.assertEqual((w, h), (8, 8))
        self.assertEqual(rgba[:8], bytes([17, 17, 17, 255, 34, 34, 34, 255]))

    def test_8bpp_and_transparency(self):
        _, _, rgba = graphics.tiles(bytes([0, 255]) + bytes(62), bpp=8, transparent_zero=True)
        self.assertEqual(rgba[:8], bytes([0, 0, 0, 0, 255, 255, 255, 255]))

    def test_partial_sheet_has_transparent_padding(self):
        w, h, rgba = graphics.tiles(b"\x11" * 96, width_tiles=2)
        self.assertEqual((w, h), (16, 16))
        self.assertEqual(rgba[(8 * w + 8) * 4 : (8 * w + 8) * 4 + 4], bytes(4))

    def test_palette_bank_and_horizontal_vertical_flip(self):
        raw_tile = b"\x21" + bytes(27) + b"\x43\0\0\0"
        colors = [(i, 0, 0) for i in range(32)]
        _, _, rgba = graphics.bg_map(
            struct.pack("<H", 0x1C00), raw_tile, width_tiles=1, height_tiles=1, colors=colors
        )
        # Both flips: the first source pixel lands at bottom-right, in palette bank 1.
        self.assertEqual(rgba[(7 * 8 + 7) * 4], 17)
        self.assertEqual(rgba[(7 * 8 + 6) * 4], 18)

    def test_screenblock_layout_at_second_horizontal_block(self):
        words = [0] * 2048
        words[1024] = 1
        raw_tiles = b"\x11" * 32 + b"\x22" * 32
        w, _, rgba = graphics.bg_map(
            struct.pack("<2048H", *words), raw_tiles, width_tiles=64, height_tiles=32, layout="screenblocks"
        )
        self.assertEqual(w, 512)
        self.assertEqual(rgba[256 * 4], 34)
        self.assertEqual(rgba[0], 17)

    def test_png_crc_pixels_and_dimensions(self):
        png = graphics.png(2, 1, bytes([255, 0, 0, 255, 0, 255, 0, 255]))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        at, image_data = 8, b""
        while at < len(png):
            size = struct.unpack_from(">I", png, at)[0]
            kind, data = png[at + 4 : at + 8], png[at + 8 : at + 8 + size]
            self.assertEqual(zlib.crc32(kind + data), struct.unpack_from(">I", png, at + 8 + size)[0])
            if kind == b"IHDR":
                self.assertEqual(struct.unpack_from(">II", data), (2, 1))
            if kind == b"IDAT":
                image_data += data
            at += 12 + size
        self.assertEqual(zlib.decompress(image_data), bytes([0, 255, 0, 0, 255, 0, 255, 0, 255]))

    def test_invalid_renderings_fail_before_large_allocations(self):
        for fn in [
            lambda: graphics.tiles(b"x" * 33),
            lambda: graphics.tiles(bytes(32), width_tiles=0),
            lambda: graphics.png(2000, 2000, b""),
            lambda: graphics.palette(bytes(3)),
            lambda: graphics.tiles(b"\xff" * 32, colors=[(0, 0, 0)]),
            lambda: graphics.bg_map(b"\x01\0", bytes(32), width_tiles=1, height_tiles=1),
        ]:
            with self.assertRaises(ValueError):
                fn()


class InterpretationWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "analysis"
        self.blobs = self.folder / "resources"
        self.blobs.mkdir(parents=True)
        self.tile = bytes([0x21, 0x43, 0x65, 0x87]) * 16
        self.pal = struct.pack("<16H", *[i | ((15 - i) << 5) for i in range(16)])
        self.hashes = [digest(self.tile), digest(self.pal)]
        self.manifest = {
            "rom": {"sha256": "a" * 64, "size_bytes": 4096},
            "resources": [
                {
                    "sha256": digest(raw),
                    "offset": 256 + i * 128,
                    "compressed_bytes": 16,
                    "decompressed_bytes": len(raw),
                    "compression": "lz10",
                    "references": [],
                }
                for i, raw in enumerate([self.tile, self.pal, self.tile])
            ],
            "scan": {
                "truncated": False,
                "methods": ["lz10"],
                "decoded_blocks": 3,
                "unique_outputs": 2,
                "step": 1,
                "search_progress_percent": 100.0,
            },
        }
        self.source = self.folder / "air.json"
        self.source.write_text(json.dumps(self.manifest))
        for raw in (self.tile, self.pal):
            (self.blobs / (digest(raw) + ".bin")).write_bytes(raw)

    def run_interpret(self, name="review", **kwargs):
        out = self.root / name
        result = interpret(self.source, out, **kwargs)
        return result, out

    def test_existing_042_shape_is_reused_and_duplicates_keep_offsets(self):
        original = self.source.read_bytes()
        result, out = self.run_interpret()
        self.assertEqual(result["candidates"], 3)
        self.assertEqual(result["unique_blobs"], 2)
        self.assertEqual(result["generated_previews"], 2)
        self.assertEqual(result["identified_by_user_review"], 0)
        self.assertEqual(result["pending_interpretation"], 2)
        self.assertFalse(result["rescanned"])
        catalog = json.loads((out / "catalog.json").read_text())
        self.assertEqual(catalog["resources"][0]["offsets"], [256, 512])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(json.loads((out / "interpret-state.json").read_text())["status"], "completed")

    def test_recipes_real_palette_and_manual_acceptance(self):
        _, first = self.run_interpret("first")
        config = json.loads((first / "recipes.json").read_text())
        recipe = config["resources"][self.hashes[0]]
        recipe.update(
            mode="tiles",
            palette_sha256=self.hashes[1],
            width_tiles=1,
            review="accepted",
            evidence=["Known synthetic pixel vector"],
        )
        path = self.root / "recipes.json"
        path.write_text(json.dumps(config))
        result, out = self.run_interpret("second", recipes=path)
        self.assertEqual(result["identified_by_user_review"], 1)
        row = json.loads((out / "catalog.json").read_text())["resources"][0]
        self.assertEqual(row["colors"], "rgb555")
        self.assertEqual(row["width"], 8)

    def test_missing_and_changed_blobs_are_partial(self):
        (self.blobs / (self.hashes[0] + ".bin")).write_bytes(b"X" * len(self.tile))
        (self.blobs / (self.hashes[1] + ".bin")).unlink()
        result, _ = self.run_interpret()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["verified_blobs"], 0)

    def test_external_palette_is_hash_bound_and_copied(self):
        external_raw = struct.pack("<16H", *range(16))
        external_path = self.root / "raw-palette.bin"
        external_path.write_bytes(external_raw)
        config = {
            "format": "arcanacart-recipes-1",
            "rom_sha256": "a" * 64,
            "resources": {self.hashes[0]: {"mode": "tiles", "palette_sha256": digest(external_raw)}},
        }
        path = self.root / "external-recipes.json"
        path.write_text(json.dumps(config), encoding="utf-8-sig")
        result, out = self.run_interpret(recipes=path, palettes=[external_path])
        self.assertEqual(result["external_palettes"][0]["sha256"], digest(external_raw))
        self.assertEqual((out / "palettes" / (digest(external_raw) + ".bin")).read_bytes(), external_raw)
        with self.assertRaises(ValueError):
            self.run_interpret("missing-external", recipes=path)

    def test_limits_do_not_drop_catalog_entries(self):
        result, out = self.run_interpret(max_previews=0)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["skipped_previews"], 2)
        self.assertEqual(len(json.loads((out / "catalog.json").read_text())["resources"]), 2)
        limited, _ = self.run_interpret("byte-limited", byte_budget=1)
        self.assertEqual(limited["status"], "partial")
        self.assertEqual(limited["bytes_read"], 0)

    def test_dry_run_and_input_paths_protected(self):
        result, out = self.run_interpret(dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertFalse(out.exists())
        with self.assertRaises(ValueError):
            interpret(self.source, self.blobs / "unsafe")

    def test_existing_output_is_preserved(self):
        _, out = self.run_interpret()
        with self.assertRaises(ValueError):
            interpret(self.source, out)

    def test_base_hash_comparison_keeps_uncertainty(self):
        base = copy.deepcopy(self.manifest)
        base["resources"] = [base["resources"][1]]
        base["scan"].update(decoded_blocks=1, unique_outputs=1)
        path = self.root / "base.json"
        path.write_text(json.dumps(base))
        result, out = self.run_interpret(base=path)
        rows = json.loads((out / "catalog.json").read_text())["resources"]
        self.assertFalse(rows[0]["base_match"])
        self.assertTrue(rows[1]["base_match"])
        self.assertEqual(result["identified_by_user_review"], 0)

    def test_gallery_csp_script_and_untrusted_text(self):
        config = {
            "format": "arcanacart-recipes-1",
            "rom_sha256": "a" * 64,
            "resources": {
                self.hashes[0]: {"note": "</script><script>evil()</script> SCRIPT PAYLOAD $script"}
            },
        }
        path = self.root / "recipes.json"
        path.write_text(json.dumps(config))
        _, out = self.run_interpret(recipes=path)
        page = (out / "index.html").read_text()
        self.assertNotIn("<script>evil()", page)
        self.assertEqual(page.count(SCRIPT), 1)
        self.assertIn("sha256-" + base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode(), page)
        self.assertIn("SCRIPT PAYLOAD $script", page)

    def test_recipe_unknown_hash_wrong_rom_and_evidence(self):
        config = {"format": "arcanacart-recipes-1", "rom_sha256": "a" * 64, "resources": {}}
        for recipe in [
            {"mode": "tiles", "review": "accepted"},
            {"bpp": 5},
            {"width_tiles": True},
            {"palette_sha256": "b" * 64},
            {"code": '__import__("os")'},
        ]:
            config["resources"] = {self.hashes[0]: recipe}
            with self.assertRaises(ValueError):
                check_recipes(config, "a" * 64, set(self.hashes))
        with self.assertRaises(ValueError):
            check_recipes(config, "b" * 64, set(self.hashes))

    def test_blob_hypotheses_do_not_claim_identity(self):
        result = inspect_blob(bytes(32))
        self.assertEqual(result["uniform_byte"], 0)
        self.assertEqual(result["validation"], "inferred")
        self.assertIn("tiles4", result["hypotheses"])
        self.assertNotIn("identified", result)

    def test_cli_end_to_end(self):
        import contextlib
        import io

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["interpret", "--input", str(self.source), "--out", str(self.root / "cli")])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["generated_previews"], 2)

    def test_report_must_match_review_provenance(self):
        result, _ = self.run_interpret()
        metrics = resource_metrics(self.manifest, result)
        self.assertEqual(metrics["pending_interpretation"], 2)
        result["rom_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            resource_metrics(self.manifest, result)
