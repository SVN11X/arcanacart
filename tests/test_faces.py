"""Face-table extraction and RGB555 palette provenance; synthetic ROMs only."""

import base64
import contextlib
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from arcanacart import graphics
from arcanacart.cli import main
from arcanacart.core.io import digest, json_bytes
from arcanacart.face_gallery import SCRIPT
from arcanacart.faces import DEFAULT_LAYOUT, FE8_LAYOUT, FE8_SHA256, reconstruct_faces


def literal_lz(raw):
    return (
        b"\x10"
        + len(raw).to_bytes(3, "little")
        + b"".join(b"\0" + raw[i : i + 8] for i in range(0, len(raw), 8))
    )


def decode_png(path):
    raw = path.read_bytes()
    at, data = 8, b""
    while at < len(raw):
        size = struct.unpack_from(">I", raw, at)[0]
        kind, chunk = raw[at + 4 : at + 8], raw[at + 8 : at + 8 + size]
        if kind == b"IHDR":
            width, height = struct.unpack_from(">II", chunk)
        if kind == b"IDAT":
            data += chunk
        at += size + 12
    stride = width * 4 + 1
    pixels = zlib.decompress(data)
    return width, height, b"".join(pixels[y * stride + 1 : (y + 1) * stride] for y in range(height))


class PortraitLayout(unittest.TestCase):
    def test_obj_parts_reach_expected_body_positions(self):
        raw = b"".join(bytes([((i % 15) + 1) * 17]) * 32 for i in range(128))
        width, height, pixels = graphics.portrait(raw)
        self.assertEqual((width, height), (96, 80))
        for x, y, gray in (
            (16, 0, 17),
            (16, 32, 153),
            (16, 64, 34),
            (0, 48, 102),
            (48, 64, 102),
            (80, 48, 136),
        ):
            at = (y * width + x) * 4
            self.assertEqual(pixels[at : at + 4], bytes([gray, gray, gray, 255]))
        self.assertEqual(pixels[:4], bytes(4))

    def test_wrong_sheet_size_rejected(self):
        for size in (512, 2880, 8192):
            with self.assertRaises(ValueError):
                graphics.portrait(bytes(size))


