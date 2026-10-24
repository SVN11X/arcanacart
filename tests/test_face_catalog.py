"""Consolidate real synthetic extraction bundles and preserve source provenance."""

import contextlib
import importlib
import io
import json
import struct
import subprocess
import sys
import unittest
import zlib
from unittest.mock import patch
from zipfile import ZipFile

import test_face_batch as fixtures

catalog_tool = importlib.import_module("consolidar_retratos")
gallery = importlib.import_module("catalogo_retratos_galeria")


class FaceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BatchTests(
            "test_actual_renderer_exports_raw_lz10_real_palette_and_valid_links"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.out = self.fixture.root / "consolidado"

    def extract(self, **kwargs):
        self.assertEqual(self.fixture.run_batch(**kwargs)[0], 0)
        return self.fixture.out

    def consolidate(self, source=None, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return catalog_tool.run(source or self.fixture.out, self.out, **kwargs)

    def zip_input(self, windows_names=False):
        target = self.fixture.root / "entrada.zip"
        with ZipFile(target, "w") as z:
            for path in self.fixture.out.rglob("*"):
                if path.is_file():
                    name = path.relative_to(self.fixture.out).as_posix()
                    z.write(path, name.replace("/", "\\") if windows_names else name)
        return target

    def test_deduplicates_pngs_and_retains_all_origins_and_source_bytes(self):
        self.fixture.add_job()
        source = self.extract()
        original = {
            p: (fixtures.batch.file_hash(p), p.stat().st_mtime_ns) for p in source.rglob("*") if p.is_file()
        }
        result = self.consolidate(create_zip=True)
        self.assertEqual(
            (result["component_occurrences"], result["unique_images"], result["visible_images"]), (6, 4, 4)
        )
        self.assertEqual(result["unique_palettes"], 1)
        catalog = fixtures.batch.small_json(self.out / "catalogo.json")
        origins = [o for a in catalog["images"] for o in a["origins"]]
        self.assertEqual(len(origins), 6)
        self.assertEqual({o["variant_id"] for o in origins}, {"fe8-001", "fe8-002"})
        for asset in catalog["images"]:
            self.assertEqual(fixtures.batch.file_hash(self.out / asset["file"]), asset["png_sha256"])
        for path, identity in original.items():
            self.assertEqual((fixtures.batch.file_hash(path), path.stat().st_mtime_ns), identity)
        state = fixtures.batch.small_json(self.out / "catalog-state.json")
        for relative, digest in state["artifacts"].items():
            self.assertEqual(fixtures.batch.file_hash(self.out / relative), digest)
        with ZipFile(result["archive"]) as z:
            self.assertIsNone(z.testzip())
            self.assertFalse(any(n.endswith(".gba") or "\\" in n for n in z.namelist()))

    def test_zip_with_windows_member_separators_is_read_without_unpacking(self):
        self.extract()
        source = self.zip_input(windows_names=True)
        result = self.consolidate(source)
        self.assertEqual((result["unique_images"], result["component_occurrences"]), (3, 3))

    def test_transparent_png_is_retained_and_classified(self):
        original_make = fixtures.make_rom

        def empty_portrait(*args, **kwargs):
            rom, air = original_make(*args, **kwargs)
            data = bytearray(rom)
            data[0x7004:0x8004] = bytes(4096)
            air["rom"]["sha256"] = fixtures.batch.check.digest(data)
            return bytes(data), air

        self.fixture.plan["jobs"].clear()
        with patch.object(fixtures, "make_rom", side_effect=empty_portrait):
            self.fixture.add_job()
        self.extract()
        result = self.consolidate()
        self.assertEqual(
            (result["transparent_images"], result["transparent_occurrences"], result["visible_images"]),
            (1, 1, 2),
        )
        catalog = fixtures.batch.small_json(self.out / "catalogo.json")
        blank = next(a for a in catalog["images"] if not a["visible"])
        self.assertTrue((self.out / blank["file"]).is_file())

    def test_known_empty_table_slot_accepts_underlying_partial_summary(self):
        self.fixture.plan["jobs"].clear()
        self.fixture.add_job(empty=True)
        self.extract()
        self.assertEqual(self.consolidate()["component_occurrences"], 3)

    def test_corrupt_component_png_fails_before_publishing(self):
        source = self.extract()
        (source / "fe8-001/galeria/retratos/face-001.png").write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.consolidate()
        self.assertFalse(self.out.exists())

    def test_incomplete_batch_is_rejected(self):
        source = self.extract()
        path = source / "resumen.json"
        document = json.loads(path.read_bytes())
        document["run_status"] = "interrupted"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "completo"):
            self.consolidate()
        self.assertFalse(self.out.exists())

    def test_source_output_overlap_and_existing_destination_are_rejected(self):
        source = self.extract()
        with self.assertRaisesRegex(ValueError, "separada"):
            catalog_tool.run(source, source / "nuevo")
        self.out.mkdir()
        (self.out / "user.txt").write_text("keep")
        with self.assertRaises(FileExistsError):
            self.consolidate()
        self.assertEqual((self.out / "user.txt").read_text(), "keep")

    def test_dry_run_writes_no_catalog(self):
        self.extract()
        result = self.consolidate(dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["unique_images"], 3)
        self.assertFalse(self.out.exists())

    def test_failed_write_removes_staging_and_preserves_original(self):
        source = self.extract()
        original = fixtures.batch.file_hash(source / "run-state.json")
        with patch.object(catalog_tool.check, "atomic_bytes", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.consolidate()
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.fixture.root.glob(".catalogo-retratos-*")))
        self.assertEqual(fixtures.batch.file_hash(source / "run-state.json"), original)

    def test_zip_traversal_paths_are_rejected_without_unpacking(self):
        self.extract()
        source = self.zip_input()
        with ZipFile(source, "a") as z:
            z.writestr("../outside.txt", "bad")
        with self.assertRaisesRegex(ValueError, "Ruta"):
            self.consolidate(source)
        self.assertFalse(self.out.exists())

    def test_root_plan_crlf_conversion_keeps_plan_identity(self):
        source = self.extract()
        path = source / "planes-usados.json"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.consolidate()["unique_images"], 3)

    def test_cli_works_from_another_directory_and_generates_zip(self):
        source = self.extract()
        result = subprocess.run(
            [
                sys.executable,
                str(fixtures.PACKAGE / "consolidar_retratos.py"),
                "--repo",
                str(fixtures.ROOT),
                "--input",
                str(source),
                "--out",
                str(self.out),
                "--crear-zip",
            ],
            cwd=self.fixture.root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.out.with_name(self.out.name + ".zip").is_file())

    def test_json_data_cannot_close_its_script_element(self):
        self.extract()
        self.consolidate()
        catalog = fixtures.batch.small_json(self.out / "catalogo.json")
        injected = '</script><script>window.pwned=true</script><img onerror="bad">'
        catalog["images"][0]["origins"][0]["variant"] = injected
        page = gallery.render_gallery(catalog)
        self.assertNotIn(injected, page)
        payload = page.split('id="catalog-data">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(payload)["images"][0]["origins"][0]["variant"], injected)

    def test_png_validation_checks_crc_transparency_and_bounds(self):
        raw = bytes([19, 20, 21, 0]) * 4
        png = fixtures.FACES.graphics.png(2, 2, raw)
        self.assertFalse(catalog_tool.png_info(png)["visible"])
        damaged = bytearray(png)
        damaged[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            catalog_tool.png_info(bytes(damaged))
        header = struct.pack(">IIBBBBB", 1_048_577, 1, 8, 6, 0, 0, 0)
        chunk = b"IHDR" + header
        oversized = (
            b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + chunk + struct.pack(">I", zlib.crc32(chunk))
        )
        with self.assertRaisesRegex(ValueError, "Dimensiones"):
            catalog_tool.png_info(oversized)

    def test_patch_release_compatibility_keeps_existing_plan_identity(self):
        before = fixtures.batch.plan_text_hash(self.fixture.plan_path)
        self.extract()
        with patch.object(
            fixtures.FACES, "reconstruct_faces", wraps=fixtures.FACES.reconstruct_faces
        ) as renderer:
            self.assertEqual(self.fixture.run_batch(resume=True)[0], 0)
            renderer.assert_not_called()
        self.assertEqual(before, fixtures.batch.plan_text_hash(self.fixture.plan_path))
        self.assertTrue(fixtures.batch.compatible_version("0.6.3", "0.6.2"))
        self.assertFalse(fixtures.batch.compatible_version("0.6.1", "0.6.2"))
        self.assertFalse(fixtures.batch.compatible_version("0.7.0", "0.6.2"))


if __name__ == "__main__":
    unittest.main()
