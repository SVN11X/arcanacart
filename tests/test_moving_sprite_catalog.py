"""Hash-bound movement resource export, palette reuse and complete raw tile previews."""

import contextlib
import copy
import io
import json
import struct
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import test_moving_sprite_review as review_fixtures
from test_map_sprite_catalog import png_pixels
from test_moving_sprite_review import literal_lz

from arcanacart import moving_sprite_catalog as mc
from arcanacart import moving_sprite_review as mr
from arcanacart.core.io import digest, json_bytes
from arcanacart.icon_variants import _publish, _sealed, pack_variants


def make_sources(owner):
    fixture = review_fixtures.MovingSpriteReview("runTest")
    fixture.setUp()
    owner.addCleanup(fixture.doCleanups)
    root = fixture.root
    # A partial final tile row must survive intact; preview padding has no raw bytes.
    raw = bytes(range(256)) * 30 + bytes(range(32))
    sheet = literal_lz(raw)
    for path in (fixture.base_path, fixture.rom):
        data = bytearray(path.read_bytes())
        data[0x2000 : 0x2000 + len(sheet)] = sheet
        path.write_bytes(data)
    fixture.sheet, fixture.raw = sheet, raw
    fixture.profile["rom_sha256"] = digest(fixture.base_path.read_bytes())
    fixture.save_variant(fixture.rom.read_bytes())
    fixture.review(slots=3)
    source = fixture.out
    files = _sealed(source, state_name=mr.STATE)
    report = json.loads(files["revision.json"])
    specs, references = [], []
    colors = {}
    for index, role in enumerate(mc.ROLE_LABELS):
        palette = struct.pack("<16H", 0, *[(n + index * 2) | ((n + index) << 5) for n in range(1, 16)])
        colors[role] = palette
    palette_payloads = {"paletas/" + digest(b) + ".bin": b for b in colors.values()}
    for row in report["results"]:
        table = row["tables"][0]
        spec = {k: row.get(k) for k in ("variant_id", "variant", "game", "rom_sha256", "air_sha256")}
        spec.update(
            first_id=1,
            last_id=2,
            table_offset=table["table_offset"],
            table_window_sha256=digest(files[table["table_window_file"]]),
            table_prefix_sha256=digest(files[table["table_window_file"]][:16]),
            accesses=[],
        )
        for pointer in row["access_pointers"]:
            canonical = bytearray(files[pointer["context_file"]])
            for other in row["access_pointers"]:
                position = other["location"] - pointer["context_offset"]
                if 0 <= position <= len(canonical) - 4:
                    canonical[position : position + 4] = bytes(4)
            spec["accesses"].append(
                {
                    "location": pointer["location"],
                    "context_offset": pointer["context_offset"],
                    "context_sha256": pointer["context_sha256"],
                    "context_except_table_literals_sha256": digest(canonical),
                }
            )
        specs.append(spec)
        references.append(
            {
                **{k: row.get(k) for k in ("variant_id", "variant", "game", "rom_sha256", "air_sha256")},
                "palettes": {role: digest(b) for role, b in colors.items()},
                "palette_offsets": {role: 0x6000 + i * 32 for i, role in enumerate(colors)},
            }
        )
    palette_summary = {"format": mc.STANDING_FORMAT, "status": "completed"}
    palette_payloads.update(
        {
            "resumen.json": json_bytes(palette_summary),
            "catalogo.json": json_bytes({"summary": palette_summary, "profiles": references}),
        }
    )
    palettes = root / "paletas-previas"
    _publish(palettes, palette_payloads, state_name=mc.STANDING_STATE)
    registry = {
        "format": "arcanacart-moving-resource-definitions-1",
        "capacity_confirmed": False,
        "runtime_appearance_verified": False,
        "source_report_sha256": digest(files["revision.json"]),
        "source_state_sha256": digest(files[mr.STATE]),
        "plan_canonical_sha256": report["plan_canonical_sha256"],
        "palette_source": {
            "summary_sha256": digest(palette_payloads["resumen.json"]),
            "state_sha256": digest((palettes / mc.STANDING_STATE).read_bytes()),
        },
        "definitions": specs,
    }
    definitions = root / "definiciones.json"
    definitions.write_bytes(json_bytes(registry))
    return root, source, palettes, definitions, raw, colors


