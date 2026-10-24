"""Synthetic evidence packets exercise reviewed sprite extraction without ROMs."""

import contextlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from arcanacart import map_sprite_catalog as catalog
from arcanacart import map_sprite_followup as follow
from arcanacart import map_sprite_review as review
from arcanacart.core.io import digest, json_bytes
from arcanacart.icon_variants import _publish


def literal_lz(raw):
    return (
        b"\x10"
        + len(raw).to_bytes(3, "little")
        + b"".join(b"\0" + raw[i : i + 8] for i in range(0, len(raw), 8))
    )


def color(role, index):
    if index == 0:
        return (0, 0, 0, 0)
    return (
        ((role * 3 + index) & 31) * 255 // 31,
        ((index * 2 + role) & 31) * 255 // 31,
        ((index * 3 + role * 2) & 31) * 255 // 31,
        255,
    )


def png_pixels(raw):
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    position, compressed = 8, bytearray()
    while position < len(raw):
        length = struct.unpack_from(">I", raw, position)[0]
        kind = raw[position + 4 : position + 8]
        data = raw[position + 8 : position + 8 + length]
        assert zlib.crc32(kind + data) == struct.unpack_from(">I", raw, position + 8 + length)[0]
        if kind == b"IHDR":
            width, height, depth, type_, _, _, interlace = struct.unpack(">IIBBBBB", data)
            assert (depth, type_, interlace) == (8, 6, 0)
        if kind == b"IDAT":
            compressed.extend(data)
        position += length + 12
    pixels = zlib.decompress(compressed)
    stride = width * 4 + 1
    assert len(pixels) == stride * height
    assert all(pixels[y * stride] == 0 for y in range(height))
    return width, height, b"".join(pixels[y * stride + 1 : (y + 1) * stride] for y in range(height))


def make_packet(root):
    source, definitions = root / "revision", root / "definiciones.json"
    raws = [
        bytes(384),
        b"\x11" * 256 + b"\x22" * 256 + b"\x33" * 256,
        b"".join(bytes([(tile % 15 + 1) * 17]) * 32 for tile in range(48)),
    ]
    payloads, profiles, specs = {}, [], []
    for game, vid in (("fe7", "fe7-base"), ("fe8", "fe8-001")):
        palette_start = 0x4000 if game == "fe7" else 0x5000
        pal_specs, candidates = {}, []
        loader = bytearray(96)
        loader[:10] = bytes.fromhex("00b50948e02189008022")
        for i, role in enumerate(review.PALETTES):
            values = [0] + [
                ((i * 3 + index) & 31) | (((index * 2 + i) & 31) << 5) | (((index * 3 + i * 2) & 31) << 10)
                for index in range(1, 16)
            ]
            raw = struct.pack("<16H", *values)
            name = f"paletas-origen/{vid}-{role}.bin"
            payloads[name] = raw
            pal_specs[role] = {"offset": palette_start + i * 32, "sha256": digest(raw)}
            candidates.append({"role_hint": role, **pal_specs[role], "file": name})
        for role, position in {"player": 0x28, "fourth": 0x30, "light-rune": 0x44, "sepia": 0x5C}.items():
            struct.pack_into("<I", loader, position, 0x08000000 + pal_specs[role]["offset"])
        context = bytearray(1024)
        context[0xF8:0x158] = loader
        context_file = f"evidencias/{vid}/contexto.bin"
        payloads[context_file] = context
        entries, table = [], bytearray()
        for i, raw in enumerate(raws):
            blob = literal_lz(raw)
            name = "hojas/" + digest(blob) + ".lz10"
            payloads[name] = blob
            pointer = 0x08002000 + i * 0x800
            table.extend(struct.pack("<HHI", 2, i, pointer))
            width, height, size = review.SIZE[i]
            entry = {
                "sprite_id": i,
                "sprite_id_hex": f"0x{i:02X}",
                "entry_offset": 0x1000 + i * 8,
                "pattern": 2,
                "size_code": i,
                "sheet_pointer": pointer,
                "sheet_offset": pointer - 0x08000000,
                "status": "candidate",
                "issues": [],
                "frame_width": width,
                "frame_height": height,
                "decoded_bytes": size,
                "expected_bytes_for_three_frames": size,
                "compressed_bytes": len(blob),
                "stored_file": name,
                "stored_sha256": digest(blob),
            }
            if game == "fe8":
                entry["air_decoded_sha256"] = digest(raw)
            entries.append(entry)
        table.extend(bytes(8))
        table_file = f"evidencias/{vid}/tabla.bin"
        payloads[table_file] = table
        profile = {
            "variant_id": vid,
            "game": game,
            "variant": vid + " synthetic",
            "rom_sha256": digest(vid.encode()),
            "air_sha256": digest(b"air") if game == "fe8" else None,
            "rom_size_bytes": 0x8000,
            "status": "pending",
            "followup_rom_bytes_verified": True,
            "table_offset": 0x1000,
            "table_window_file": table_file,
            "table_window_sha256": digest(table),
            "entries": entries,
            "palette_candidates": candidates,
            "palette_load_context": {
                "file": context_file,
                "offset": 0x500,
                "size_bytes": 1024,
                "sha256": digest(context),
            },
        }
        profiles.append(profile)
        specs.append(
            {key: profile[key] for key in ("variant_id", "game", "variant", "rom_sha256", "air_sha256")}
            | {
                "first_id": 0,
                "last_id": 2,
                "table_offset": 0x1000,
                "table_sha256": digest(table[:24]),
                "table_window_sha256": digest(table),
                "palette_loader_offset": 0x5F8,
                "palette_loader_sha256": digest(loader),
                "palettes": pal_specs,
            }
        )
    report = {
        "format": follow.FORMAT,
        "status": "completed",
        "counts": {"error": 0},
        "plan_canonical_sha256": digest(b"plan"),
        "results": profiles,
    }
    payloads["revision.json"] = json_bytes(report)
    _publish(source, payloads, state_name=review.STATE)
    registry = {
        "format": catalog.DEFINITION_FORMAT,
        "source_report_sha256": digest(payloads["revision.json"]),
        "source_state_sha256": digest((source / review.STATE).read_bytes()),
        "plan_canonical_sha256": report["plan_canonical_sha256"],
        "capacity_confirmed": False,
        "in_game_verified": False,
        "definitions": specs,
    }
    definitions.write_bytes(json_bytes(registry))
    return source, definitions, registry, raws


