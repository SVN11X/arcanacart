"""Oversized preview regression, legacy bundle reuse and interrupted publication."""

import contextlib
import csv
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
from unittest.mock import patch

from arcanacart import graphics
from arcanacart.cli import main
from arcanacart.core.io import digest, json_bytes
from arcanacart.interpret import BlobReader, bundle_payloads, interpret, render_pages
from arcanacart.preview_repair import LIMIT_ERROR, METADATA, repair_previews


def png_pixels(path):
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    at, data = 8, b""
    while at < len(raw):
        size = struct.unpack_from(">I", raw, at)[0]
        kind, chunk = raw[at + 4 : at + 8], raw[at + 8 : at + 8 + size]
        assert zlib.crc32(kind + chunk) == struct.unpack_from(">I", raw, at + 8 + size)[0]
        if kind == b"IHDR":
            width, height = struct.unpack_from(">II", chunk)
        if kind == b"IDAT":
            data += chunk
        at += 12 + size
    decoded = zlib.decompress(data)
    stride = width * 4 + 1
    assert len(decoded) == stride * height
    assert all(decoded[y * stride] == 0 for y in range(height))
    return width, height, b"".join(decoded[y * stride + 1 : (y + 1) * stride] for y in range(height))


class PreviewRepair(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arcana repair ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.analysis = self.root / "analysis"
        self.blobs = self.analysis / "resources"
        self.blobs.mkdir(parents=True)
        # Exact size reported by the user; each tile carries its absolute index.
        self.large = b"".join(struct.pack("<I", i) * 8 for i in range(34816))
        self.small = bytes([0x21, 0x43, 0x65, 0x87]) * 16
        self.hashes = [digest(self.small), digest(self.large)]
        records = []
        for number, raw in enumerate((self.small, self.large)):
            hash_ = digest(raw)
            (self.blobs / (hash_ + ".bin")).write_bytes(raw)
            records.append(
                {
                    "sha256": hash_,
                    "offset": 256 + number * 32,
                    "compressed_bytes": 16,
                    "decompressed_bytes": len(raw),
                    "compression": "lz10",
                    "references": [],
                }
            )
        self.manifest = {
            "rom": {"sha256": "a" * 64, "size_bytes": 4096},
            "resources": records,
            "scan": {
                "truncated": False,
                "methods": ["lz10"],
                "step": 1,
                "decoded_blocks": 2,
                "unique_outputs": 2,
                "search_progress_percent": 100.0,
            },
        }
        self.source = self.analysis / "air.json"
        self.source.write_bytes(json_bytes(self.manifest))
        self.review = self.analysis / "interpretacion-0.5.0-test"

    def legacy_bundle(self, *, unrelated=False):
        def old_renderer(raw, recipe, reader):
            if len(raw) == 1114112:
                # Reproduce 0.5.0's single-image failure at the real size.
                graphics.tiles(raw, width_tiles=recipe["width_tiles"], bpp=recipe["bpp"])
            yield from render_pages(raw, recipe, reader)

        with patch("arcanacart.interpret.render_pages", side_effect=old_renderer):
            result = interpret(self.source, self.review)
        catalog = json.loads((self.review / "catalog.json").read_bytes())
        rows, summary = catalog["resources"], catalog["summary"]
        self.assertEqual(result["errors"], 1)
        self.assertEqual(rows[1]["preview_error"], LIMIT_ERROR)
        # Remove fields that did not exist in 0.5.0.
        summary.pop("generated_png_files")
        summary.pop("preview_limit_unit")
        summary["tool_version"] = "0.5.0"
        for row in rows:
            row.pop("pages", None)
        if unrelated:
            rows[0].update(preview_status="error", preview_error="Paleta incompatible.")
            summary["generated_previews"] = 0
            summary["errors"] = 2
        template = json.loads((self.review / "recipes.json").read_bytes())
        for name, content in bundle_payloads(summary, rows, template).items():
            (self.review / name).write_bytes(content)
        state = {
            "status": "partial",
            "artifacts": {
                p.relative_to(self.review).as_posix(): digest(p.read_bytes())
                for p in self.review.rglob("*")
                if p.is_file() and p.name != "interpret-state.json"
            },
        }
        (self.review / "interpret-state.json").write_bytes(json_bytes(state))
        return {name: (self.review / name).read_bytes() for name in METADATA}

    def test_real_size_pages_cover_every_tile_and_png_pixel(self):
        result = interpret(self.source, self.review)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["generated_previews"], 2)
        self.assertEqual(result["generated_png_files"], 18)
        self.assertEqual(result["rendered_pixels"], 2228224 + 128)
        rows = json.loads((self.review / "catalog.json").read_bytes())["resources"]
        self.assertEqual(len(rows[1]["pages"]), 17)
        next_tile = 0
        for page in rows[1]["pages"]:
            self.assertEqual(page["first_tile"], next_tile)
            self.assertEqual(page["byte_offset"], next_tile * 32)
            self.assertEqual(page["size_bytes"], page["tile_count"] * 32)
            width, height, rgba = png_pixels(self.review / page["png"])
            self.assertEqual((width, height), (128, 1024))
            self.assertLessEqual(width * height, 1048576)
            for tile in range(page["tile_count"]):
                # Independently check the first pixel of EVERY tile, across page boundaries.
                pos = ((tile // 16) * 8 * width + (tile % 16) * 8) * 4
                value = ((next_tile + tile) & 15) * 17
                self.assertEqual(rgba[pos : pos + 4], bytes([value, value, value, 255]))
            next_tile += page["tile_count"]
        self.assertEqual(next_tile, 34816)
        self.assertEqual(result["identified_by_user_review"], 0)
        self.assertIn("Página de este bloque", (self.review / "index.html").read_text())

    def test_repair_reads_only_failed_blob_and_retains_good_png_and_recipes(self):
        self.legacy_bundle()
        good = self.review / "png" / (self.hashes[0] + ".png")
        old_png, old_mtime = good.read_bytes(), good.stat().st_mtime_ns
        old_recipes = (self.review / "recipes.json").read_bytes()
        source_bytes = self.source.read_bytes()
        calls = []
        read = BlobReader.read

        def track(reader, hash_):
            calls.append(hash_)
            return read(reader, hash_)

        with patch.object(BlobReader, "read", track):
            result = repair_previews(self.source, self.review)
        self.assertEqual(calls, [self.hashes[1]])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["repair"]["new_png_files"], 17)
        self.assertEqual(result["repair"]["repaired_blobs"], 1)
        self.assertEqual(result["generated_png_files"], 18)
        self.assertEqual(result["pending_interpretation"], 2)
        self.assertEqual(result["identified_by_user_review"], 0)
        self.assertEqual((good.read_bytes(), good.stat().st_mtime_ns), (old_png, old_mtime))
        self.assertEqual((self.review / "recipes.json").read_bytes(), old_recipes)
        self.assertEqual(self.source.read_bytes(), source_bytes)
        self.assertTrue(Path(result["repair"]["backup"]).is_dir())
        current = {name: (self.review / name).read_bytes() for name in METADATA}
        with patch.object(BlobReader, "read", side_effect=AssertionError("Must not reread blobs")):
            repeat = repair_previews(self.source, self.review)
        self.assertEqual(repeat["repair"]["repaired_blobs"], 0)
        self.assertEqual(repeat["repair"]["eligible_blobs"], 0)
        self.assertEqual({name: (self.review / name).read_bytes() for name in METADATA}, current)

    def test_unrelated_errors_are_retained_and_status_stays_partial(self):
        self.legacy_bundle(unrelated=True)
        result = repair_previews(self.source, self.review)
        self.assertEqual(result["repair"]["repaired_blobs"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["status"], "partial")
        rows = json.loads((self.review / "catalog.json").read_bytes())["resources"]
        self.assertEqual(rows[0]["preview_error"], "Paleta incompatible.")
        self.assertNotIn("preview_error", rows[1])

    def test_whole_block_budgets_and_dry_run(self):
        before = self.legacy_bundle()
        planned = repair_previews(self.source, self.review, dry_run=True)
        self.assertEqual(planned["planned_png_files"], 17)
        self.assertEqual(planned["planned_pixels"], 2228224)
        self.assertEqual(planned["planned_blob_bytes"], 1114112)
        self.assertEqual({name: (self.review / name).read_bytes() for name in METADATA}, before)
        for kwargs in ({"max_previews": 16}, {"pixel_budget": 2228223}):
            result = repair_previews(self.source, self.review, **kwargs)
            self.assertEqual(result["repair"]["deferred_blobs"], 1)
            self.assertEqual(result["repair"]["new_png_files"], 0)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(list((self.review / "png").glob("*-p*.png"))), 0)
        self.assertEqual(repair_previews(self.source, self.review)["status"], "completed")

    def test_new_interpretation_does_not_publish_incomplete_block(self):
        result = interpret(self.source, self.review, max_previews=17)
        self.assertEqual(result["generated_png_files"], 1)
        self.assertEqual(result["skipped_previews"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(list((self.review / "png").iterdir())), 1)

    def test_page_failure_discards_pages_and_allows_retry(self):
        self.legacy_bundle()
        original = graphics.png
        count = 0

        def failure(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("Synthetic full disk")
            return original(*args)

        with patch("arcanacart.graphics.png", side_effect=failure):
            result = repair_previews(self.source, self.review)
        self.assertEqual(result["repair"]["new_png_files"], 0)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(len(list(self.review.rglob("*-p*.png"))), 0)
        self.assertEqual(repair_previews(self.source, self.review)["status"], "completed")

    def test_metadata_failure_restores_original_bundle_then_retry_works(self):
        before = self.legacy_bundle()
        from arcanacart.core.io import atomic_write

        failed = False

        def failure(path, data, **kwargs):
            nonlocal failed
            if Path(path) == self.review / "summary.json" and not failed:
                failed = True
                raise OSError("Synthetic interrupted metadata publication")
            return atomic_write(path, data, **kwargs)

        with patch("arcanacart.preview_repair.atomic_write", side_effect=failure):
            with self.assertRaises(OSError):
                repair_previews(self.source, self.review)
        self.assertEqual({name: (self.review / name).read_bytes() for name in METADATA}, before)
        self.assertEqual(len(list((self.review / "png").glob("*-p*.png"))), 0)
        self.assertEqual(
            json.loads((self.review / "preview-repair.json").read_bytes())["status"], "rolled-back"
        )
        self.assertEqual(repair_previews(self.source, self.review)["status"], "completed")

    def test_interrupted_commit_is_recovered_on_next_execution(self):
        self.legacy_bundle()
        repair_previews(self.source, self.review)
        journal = json.loads((self.review / "preview-repair.json").read_bytes())
        journal["status"] = "committing"
        (self.review / "preview-repair.json").write_bytes(json_bytes(journal))
        with self.assertRaises(ValueError):
            repair_previews(self.source, self.review, dry_run=True)
        result = repair_previews(self.source, self.review)
        self.assertEqual(result["repair"]["repaired_blobs"], 1)
        self.assertEqual(result["status"], "completed")

    def test_source_and_catalog_changes_are_rejected(self):
        self.legacy_bundle()
        old_source = self.source.read_bytes()
        self.source.write_bytes(old_source + b"\n")
        with self.assertRaises(ValueError):
            repair_previews(self.source, self.review)
        self.source.write_bytes(old_source)
        catalog = self.review / "catalog.json"
        catalog.write_bytes(catalog.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            repair_previews(self.source, self.review)
        self.assertEqual(len(list((self.review / "png").glob("*-p*.png"))), 0)

    def test_changed_blob_stays_pending_with_diagnostic(self):
        self.legacy_bundle()
        (self.blobs / (self.hashes[1] + ".bin")).write_bytes(b"x" * len(self.large))
        result = repair_previews(self.source, self.review)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["repair"]["repaired_blobs"], 0)
        row = json.loads((self.review / "catalog.json").read_bytes())["resources"][1]
        self.assertIn("hash", row["repair_error"])
        self.assertEqual(row["preview_error"], LIMIT_ERROR)

    def test_cli_plan_is_json_and_leaves_metadata_intact(self):
        before = self.legacy_bundle()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(
                ["repair-previews", "--input", str(self.source), "--review", str(self.review), "--dry-run"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["planned_png_files"], 17)
        self.assertEqual({name: (self.review / name).read_bytes() for name in METADATA}, before)

    @unittest.skipUnless(os.name == "nt", "Requiere PowerShell en Windows.")
    def test_windows_launcher_repairs_existing_summary_csv(self):
        self.legacy_bundle()
        shell = shutil.which("pwsh") or str(
            Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        csv_path = self.root / "resumen anterior.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "Juego",
                    "Variante",
                    "Estado",
                    "Galeria",
                    "Candidatos",
                    "BloquesUnicos",
                    "PNG",
                    "Aceptados",
                    "Pendientes",
                    "Detalle",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Juego": "fe7",
                    "Variante": "base",
                    "Estado": "partial",
                    "Galeria": str(self.review / "index.html"),
                    "Candidatos": 2,
                    "BloquesUnicos": 2,
                    "PNG": 1,
                    "Aceptados": 0,
                    "Pendientes": 2,
                    "Detalle": "",
                }
            )
        script = Path(__file__).resolve().parents[1] / "scripts/windows/Reparar-Previsualizaciones.ps1"
        proc = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ResumenCsv",
                str(csv_path),
                "-PythonExe",
                sys.executable,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        reports = list(self.root.glob("resumen-reparacion-*.csv"))
        self.assertEqual(len(reports), 1)
        with reports[0].open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(
            (row["Estado"], row["Reparados"], row["PNGNuevos"], row["PNG"]), ("completed", "1", "17", "18")
        )


class PagePlans(unittest.TestCase):
    def test_8bpp_and_narrow_or_wide_pages_are_lossless_in_length(self):
        for bpp in (4, 8):
            for columns in (1, 7, 16, 128):
                plan = graphics.tile_page_plan(1114112, bpp=bpp, width_tiles=columns)
                cursor = 0
                for page in plan:
                    self.assertEqual(page["byte_offset"], cursor)
                    self.assertLessEqual(page["width"] * page["height"], 1048576)
                    self.assertEqual(page["size_bytes"] % (8 * bpp), 0)
                    cursor += page["size_bytes"]
                self.assertEqual(cursor, 1114112)

    def test_small_tall_images_keep_their_original_dimensions(self):
        plan = graphics.tile_page_plan(32768, width_tiles=1)
        self.assertEqual(len(plan), 1)
        self.assertEqual((plan[0]["width"], plan[0]["height"]), (8, 8192))