class MovingSpriteCatalog(unittest.TestCase):
    def setUp(self):
        self.root, self.source, self.palettes, self.definitions, self.raw, self.colors = make_sources(self)
        self.out = self.root / "catalogo"

    def extract(self):
        return mc.extract_movement(self.source, self.palettes, self.out, self.definitions)

    def test_exact_assets_ap_relationships_and_every_occurrence_are_retained(self):
        summary = self.extract()
        self.assertEqual(
            (summary["occurrences"], summary["unique_raw_sheets"], summary["unique_ap_snapshots"]), (4, 1, 1)
        )
        self.assertEqual(summary["unique_resources"], 1)
        self.assertEqual(summary["unique_preview_pngs"], 7)
        data = json.loads((self.out / "catalogo.json").read_bytes())
        self.assertEqual(
            {(o["variant_id"], o["class_id"]) for o in data["occurrences"]},
            {("fe8-base", 1), ("fe8-base", 2), ("fe8-001", 1), ("fe8-001", 2)},
        )
        for o in data["occurrences"]:
            self.assertEqual((self.out / o["raw_file"]).read_bytes(), self.raw)
            self.assertEqual(digest((self.out / o["compressed_file"]).read_bytes()), o["stored_sha256"])
            self.assertEqual(digest((self.out / o["definition"]).read_bytes()), o["definition_sha256"])
        resource = data["resources"][0]
        self.assertEqual((resource["ap_frames"], resource["ap_animations"]), (2, 5))
        self.assertEqual(digest((self.out / resource["ap_file"]).read_bytes()), resource["ap_sha256"])
        self.assertEqual(resource["preview_kind"], "4bpp-tile-sheet")

    def test_all_tile_pixels_and_transparent_padding_match_independent_indexing(self):
        self.extract()
        data = json.loads((self.out / "catalogo.json").read_bytes())
        preview = next(iter(data["previews"].values()))
        self.assertEqual((preview["tile_count"], preview["padding_tiles"], preview["height"]), (241, 3, 488))
        for role, rendering in preview["renderings"].items():
            asset = data["images"][rendering["png_sha256"]]
            w, h, pixels = png_pixels((self.out / asset["file"]).read_bytes())
            self.assertEqual((w, h), (32, 488))
            expected = bytearray(w * h * 4)
            for tile in range(241):
                for y in range(8):
                    for x in range(8):
                        value = self.raw[tile * 32 + y * 4 + x // 2]
                        index = (value >> ((x % 2) * 4)) & 15
                        color = struct.unpack_from("<H", self.colors[role], index * 2)[0]
                        rgba = bytes(
                            (
                                (color & 31) * 255 // 31,
                                ((color >> 5) & 31) * 255 // 31,
                                ((color >> 10) & 31) * 255 // 31,
                                255 if index else 0,
                            )
                        )
                        pos = (((tile // 4) * 8 + y) * w + (tile % 4) * 8 + x) * 4
                        expected[pos : pos + 4] = rgba
            self.assertEqual(pixels, expected)

    def test_no_rom_air_scanner_or_ap_execution_and_inputs_unchanged(self):
        before = {
            p: p.read_bytes()
            for folder in (self.source, self.palettes)
            for p in folder.rglob("*")
            if p.is_file()
        }
        with (
            patch("arcanacart.pipeline.load_rom", side_effect=AssertionError("ROM")),
            patch("arcanacart.pipeline.scan_resources", side_effect=AssertionError("scan")),
        ):
            summary = self.extract()
        for key in (
            "roms_read",
            "air_files_read",
            "rescanned",
            "inputs_modified",
            "runtime_frames_composed",
            "animations_executed",
        ):
            self.assertFalse(summary[key])
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_repository_definition_crlf_keeps_the_same_canonical_identity(self):
        first = self.extract()
        self.out = self.root / "catalogo-crlf"
        self.definitions.write_bytes(self.definitions.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(
            self.extract()["definitions_canonical_sha256"], first["definitions_canonical_sha256"]
        )

    def test_changed_review_or_palette_bytes_fail_before_output_publication(self):
        for folder, name in ((self.source, "revision.json"), (self.palettes, "resumen.json")):
            path = folder / name
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaises(ValueError):
                self.extract()
            self.assertFalse(self.out.exists())
            path.write_bytes(original)

    def test_resealed_source_cannot_change_the_pinned_report(self):
        files = _sealed(self.source, state_name=mr.STATE)
        report = json.loads(files["revision.json"])
        report["results"][1]["rom_sha256"] = "f" * 64
        files.pop(mr.STATE)
        files["revision.json"] = json_bytes(report)
        changed = self.root / "revisada-editada"
        _publish(changed, files, state_name=mr.STATE)
        self.source = changed
        with self.assertRaisesRegex(ValueError, "auditada"):
            self.extract()
        self.assertFalse(self.out.exists())

    def test_explicit_definition_ranges_and_context_hashes_are_enforced(self):
        original = json.loads(self.definitions.read_bytes())
        cases = [
            ("last_id", 3),
            ("first_id", True),
            ("table_prefix_sha256", "f" * 64),
            ("rom_sha256", "e" * 64),
        ]
        for field, value in cases:
            changed = copy.deepcopy(original)
            changed["definitions"][0][field] = value
            self.definitions.write_bytes(json_bytes(changed))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.extract()
            self.assertFalse(self.out.exists())
        original["definitions"][0]["accesses"][0]["context_except_table_literals_sha256"] = "0" * 64
        self.definitions.write_bytes(json_bytes(original))
        with self.assertRaises(ValueError):
            self.extract()

    def test_ap_snapshot_or_air_hash_mismatch_is_rejected_even_with_explicit_source_pin(self):
        files = _sealed(self.source, state_name=mr.STATE)
        report = json.loads(files["revision.json"])
        report["results"][0]["tables"][0]["entries"][0]["air_decoded_sha256"] = "f" * 64
        files.pop(mr.STATE)
        files["revision.json"] = json_bytes(report)
        altered = self.root / "cambio-metadatos"
        _publish(altered, files, state_name=mr.STATE)
        doc = json.loads(self.definitions.read_bytes())
        doc["source_report_sha256"] = digest(files["revision.json"])
        doc["source_state_sha256"] = digest((altered / mr.STATE).read_bytes())
        self.definitions.write_bytes(json_bytes(doc))
        self.source = altered
        with self.assertRaisesRegex(ValueError, "AIR"):
            self.extract()

    def test_flat_and_single_folder_zips_accept_identical_sealed_contents(self):
        self.extract()
        expected = _sealed(self.out, state_name=mc.STATE)
        for source, state, name in (
            (self.source, mr.STATE, "revision"),
            (self.palettes, mc.STANDING_STATE, "paletas"),
        ):
            files = _sealed(source, state_name=state)
            for outer in ("", "carpeta contenedora/"):
                path = self.root / (name + ("-raiz" if outer else "-plano") + ".zip")
                with ZipFile(path, "w") as z:
                    if outer:
                        z.writestr(outer, b"")
                    for key, raw in files.items():
                        z.writestr(outer + key, raw)
                loaded, _ = mc._bundle(path, state)
                self.assertEqual(loaded, files)
        self.out = self.root / "catalogo-zip"
        self.source = self.root / "revision-raiz.zip"
        self.palettes = self.root / "paletas-raiz.zip"
        self.extract()
        actual = _sealed(self.out, state_name=mc.STATE)
        for name in expected:
            if name.startswith(("raw/", "comprimidos/", "ap/", "imagenes/", "paletas/")):
                self.assertEqual(actual[name], expected[name])

    def test_zip_paths_missing_files_and_alias_collisions_are_rejected(self):
        for names in (("../fuera",), ("/fuera",), ("a\\b",), ("a", "A"), ("a/dato", "b/dato")):
            path = self.root / "bad.zip"
            with ZipFile(path, "w") as z:
                for name in names:
                    z.writestr(name, b"x")
            with self.subTest(names=names), self.assertRaises(ValueError):
                mc._bundle(path, mr.STATE)

    def test_manifest_csv_and_portable_zip_cover_every_output(self):
        self.extract()
        files = _sealed(self.out, state_name=mc.STATE)
        import csv

        rows = list(csv.DictReader(io.StringIO(files["ocurrencias.csv"].decode("utf-8-sig"))))
        self.assertEqual(len(rows), 4)
        target = self.root / "catalogo.zip"
        result = pack_variants(self.out, target, state_name=mc.STATE)
        self.assertTrue(result["crc_verified"])
        with ZipFile(target) as z:
            self.assertEqual(set(z.namelist()), set(files))
            self.assertTrue(all("\\" not in name for name in z.namelist()))
        (self.out / "ocurrencias.csv").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            pack_variants(self.out, self.root / "bad-catalogo.zip", state_name=mc.STATE)

    def test_existing_and_nested_outputs_are_rejected(self):
        self.out.mkdir()
        with self.assertRaises(ValueError):
            self.extract()
        self.out = self.source / "subcarpeta"
        with self.assertRaises(ValueError):
            self.extract()
        self.out = self.palettes / "subcarpeta"
        with self.assertRaises(ValueError):
            self.extract()

    def test_cli_json_and_pack_subcommand(self):
        args = [
            "extract",
            "--review",
            str(self.source),
            "--palettes",
            str(self.palettes),
            "--definitions",
            str(self.definitions),
            "--out",
            str(self.out),
        ]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(mc.main(args), 0)
        self.assertEqual(json.loads(stdout.getvalue())["occurrences"], 4)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(
                mc.main(["pack", "--input", str(self.out), "--out", str(self.root / "salida.zip")]), 0
            )
        self.assertTrue(json.loads(stdout.getvalue())["crc_verified"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mc.main(args), 2)


if __name__ == "__main__":
    unittest.main()