class MapSpriteCatalog(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="arcana sprites con espacios ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.definitions, self.registry, self.raws = make_packet(self.root)
        self.out = self.root / "catalogo"

    def run_extract(self):
        return catalog.extract_sprites(self.source, self.out, self.definitions)

    def data(self):
        return json.loads((self.out / "catalogo.json").read_bytes())

    def repin(self, report=None):
        if report is not None:
            (self.source / "revision.json").write_bytes(json_bytes(report))
        state = {
            "status": "completed",
            "artifacts": {
                p.relative_to(self.source).as_posix(): digest(p.read_bytes())
                for p in self.source.rglob("*")
                if p.is_file() and p.name != review.STATE
            },
        }
        (self.source / review.STATE).write_bytes(json_bytes(state))
        self.registry["source_state_sha256"] = digest((self.source / review.STATE).read_bytes())
        self.registry["source_report_sha256"] = digest((self.source / "revision.json").read_bytes())
        self.definitions.write_bytes(json_bytes(self.registry))

    def test_real_definitions_bind_all_45_identities_to_the_audited_packet(self):
        definitions = catalog._definitions(catalog.DEFINITIONS)
        self.assertEqual(len(definitions["definitions"]), 45)
        self.assertEqual(sum(not d["variant_id"].endswith("-base") for d in definitions["definitions"]), 43)
        self.assertEqual(sum(d["last_id"] + 1 for d in definitions["definitions"]), 9812)

    def test_deduplicates_without_losing_origins_and_never_opens_roms(self):
        before = {p: p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        with (
            patch.object(catalog, "decompress", wraps=catalog.decompress) as decode,
            patch("arcanacart.pipeline.load_rom", side_effect=AssertionError("ROM")),
            patch("arcanacart.compression.scan_resources", side_effect=AssertionError("scan")),
        ):
            summary = self.run_extract()
        self.assertEqual(decode.call_count, 3)
        self.assertEqual(summary["sheet_occurrences"], 6)
        self.assertEqual(summary["unique_raw_sheets"], 3)
        self.assertEqual(summary["render_sets"], 3)
        self.assertEqual(summary["unique_palettes"], 7)
        self.assertFalse(summary["roms_read"])
        self.assertFalse(summary["in_game_verified"])
        self.assertEqual(len(self.data()["occurrences"]), 6)
        for p, raw in before.items():
            self.assertEqual(p.read_bytes(), raw)

    def test_all_three_frame_geometries_and_pixels_are_exact(self):
        self.run_extract()
        data = self.data()
        for render in data["render_sets"]:
            role = "enemy"
            refs = render["renderings"][role]
            sheet = data["assets"][refs["sheet"]]
            width, height, pixels = png_pixels((self.out / sheet["file"]).read_bytes())
            self.assertEqual((width, height), (render["width"], render["height"] * 3))
            for index, key in enumerate(refs["frames"]):
                frame = data["assets"][key]
                fw, fh, rgba = png_pixels((self.out / frame["file"]).read_bytes())
                self.assertEqual((fw, fh), (render["width"], render["height"]))
                self.assertEqual(rgba, pixels[index * fw * fh * 4 : (index + 1) * fw * fh * 4])
                if (fw, fh) == (16, 32):
                    self.assertEqual(rgba, bytes(color(1, index + 1)) * (fw * fh))
                if (fw, fh) == (32, 32):
                    self.assertEqual(rgba[:4], bytes(color(1, (index * 16) % 15 + 1)))

    def test_transparent_frames_and_raws_are_preserved(self):
        result = self.run_extract()
        self.assertEqual(result["transparent_render_sets"], 1)
        self.assertEqual(len(list((self.out / "raw").glob("*.4bpp"))), 3)
        self.assertEqual((self.out / "raw" / (digest(self.raws[0]) + ".4bpp")).read_bytes(), self.raws[0])
        blank = next(s for s in self.data()["render_sets"] if not s["visible"])
        self.assertEqual(len(blank["renderings"]["player"]["frames"]), 3)
        self.assertEqual(len(set(blank["renderings"]["player"]["frames"])), 1)

    def test_source_and_definition_hashes_are_required_before_publication(self):
        self.registry["source_report_sha256"] = "0" * 64
        self.definitions.write_bytes(json_bytes(self.registry))
        with self.assertRaises(ValueError):
            self.run_extract()
        self.assertFalse(self.out.exists())

    def test_definition_crlf_has_the_same_canonical_hash_and_outputs(self):
        first = self.run_extract()["definitions_canonical_sha256"]
        self.out = self.root / "crlf"
        self.definitions.write_bytes(self.definitions.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.run_extract()["definitions_canonical_sha256"], first)

    def test_altered_raw_or_palette_bytes_fail_even_after_resealing_the_container(self):
        palette = next((self.source / "paletas-origen").glob("*.bin"))
        palette.write_bytes(b"\x42" * 32)
        self.repin()
        with self.assertRaises(ValueError):
            self.run_extract()
        self.assertFalse(self.out.exists())

    def test_air_decoded_hash_is_compared_with_actual_output(self):
        report = json.loads((self.source / "revision.json").read_bytes())
        report["results"][1]["entries"][1]["air_decoded_sha256"] = "0" * 64
        self.repin(report)
        with self.assertRaises(ValueError):
            self.run_extract()
        self.assertFalse(self.out.exists())

    def test_ids_and_size_metadata_cannot_relabel_a_sheet(self):
        report = json.loads((self.source / "revision.json").read_bytes())
        report["results"][0]["entries"][1]["sprite_id"] = 2
        self.repin(report)
        with self.assertRaises(ValueError):
            self.run_extract()

    def test_native_palette_loader_and_literals_are_bound_to_the_definition(self):
        report = json.loads((self.source / "revision.json").read_bytes())
        path = self.source / report["results"][0]["palette_load_context"]["file"]
        raw = bytearray(path.read_bytes())
        raw[0xF8 + 0x28] ^= 1
        path.write_bytes(raw)
        self.repin()
        with self.assertRaises(ValueError):
            self.run_extract()

    def test_no_overwrite_or_nested_output(self):
        self.out.mkdir()
        with self.assertRaises(ValueError):
            self.run_extract()
        with self.assertRaises(ValueError):
            catalog.extract_sprites(self.source, self.source / "nested", self.definitions)

    def test_zip_input_and_repacking_require_no_rom_or_original_packet(self):
        archive = self.root / "source.zip"
        review.pack_variants(self.source, archive, state_name=review.STATE)
        catalog.extract_sprites(archive, self.out, self.definitions)
        archive.unlink()
        output = self.root / "catalogo.zip"
        result = review.pack_variants(self.out, output, state_name=catalog.STATE)
        self.assertTrue(result["crc_verified"])
        with ZipFile(output) as z:
            self.assertIsNone(z.testzip())
            self.assertTrue(all("\\" not in name for name in z.namelist()))
            self.assertEqual(json.loads(z.read("resumen.json"))["sheet_occurrences"], 6)

    def test_cli_is_json_and_refuses_zip_inside_the_source(self):
        args = [
            "extract",
            "--review",
            str(self.source),
            "--out",
            str(self.out),
            "--definitions",
            str(self.definitions),
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(catalog.main(args + ["--zip", str(self.source / "new.zip")]), 2)
        self.assertFalse(self.out.exists())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(catalog.main(args + ["--zip", str(self.root / "ok.zip")]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "completed")


if __name__ == "__main__":
    unittest.main()
