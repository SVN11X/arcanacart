import contextlib
import importlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "scripts/variantes"
sys.path.insert(0, str(PACKAGE))
batch = importlib.import_module("extraer_retratos_variantes")
REPO = ROOT
API = batch.check.load_api(REPO)
FACES = importlib.import_module("arcanacart.faces")


def literal(raw):
    out = bytearray(b"\x10" + len(raw).to_bytes(3, "little"))
    for offset in range(0, len(raw), 8):
        out.append(0)
        out.extend(raw[offset : offset + 8])
    return bytes(out)


def make_rom(table, card_byte=0x33):
    rom = bytearray(0x20000)
    rom[0xAC:0xB0] = b"BE8E"
    rom[0x5514:0x5524] = bytes(range(16))
    struct.pack_into("<I", rom, 0x5524, 0x08000000 + table)
    palette = bytes(range(32))
    rom[0x6000:0x6020] = palette
    raw = b"\x11" * 4096
    rom[0x7000 : 0x7000 + 4100] = b"\x00" + (4100).to_bytes(3, "little") + raw
    blocks = [(0x9000, b"\x22" * 512, table + 28 + 4), (0xA000, bytes([card_byte]) * 2880, table + 56 + 16)]
    resources = []
    for offset, payload, location in blocks:
        encoded = literal(payload)
        rom[offset : offset + len(encoded)] = encoded
        resources.append(
            {
                "offset": offset,
                "sha256": batch.check.digest(payload),
                "decompressed_bytes": len(payload),
                "compressed_bytes": len(encoded),
                "compression": "lz10",
                "encoded_sha256": batch.check.digest(encoded),
                "references": [{"location": location, "target_offset": offset}],
            }
        )
    struct.pack_into("<5I", rom, table + 28, 0x08007000, 0x08009000, 0x08006000, 0, 0)
    struct.pack_into("<5I", rom, table + 56, 0, 0, 0x08006000, 0, 0x0800A000)
    air = {
        "rom": {"sha256": batch.check.digest(rom), "size_bytes": len(rom), "game_code": "BE8E"},
        "resources": resources,
        "scan": {
            "truncated": False,
            "step": 1,
            "methods": ["lz10"],
            "decoded_blocks": 2,
            "unique_outputs": 2,
        },
    }
    return bytes(rom), air


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if tag == "a" and key == "href":
                self.links.append(value)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.base, self.base_air = make_rom(0x10000)
        self.base_path = self.inputs / "base.gba"
        self.base_path.write_bytes(self.base)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.plan_path = self.tools / "planes.json"
        self.out = self.root / "outputs/retratos-variantes-prueba"
        self.plan = {
            "format": "arcanacart-bounded-face-batch-1",
            "plan_version": 1,
            "required_tool_version": "0.6.2",
            "default_output_parent": str(self.out.parent),
            "bases": {"fe8": {"rom_path": str(self.base_path), "rom_sha256": batch.check.digest(self.base)}},
            "scope": "Rango de prueba; tamaño total reservado no confirmado.",
            "jobs": [],
            "expected_total_pngs": 0,
            "expected_total_counts": {},
        }
        self.add_job()

    def tearDown(self):
        self.temporary.cleanup()

    def save_plan(self):
        counts = {k: sum(j["expected_counts"][k] for j in self.plan["jobs"]) for k in batch.KINDS}
        self.plan.update(expected_total_counts=counts, expected_total_pngs=sum(counts.values()))
        self.plan_path.write_text(json.dumps(self.plan))

    def add_job(self, card_size=2880, empty=False, missing_compressed=False, bad_palette=False):
        n = len(self.plan["jobs"]) + 1
        rom_bytes, air = make_rom(0x11000, card_byte=0x40 + n)
        rom = bytearray(rom_bytes)
        card = air["resources"][1]
        card_payload = bytes([0x40 + n]) * card_size
        encoded = literal(card_payload)
        rom[0xA000 : 0xA000 + len(encoded)] = encoded
        card.update(
            sha256=batch.check.digest(card_payload),
            decompressed_bytes=card_size,
            compressed_bytes=len(encoded),
            encoded_sha256=batch.check.digest(encoded),
        )
        if bad_palette:
            struct.pack_into("<I", rom, 0x11000 + 28 + 8, 0x6000)
        if missing_compressed:
            air["resources"].pop(0)
            air["scan"].update(decoded_blocks=1, unique_outputs=1)
        air["rom"].update(sha256=batch.check.digest(rom))
        job_dir = self.inputs / f"job-{n}"
        job_dir.mkdir(exist_ok=True)
        air_path = job_dir / "air.json"
        air_path.write_text(json.dumps(air))
        rom_path = job_dir / "rom.gba"
        rom_path.write_bytes(rom)
        resources = job_dir / "resources"
        resources.mkdir(exist_ok=True)
        for record in air["resources"]:
            payload, consumed = API.decoders[rom[record["offset"]]][1](rom, record["offset"], 8192, None)
            (resources / (record["sha256"] + ".bin")).write_bytes(payload)
        count = 4 if empty else 3
        layout = dict(
            FACES.FE8_LAYOUT, rom_sha256=air["rom"]["sha256"], table_offset=0x11000, entry_count=count
        )
        layout_path = self.tools / f"fe8-{n:03}.json"
        layout_path.write_text(json.dumps(layout))
        job = {
            "id": f"fe8-{n:03}",
            "game": "fe8",
            "variant": f"{n:03}-prueba",
            "air_path": str(air_path),
            "rom_path": str(rom_path),
            "rom_sha256": air["rom"]["sha256"],
            "air_sha256": batch.file_hash(air_path),
            "layout_file": layout_path.name,
            "layout_sha256": batch.file_hash(layout_path),
            "first_id": 1,
            "last_id": count - 1,
            "expected_empty_ids": [3] if empty else [],
            "expected_counts": {"portrait": 1, "miniature": 1, "classcard": 1},
            "access_code_hex": bytes(range(16)).hex(),
            "table_bytes_sha256": batch.check.digest(rom[0x11000 + 28 : 0x11000 + count * 28]),
        }
        self.plan["jobs"].append(job)
        self.save_plan()
        return job

    def run_batch(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return batch.run(REPO, self.plan_path, self.out, **kwargs)

    def test_actual_renderer_exports_raw_lz10_real_palette_and_valid_links(self):
        snapshot = {
            p: (batch.file_hash(p), p.stat().st_mtime_ns) for p in self.inputs.rglob("*") if p.is_file()
        }
        code, archive = self.run_batch()
        self.assertEqual(code, 0)
        summary = batch.small_json(self.out / "resumen.json")
        self.assertEqual(summary["generated_component_pngs"], 3)
        probe = batch.small_json(self.out / "fe8-001/validacion.json")
        self.assertTrue(probe["range_components_validated"])
        self.assertFalse(probe["allocated_table_size_confirmed"])
        for p, identity in snapshot.items():
            self.assertEqual((batch.file_hash(p), p.stat().st_mtime_ns), identity)
        with ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            self.assertFalse(
                any(n.endswith(".gba") or n.endswith("air.json") or ".lock" in n for n in z.namelist())
            )
            self.assertIn("fe8-001/galeria/retratos/face-001.png", z.namelist())
        links = Links()
        links.feed((self.out / "index.html").read_text())
        self.assertGreaterEqual(len(links.links), 3)
        for name in links.links:
            self.assertTrue((self.out / name).is_file(), name)

    def test_3200_byte_classcard_is_rendered_as_80_by_80(self):
        self.plan["jobs"].clear()
        self.add_job(card_size=3200)
        code, archive = self.run_batch()
        self.assertEqual(code, 0)
        png = (self.out / "fe8-001/galeria/tarjetas-clase/face-002.png").read_bytes()
        self.assertEqual(struct.unpack(">II", png[16:24]), (80, 80))

    def test_known_empty_slot_completes_range_and_preserves_partial_raw_summary(self):
        self.plan["jobs"].clear()
        self.add_job(empty=True)
        self.assertEqual(self.run_batch()[0], 0)
        report = batch.small_json(self.out / "fe8-001/resultado.json")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["summary"]["status"], "partial")
        self.assertEqual(report["summary"]["entries_without_observed_graphics"], [3])
        self.assertIsNotNone(
            batch.cached_result(
                self.out,
                self.plan["jobs"][0],
                batch.small_json(self.out / "run-state.json")["jobs"]["fe8-001"],
                batch.file_hash(self.plan_path),
            )
        )

    def test_resume_verifies_outputs_and_does_not_repeat_renderer(self):
        self.run_batch()
        original = (self.out / "fe8-001/resultado.json").read_bytes()
        with patch.object(FACES, "reconstruct_faces", wraps=FACES.reconstruct_faces) as renderer:
            self.assertEqual(self.run_batch(resume=True)[0], 0)
            self.assertEqual(renderer.call_count, 0)
        self.assertEqual((self.out / "fe8-001/resultado.json").read_bytes(), original)

    def test_corrupt_export_is_regenerated_in_new_attempt_and_old_is_preserved(self):
        self.run_batch()
        png = self.out / "fe8-001/galeria/retratos/face-001.png"
        png.write_bytes(b"corrupted")
        self.assertEqual(self.run_batch(resume=True)[0], 0)
        state = batch.small_json(self.out / "run-state.json")
        self.assertTrue(state["jobs"]["fe8-001"]["directory"].startswith("fe8-001-r"))
        self.assertEqual(png.read_bytes(), b"corrupted")
        with ZipFile(self.run_batch(resume=True)[1]) as z:
            self.assertNotIn("fe8-001/galeria/retratos/face-001.png", z.namelist())

    def test_interrupt_after_first_job_saves_partial_zip_and_resumes_only_second(self):
        self.add_job()
        original = batch.verify_job_inputs

        def stop_second(job, *args):
            if job["id"] == "fe8-002":
                raise KeyboardInterrupt()
            return original(job, *args)

        with patch.object(batch, "verify_job_inputs", side_effect=stop_second):
            code, partial = self.run_batch()
        self.assertEqual(code, 130)
        old = (batch.file_hash(partial), partial.stat().st_mtime_ns)
        with ZipFile(partial) as z:
            self.assertIsNone(z.testzip())
            summary = json.loads(z.read("resumen.json"))
            self.assertEqual(summary["completed_variants"], 1)
            self.assertEqual(summary["pending_variants"], 1)
            self.assertEqual(summary["run_status"], "interrupted")
        with patch.object(FACES, "reconstruct_faces", wraps=FACES.reconstruct_faces) as renderer:
            self.assertEqual(self.run_batch(resume=True)[0], 0)
            self.assertEqual(renderer.call_count, 1)
        self.assertEqual((batch.file_hash(partial), partial.stat().st_mtime_ns), old)

    def test_changed_air_is_rejected_even_when_old_result_exists(self):
        self.run_batch()
        path = Path(self.plan["jobs"][0]["air_path"])
        path.write_bytes(path.read_bytes() + b"\n")
        with patch.object(FACES, "reconstruct_faces") as renderer:
            self.assertEqual(self.run_batch(resume=True)[0], 2)
            renderer.assert_not_called()
        self.assertIn("AIR cambió", batch.small_json(self.out / "resumen.json")["variants"][0]["Detalle"])

    def test_changed_rom_is_rejected_before_rendering(self):
        p = Path(self.plan["jobs"][0]["rom_path"])
        data = bytearray(p.read_bytes())
        data[0x200] ^= 1
        p.write_bytes(data)
        with patch.object(FACES, "reconstruct_faces") as renderer:
            self.assertEqual(self.run_batch()[0], 2)
            renderer.assert_not_called()

    def test_wrong_table_hash_is_rejected(self):
        self.plan["jobs"][0]["table_bytes_sha256"] = "0" * 64
        self.save_plan()
        self.assertEqual(self.run_batch()[0], 2)
        self.assertFalse((self.out / "fe8-001/galeria").exists())

    def test_changed_definition_is_rejected_without_creating_output(self):
        (self.tools / "fe8-001.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "definición"):
            self.run_batch()
        self.assertFalse(self.out.exists())

    def test_bad_palette_fails_preflight_before_rendering(self):
        self.plan["jobs"].clear()
        self.add_job(bad_palette=True)
        with patch.object(FACES, "reconstruct_faces") as renderer:
            self.assertEqual(self.run_batch()[0], 2)
            renderer.assert_not_called()

    def test_compressed_component_absent_from_air_is_explicitly_rejected(self):
        self.plan["jobs"].clear()
        self.add_job(missing_compressed=True)
        with patch.object(FACES, "reconstruct_faces") as renderer:
            self.assertEqual(self.run_batch()[0], 2)
            renderer.assert_not_called()
        self.assertIn(
            "comprimido ausente del AIR",
            batch.small_json(self.out / "resumen.json")["variants"][0]["Detalle"],
        )

    def test_missing_or_corrupt_original_blob_is_reported_without_false_success(self):
        blob = next((self.inputs / "job-1/resources").glob("*.bin"))
        blob.write_bytes(b"bad")
        self.assertEqual(self.run_batch()[0], 2)
        summary = batch.small_json(self.out / "resumen.json")
        self.assertEqual(summary["completed_variants"], 0)
        self.assertNotEqual(summary["run_status"], "completed")

    def test_latest_run_matches_plan_and_rejects_unrelated_runs(self):
        self.run_batch()
        self.assertEqual(batch.latest_run(self.out.parent, batch.file_hash(self.plan_path)), self.out)
        self.assertIsNone(batch.latest_run(self.out.parent, "f" * 64))

    def test_archive_interrupt_removes_temp_file_and_preserves_state(self):
        with patch.object(batch.ZipFile, "write", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_batch()
        self.assertFalse(list(self.out.parent.glob(".*.tmp")))
        self.assertFalse((self.out / ".arcanacart.lock").exists())
        with patch.object(FACES, "reconstruct_faces", wraps=FACES.reconstruct_faces) as renderer:
            self.assertEqual(self.run_batch(resume=True)[0], 0)
            renderer.assert_not_called()

    def test_direct_cli_uses_real_api_and_custom_output_parent(self):
        result = subprocess.run(
            [
                sys.executable,
                str(PACKAGE / "extraer_retratos_variantes.py"),
                "--repo",
                str(REPO),
                "--plan",
                str(self.plan_path),
                "--output-parent",
                str(self.out.parent),
                "--resume-latest",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Variantes completadas: 1/1", result.stdout)
        out = batch.latest_run(self.out.parent, batch.file_hash(self.plan_path))
        self.assertIsNotNone(out)

    def test_delivered_manifest_contains_43_valid_exact_hash_bound_definitions(self):
        plan, checksum = batch.read_plan(PACKAGE / "planes.json")
        self.assertEqual(len(plan["jobs"]), 43)
        self.assertEqual(plan["expected_total_pngs"], 17291)
        self.assertEqual(len({j["rom_sha256"] for j in plan["jobs"]}), 43)
        for job in plan["jobs"]:
            layout = batch.small_json(PACKAGE / job["layout_file"])
            self.assertEqual(
                FACES.checked_layout(layout, {"sha256": job["rom_sha256"], "size_bytes": 32 * 1024 * 1024}),
                layout,
            )
            self.assertEqual(job["last_id"], 228 if job["game"] == "fe7" else 254)


if __name__ == "__main__":
    unittest.main()
