"""Raw icon banks: exact bytes, bounded references and independent pixel checks."""

import base64
import contextlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from arcanacart.cli import main
from arcanacart.core.io import digest, json_bytes
from arcanacart.faces import FE7_SHA256, FE8_SHA256
from arcanacart.icon_gallery import SCRIPT
from arcanacart.icons import BUILTIN_LAYOUTS, FORMAT, extract_icons


def png_pixels(path):
    data = path.read_bytes()
    chunks, cursor = [], 8
    while cursor < len(data):
        size = struct.unpack_from(">I", data, cursor)[0]
        kind = data[cursor + 4 : cursor + 8]
        chunk = data[cursor + 8 : cursor + 8 + size]
        if kind == b"IHDR":
            width, height = struct.unpack_from(">II", chunk)
        elif kind == b"IDAT":
            chunks.append(chunk)
        cursor += size + 12
    raw = zlib.decompress(b"".join(chunks))
    stride = width * 4 + 1
    return width, height, b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(height))


class ItemIcons(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arcana icon space ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data = bytearray(0x4000)
        data[0xAC:0xB0] = b"BE8E"
        data[0xB2] = 0x96
        data[0xBD] = (-(sum(data[0xA0:0xBD]) + 0x19)) & 255
        struct.pack_into("<II", data, 0x100, 0x08001000, 0x08002000)
        quadrants = b"\x11" * 32 + b"\x22" * 32 + b"\x33" * 32 + b"\x44" * 32
        self.raws = [quadrants, quadrants, bytes(128), b"\x11" * 128]
        for i, raw in enumerate(self.raws):
            data[0x1000 + i * 128 : 0x1000 + (i + 1) * 128] = raw
        self.palette = struct.pack("<16H", 0, 31, 31 << 5, 31 << 10, 0x7FFF, *([0] * 11))
        data[0x2000:0x2020] = self.palette
        self.rom = self.root / "rom with spaces.gba"
        self.rom.write_bytes(data)
        self.rom_hash = digest(data)
        self.layout = {
            "format": FORMAT,
            "rom_sha256": self.rom_hash,
            "game": "fe8",
            "table_offset": 0x1000,
            "pointer_location": 0x100,
            "first_id": 5,
            "icon_count": 4,
            "icon_bytes": 128,
            "palette_offset": None,
            "palette_pointer_location": 0x104,
            "sources": ["synthetic; not a commercial ROM"],
        }
        self.definition = self.root / "definition.json"
        self.definition.write_bytes(json_bytes(self.layout))
        self.document = {
            "rom": {"sha256": self.rom_hash, "size_bytes": len(data)},
            "resources": [],
            "scan": {"truncated": False, "methods": ["lz10"]},
        }
        self.air = self.root / "air.json"
        self.air.write_bytes(json_bytes(self.document))
        self.out = self.root / "out"

    def extract(self, **kwargs):
        return extract_icons(self.rom, self.out, definition=self.definition, **kwargs)

    def call_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(map(str, args)))
        return code, stdout.getvalue(), stderr.getvalue()

    def update_rom(self, offset, data):
        image = bytearray(self.rom.read_bytes())
        image[offset : offset + len(data)] = data
        self.rom.write_bytes(image)
        self.layout["rom_sha256"] = digest(image)
        self.definition.write_bytes(json_bytes(self.layout))

    def test_render_exact_colors_tile_order_and_duplicate_origins(self):
        result = self.extract()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["first_id"], result["last_id"]), (5, 8))
        self.assertEqual((result["icon_occurrences"], result["unique_images"]), (4, 3))
        self.assertEqual(result["transparent_occurrences"], 1)
        self.assertEqual((result["visible_images"], result["transparent_images"]), (2, 1))
        self.assertEqual(result["duplicate_png_copies_avoided"], 1)
        rows = json.loads((self.out / "catalog.json").read_bytes())["icons"]
        self.assertEqual([r["icon_id"] for r in rows], [5, 6, 7, 8])
        self.assertEqual(rows[0]["file"], rows[1]["file"])
        self.assertNotEqual(rows[0]["source_offset"], rows[1]["source_offset"])
        width, height, rgba = png_pixels(self.out / rows[0]["file"])
        self.assertEqual((width, height), (16, 16))
        for x, y, color in [
            (0, 0, (255, 0, 0, 255)),
            (8, 0, (0, 255, 0, 255)),
            (0, 8, (0, 0, 255, 255)),
            (8, 8, (255, 255, 255, 255)),
        ]:
            at = (y * 16 + x) * 4
            self.assertEqual(tuple(rgba[at : at + 4]), color)
        self.assertFalse(rows[2]["visible"])
        self.assertEqual(set(png_pixels(self.out / rows[2]["file"])[2][3::4]), {0})
        for row, raw in zip(rows, self.raws, strict=True):
            self.assertEqual((self.out / row["raw_file"]).read_bytes(), raw)
            self.assertEqual(row["source_sha256"], digest(raw))
            self.assertEqual((self.out / row["palette_file"]).read_bytes(), self.palette)

    def test_all_artifacts_manifest_csv_and_inputs_preserved(self):
        before = {p: p.read_bytes() for p in [self.rom, self.definition, self.air]}
        self.extract(source=self.air)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        state = json.loads((self.out / "icons-state.json").read_bytes())
        files = {p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()}
        self.assertEqual(set(state["artifacts"]), files - {"icons-state.json"})
        for file, hash_ in state["artifacts"].items():
            self.assertEqual(digest((self.out / file).read_bytes()), hash_)
        import csv

        with (self.out / "icons.csv").open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        self.assertEqual([int(r["icon_id"]) for r in csv_rows], [5, 6, 7, 8])
        self.assertEqual({r["rom_sha256"] for r in csv_rows}, {self.rom_hash})
        resolved = json.loads((self.out / "definition.json").read_bytes())
        self.assertEqual(resolved["palette_offset"], 0x2000)

    def test_subrange_is_inclusive_and_uses_definition_first_id(self):
        result = self.extract(first_id=6, last_id=7)
        self.assertEqual(result["icon_occurrences"], 2)
        rows = json.loads((self.out / "catalog.json").read_bytes())["icons"]
        self.assertEqual([r["source_offset"] for r in rows], [0x1080, 0x1100])

    def test_dry_run_never_creates_output(self):
        result = self.extract(dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertFalse(self.out.exists())

    def test_header_hint_does_not_enable_automatic_vanilla_layout(self):
        with self.assertRaisesRegex(ValueError, "base FE7/FE8 USA exacta"):
            extract_icons(self.rom, self.out)
        self.assertFalse(self.out.exists())

    def test_builtin_bounds_and_sources_are_pinned(self):
        self.assertEqual(BUILTIN_LAYOUTS[FE7_SHA256]["icon_count"], 173)
        self.assertEqual(BUILTIN_LAYOUTS[FE8_SHA256]["icon_count"], 224)
        for spec in BUILTIN_LAYOUTS.values():
            self.assertEqual(spec["first_id"], 0)
            self.assertTrue(all("/blob/" in s for s in spec["sources"]))

    def test_automatic_layout_checks_same_pointers_as_explicit_layout(self):
        with patch.dict(BUILTIN_LAYOUTS, {self.rom_hash: self.layout}):
            result = extract_icons(self.rom, self.out)
        self.assertEqual(result["definition_origin"], "builtin-exact-rom")

    def test_wrong_rom_bytes_rejected_without_outputs(self):
        image = bytearray(self.rom.read_bytes())
        image[-1] = 1
        self.rom.write_bytes(image)
        with self.assertRaises(ValueError):
            self.extract()
        self.assertFalse(self.out.exists())

    def test_repointed_bank_does_not_silently_read_old_offset(self):
        self.update_rom(0x100, struct.pack("<I", 0x08001200))
        with self.assertRaisesRegex(ValueError, "puntero de iconos"):
            self.extract()
        self.assertFalse(self.out.exists())

    def test_bad_pointer_window_and_out_of_rom_are_rejected(self):
        for pointer in (0, 0x02001000, 0x08003FF0):
            with self.subTest(pointer=pointer):
                self.update_rom(0x104, struct.pack("<I", pointer))
                with self.assertRaises(ValueError):
                    self.extract()

    def test_explicit_palette_and_pointer_must_match(self):
        self.layout["palette_offset"] = 0x2020
        self.definition.write_bytes(json_bytes(self.layout))
        with self.assertRaisesRegex(ValueError, "puntero de paleta"):
            self.extract()

    def test_explicit_direct_offsets_are_supported(self):
        self.layout.update(pointer_location=None, palette_pointer_location=None, palette_offset=0x2000)
        self.definition.write_bytes(json_bytes(self.layout))
        self.assertEqual(self.extract()["icon_occurrences"], 4)

    def test_invalid_ranges_and_layouts_do_not_write(self):
        original = dict(self.layout)
        for field, value in [
            ("icon_count", 4097),
            ("icon_count", True),
            ("icon_bytes", 64),
            ("table_offset", 0x3F00),
            ("first_id", -1),
            ("game", []),
            ("sources", []),
            ("palette_offset", -1),
        ]:
            with self.subTest(field=field, value=value):
                self.layout = {**original, field: value}
                self.definition.write_bytes(json_bytes(self.layout))
                with self.assertRaises(ValueError):
                    self.extract()
                self.assertFalse(self.out.exists())

    def test_bad_selected_range_rejected(self):
        for low, high in [(4, 8), (5, 9), (8, 6), (True, 8)]:
            with self.subTest(low=low, high=high), self.assertRaises(ValueError):
                self.extract(first_id=low, last_id=high)

    def test_air_identity_must_match(self):
        self.document["rom"]["sha256"] = "0" * 64
        self.air.write_bytes(json_bytes(self.document))
        with self.assertRaisesRegex(ValueError, "AIR no corresponde"):
            self.extract(source=self.air)
        self.assertFalse(self.out.exists())

    def test_air_line_endings_are_not_normalized_for_hashes(self):
        lf = json_bytes(self.document)
        crlf = lf.replace(b"\n", b"\r\n")
        self.air.write_bytes(crlf)
        result = self.extract(source=self.air)
        self.assertEqual(result["source_manifest_sha256"], digest(crlf))
        self.assertNotEqual(result["source_manifest_sha256"], digest(lf))

    def test_air_inventory_keeps_candidates_unclassified(self):
        self.document["resources"] = [
            {
                "offset": 0x3000,
                "compressed_bytes": 9,
                "decompressed_bytes": 4,
                "compression": "lz10",
                "sha256": digest(b"DEMO"),
                "references": [],
            }
        ]
        self.air.write_bytes(json_bytes(self.document))
        result = self.extract(source=self.air)
        self.assertEqual(result["air_candidates_inventoried"], 1)
        self.assertIn("unclassified-air-candidate", (self.out / "air-inventory.csv").read_text())
        self.assertFalse((self.root / "resources").exists())

    def test_existing_output_is_not_replaced(self):
        self.out.mkdir()
        marker = self.out / "previous.json"
        marker.write_bytes(b"keep this")
        with self.assertRaises(ValueError):
            self.extract()
        self.assertEqual(marker.read_bytes(), b"keep this")

    def test_symlink_input_rejected(self):
        link = self.root / "linked.gba"
        try:
            link.symlink_to(self.rom)
        except OSError:
            self.skipTest("Symlinks not available")
        with self.assertRaises(ValueError):
            extract_icons(link, self.out, definition=self.definition)

    def test_gallery_embedded_data_csp_and_no_external_scripts(self):
        self.extract()
        page = (self.out / "index.html").read_text()
        self.assertIn(base64.b64encode(bytes.fromhex(digest(SCRIPT.encode()))).decode(), page)
        self.assertNotIn("<script src=", page)
        start = page.index('<script id="icon-data" type="application/json">')
        data = page[start:].split(">", 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(data), json.loads((self.out / "catalog.json").read_bytes())["icons"])

    def test_cli_and_invalid_range_exit_codes(self):
        args = ["icons", "--rom", self.rom, "--definition", self.definition, "--out", self.out]
        code, stdout, stderr = self.call_cli(*args, "--dry-run")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["status"], "planned")
        code, _, stderr = self.call_cli(*args, "--last-id", "0xFFFF")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr)["status"], "error")
        self.assertFalse(self.out.exists())
        code, stdout, stderr = self.call_cli(*args)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["icon_occurrences"], 4)


if __name__ == "__main__":
    unittest.main()