class FaceExtraction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arcana face ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resources = self.root / "resources"
        self.resources.mkdir()
        image = bytearray(0x10000)
        self.table = 0x100
        struct.pack_into("<I", image, 0x10, 0x08000100)
        self.raws = [b"\x11" * 4096, b"\x22" * 512, b"\x33" * 2880]
        self.offsets = [0x1000, 0x3000, 0x6000]
        self.hashes = [digest(raw) for raw in self.raws]
        self.palette = struct.pack("<16H", 0, 31, 31 << 5, 31 << 10, *([0] * 12))
        image[0x5000:0x5020] = self.palette
        for face_id in (1, 2):
            entry = self.table + face_id * 28
            struct.pack_into("<III", image, entry, 0x08001000, 0x08003000, 0x08005000)
        struct.pack_into("<I", image, self.table + 3 * 28 + 8, 0x08005000)
        struct.pack_into("<I", image, self.table + 3 * 28 + 16, 0x08006000)
        records = []
        for n, (raw, offset) in enumerate(zip(self.raws, self.offsets, strict=True)):
            encoded = literal_lz(raw)
            image[offset : offset + len(encoded)] = encoded
            (self.resources / (digest(raw) + ".bin")).write_bytes(raw)
            locations = (
                [self.table + 28, self.table + 56]
                if n == 0
                else [self.table + 28 + 4, self.table + 56 + 4]
                if n == 1
                else [self.table + 84 + 16]
            )
            records.append(
                {
                    "offset": offset,
                    "compressed_bytes": len(encoded),
                    "decompressed_bytes": len(raw),
                    "sha256": digest(raw),
                    "encoded_sha256": digest(encoded),
                    "compression": "lz10",
                    "references": [{"location": at, "target_offset": offset} for at in locations],
                }
            )
        self.rom = self.root / "base.gba"
        self.rom.write_bytes(image)
        self.document = {
            "rom": {"sha256": digest(image), "size_bytes": len(image)},
            "resources": records,
            "scan": {"methods": ["lz10"], "truncated": False, "step": 1},
        }
        self.air = self.root / "air.json"
        self.air.write_bytes(json_bytes(self.document))
        self.definition = {
            **DEFAULT_LAYOUT,
            "rom_sha256": digest(image),
            "table_offset": self.table,
            "entry_count": 4,
            "pointer_location": 0x10,
        }
        self.layout = self.root / "layout.json"
        self.layout.write_bytes(json_bytes(self.definition))
        self.review = self.root / "review"
        self.recipes = self.root / "recipes.json"
        self.recipes.write_text("manual recipes stay untouched")

    def run_faces(self, **kwargs):
        return reconstruct_faces(self.air, self.review, definition=self.layout, **kwargs)

    def test_offline_reconstruction_keeps_color_and_review_uncertainty(self):
        original = {p: p.read_bytes() for p in (self.air, self.recipes, *self.resources.glob("*.bin"))}
        result = self.run_faces()
        self.assertEqual((result["portraits"], result["miniatures"], result["classcards"]), (2, 2, 1))
        self.assertEqual(result["unique_classified_blobs"], 3)
        self.assertEqual(result["generated_component_pngs"], 5)
        self.assertEqual(result["components_without_real_palette"], 5)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["rom_bytes_verified"])
        self.assertFalse(result["manual_reviews_modified"])
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        rows = json.loads((self.review / "catalog.json").read_bytes())["resources"]
        self.assertEqual({r["review"] for r in rows}, {"unreviewed"})
        self.assertEqual(len(list(self.review.rglob("*.png"))), 5)

    def test_local_rom_recovers_exact_palette_and_verifies_known_blocks(self):
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["resolved_palettes"], 1)
        self.assertEqual(result["components_without_real_palette"], 0)
        self.assertEqual(result["decoded_known_offsets"], 3)
        self.assertTrue(result["rom_bytes_verified"])
        self.assertFalse(result["rescanned"])
        self.assertEqual(
            (self.review / "paletas" / (digest(self.palette) + ".bin")).read_bytes(), self.palette
        )
        w, h, pixels = decode_png(self.review / "retratos/face-001.png")
        self.assertEqual((w, h), (96, 80))
        self.assertEqual(pixels[16 * 4 : 17 * 4], bytes([255, 0, 0, 255]))
        _, _, pixels = decode_png(self.review / "miniaturas/face-001.png")
        self.assertEqual(pixels[:4], bytes([0, 255, 0, 255]))
        w, h, pixels = decode_png(self.review / "tarjetas-clase/face-003.png")
        self.assertEqual((w, h), (80, 72))
        self.assertEqual(pixels[:4], bytes([0, 0, 255, 255]))

    def test_wrong_rom_stops_before_output(self):
        self.rom.write_bytes(b"x" * 65536)
        with self.assertRaises(ValueError):
            self.run_faces(rom_path=self.rom)
        self.assertFalse(self.review.exists())

    def test_actual_table_pointer_must_match_definition(self):
        self.definition["table_offset"] += 4
        self.layout.write_bytes(json_bytes(self.definition))
        with self.assertRaisesRegex(ValueError, "puntero real"):
            self.run_faces(rom_path=self.rom)
        self.assertFalse(self.review.exists())

    def test_invalid_palette_pointer_is_reported_without_guessed_colors(self):
        image = bytearray(self.rom.read_bytes())
        for face_id in (1, 2, 3):
            struct.pack_into("<I", image, self.table + face_id * 28 + 8, 0)
        self.rom.write_bytes(image)
        self.document["rom"]["sha256"] = digest(image)
        self.definition["rom_sha256"] = digest(image)
        self.air.write_bytes(json_bytes(self.document))
        self.layout.write_bytes(json_bytes(self.definition))
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"], 5)
        self.assertEqual(result["generated_component_pngs"], 0)
        self.assertEqual(result["resolved_palettes"], 0)

    def test_automatic_layout_rejects_unknown_rom(self):
        with self.assertRaises(ValueError):
            reconstruct_faces(self.air, self.review)

    def test_custom_layout_is_hash_bound_and_bounded(self):
        for updates in (
            {"rom_sha256": "b" * 64},
            {"entry_count": True},
            {"entry_count": 5000},
            {"entry_size": 32},
            {"table_offset": 65535},
            {"pointer_location": -1},
        ):
            self.layout.write_bytes(json_bytes({**self.definition, **updates}))
            with self.assertRaises(ValueError):
                self.run_faces()

    def test_dry_run_leaves_output_absent(self):
        result = self.run_faces(dry_run=True, rom_path=self.rom)
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["rom_bytes_verified"])
        self.assertFalse(self.review.exists())

    def test_missing_blob_is_reported_without_false_completion(self):
        (self.resources / (self.hashes[0] + ".bin")).unlink()
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["portraits"], 0)

    def test_encoded_hash_mismatch_is_partial(self):
        self.document["resources"][0]["encoded_sha256"] = "0" * 64
        self.air.write_bytes(json_bytes(self.document))
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"], 2)

    def use_raw_portrait(self, raw=None, *, stored_size=None, type_byte=0):
        raw = self.raws[0] if raw is None else raw
        image = bytearray(self.rom.read_bytes())
        size = len(raw) + 4 if stored_size is None else stored_size
        block = bytes([type_byte]) + size.to_bytes(3, "little") + raw
        image[self.offsets[0] : self.offsets[0] + len(block)] = block
        self.rom.write_bytes(image)
        self.document["rom"]["sha256"] = digest(image)
        self.definition["rom_sha256"] = digest(image)
        self.document["resources"] = [r for r in self.document["resources"] if r["offset"] != self.offsets[0]]
        self.air.write_bytes(json_bytes(self.document))
        self.layout.write_bytes(json_bytes(self.definition))
        return raw, block

    def test_raw_header_includes_itself_and_keeps_air_counts_separate(self):
        raw, block = self.use_raw_portrait()
        air_before = self.air.read_bytes()
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["portraits"], result["miniatures"], result["classcards"]), (2, 2, 1))
        self.assertEqual(result["unique_classified_blobs"], 2)
        self.assertEqual(result["unclassified_input_blobs"], 0)
        self.assertEqual(result["unique_component_blobs"], 3)
        self.assertEqual(result["raw_rom_components"], 2)
        self.assertEqual(result["unique_raw_rom_blobs"], 1)
        self.assertEqual(result["raw_rom_bytes_read"], 4100)
        self.assertEqual(result["decoded_known_offsets"], 2)
        self.assertEqual((self.review / "raw-resources" / (digest(raw) + ".bin")).read_bytes(), raw)
        self.assertEqual(self.air.read_bytes(), air_before)
        rows = json.loads((self.review / "catalog.json").read_bytes())["resources"]
        portraits = [r for r in rows if r["kind"] == "portrait"]
        for row in portraits:
            self.assertEqual(row["size_bytes"], 4096)
            self.assertEqual(row["stored_bytes"], 4100)
            self.assertEqual(row["compressed_bytes"], 0)
            self.assertEqual(row["compression"], "none")
            self.assertEqual(row["payload_offset"], self.offsets[0] + 4)
            self.assertEqual(row["encoded_sha256"], digest(block))
            self.assertEqual(row["data_origin"], "local-rom-raw")
            self.assertEqual(row["verification"], "rom-table-and-raw-data")
        w, h, pixels = decode_png(self.review / "retratos/face-001.png")
        self.assertEqual((w, h), (96, 80))
        self.assertEqual(pixels[16 * 4 : 17 * 4], bytes([255, 0, 0, 255]))
        state = json.loads((self.review / "faces-state.json").read_bytes())
        self.assertEqual(state["artifacts"][portraits[0]["raw_blob"]], digest(raw))
        self.assertIn(portraits[0]["raw_blob"], (self.review / "index.html").read_text())

    def test_raw_5120_byte_sheet_is_supported(self):
        self.use_raw_portrait(b"\x11" * 5120)
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["raw_rom_bytes_read"], 5124)

    def test_raw_length_that_excludes_header_is_not_silently_accepted(self):
        self.use_raw_portrait(stored_size=4096)
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["portraits"], 0)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["unique_raw_rom_blobs"], 0)

    def test_raw_size_limit_and_unknown_encoding_are_rejected(self):
        for update in ({"stored_size": 10000}, {"stored_size": 4}, {"type_byte": 0x10}):
            with self.subTest(update=update):
                self.use_raw_portrait(**update)
                out = self.root / ("bad-" + str(len(list(self.root.glob("bad-*")))))
                result = reconstruct_faces(self.air, out, definition=self.layout, rom_path=self.rom)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["portraits"], 0)
                self.assertEqual(result["errors"], 2)
                self.assertFalse((out / "raw-resources").exists())

    def test_raw_range_must_be_inside_rom(self):
        self.use_raw_portrait()
        image = bytearray(self.rom.read_bytes())
        at = len(image) - 32
        image[at : at + 4] = b"\0" + (4100).to_bytes(3, "little")
        for face_id in (1, 2):
            struct.pack_into("<I", image, self.table + face_id * 28, 0x08000000 + at)
        self.rom.write_bytes(image)
        self.document["rom"]["sha256"] = digest(image)
        self.definition["rom_sha256"] = digest(image)
        self.air.write_bytes(json_bytes(self.document))
        self.layout.write_bytes(json_bytes(self.definition))
        result = self.run_faces(rom_path=self.rom)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["unique_raw_rom_blobs"], 0)

    def test_fe8_auto_layout_has_pending_counts_without_local_rom(self):
        self.document["rom"]["sha256"] = FE8_SHA256
        self.document["rom"]["size_bytes"] = 0x1000000
        self.air.write_bytes(json_bytes(self.document))
        result = reconstruct_faces(self.air, self.review)
        self.assertEqual(result["layout"], FE8_LAYOUT)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["pending_component_total"], 283)
        self.assertEqual(
            result["expected_component_counts"], {"portrait": 115, "miniature": 111, "classcard": 57}
        )
        self.assertEqual(result["raw_rom_components"], 0)
        self.assertEqual(result["generated_component_pngs"], 0)

    def test_reference_target_mismatch_stops(self):
        self.document["resources"][0]["references"][0]["target_offset"] += 4
        self.air.write_bytes(json_bytes(self.document))
        with self.assertRaises(ValueError):
            self.run_faces()

    def test_existing_output_and_input_directory_are_protected(self):
        self.run_faces()
        with self.assertRaises(ValueError):
            self.run_faces()
        with self.assertRaises(ValueError):
            reconstruct_faces(self.air, self.resources / "bad", definition=self.layout)

    def test_gallery_csp_and_definition_text_are_escaped(self):
        self.definition["sources"] = ["</script><script>evil()</script>"]
        self.layout.write_bytes(json_bytes(self.definition))
        self.run_faces()
        page = (self.review / "index.html").read_text()
        self.assertNotIn("<script>evil()", page)
        token = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
        self.assertIn("sha256-" + token, page)

    def test_cli_color_export(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(
                [
                    "faces",
                    "--input",
                    str(self.air),
                    "--rom",
                    str(self.rom),
                    "--definition",
                    str(self.layout),
                    "--out",
                    str(self.review),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["resolved_palettes"], 1)

    @unittest.skipUnless(os.name == "nt", "Requiere PowerShell en Windows.")
    def test_windows_launcher_color_export(self):
        shell = shutil.which("pwsh") or str(
            Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        script = Path(__file__).resolve().parents[1] / "scripts/windows/Extraer-Retratos.ps1"
        proc = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Game",
                "fe8",
                "-AirPath",
                str(self.air),
                "-RomPath",
                str(self.rom),
                "-Definition",
                str(self.layout),
                "-PythonExe",
                sys.executable,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        summaries = list(self.root.glob("retratos-*/summary.json"))
        self.assertEqual(len(summaries), 1)
        self.assertEqual(json.loads(summaries[0].read_bytes())["resolved_palettes"], 1)
