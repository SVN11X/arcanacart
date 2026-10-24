"""Continue only the audited tail; keep original evidence and every prefix entry."""

import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from arcanacart import map_sprite_followup as follow
from arcanacart import map_sprite_review as mr
from arcanacart.core.io import digest, json_bytes


def lz_literals(raw):
    return (
        b"\x10"
        + len(raw).to_bytes(3, "little")
        + b"".join(b"\0" + raw[i : i + 8] for i in range(0, len(raw), 8))
    )


class MapSpriteFollowup(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="arcana continuacion con espacios ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.datos = self.root / "datos"
        self.source = self.root / "revision-inicial"
        self.out = self.root / "revision-ampliada"
        self.plan_path = self.root / "plan.json"
        raw = bytes(range(128)) * 3
        self.sheet = lz_literals(raw)
        self.new_sheet = lz_literals(bytes(reversed(range(128))) * 3)
        base = bytearray(0x4000)
        base[0xAC:0xB0] = b"BE8E"
        base[0xB2] = 0x96
        base[0x500 - 42 : 0x500 - 34] = bytes.fromhex("7f243c40e400281d")
        struct.pack_into("<I", base, 0x500, 0x08001000)
        struct.pack_into("<I", base, 0x544, 0x08001000)
        struct.pack_into("<HHI", base, 0x1000, 2, 0, 0x08002000)
        struct.pack_into("<HHI", base, 0x1008, 2, 0, 0x08002000)
        base[0x2000 : 0x2000 + len(self.sheet)] = self.sheet
        base[0x3000:0x30E0] = bytes(range(224))
        self.base = self.datos / "resultados/fe8/fe8-usa-base.gba"
        self.base.parent.mkdir(parents=True)
        self.base.write_bytes(base)
        profiles = {
            "fe8": {"rom_sha256": digest(base), "pointer_locations": [0x500, 0x544], "palette_offset": 0x3000}
        }
        self.profile_patch = patch.object(mr, "PROFILES", profiles)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        data = bytearray(base)
        data[0x500 - 42] = 0xFF
        for i in range(129):
            struct.pack_into("<HHI", data, 0x1000 + i * 8, 2, 0, 0x08002000)
        struct.pack_into("<HHI", data, 0x1000 + 130 * 8, 2, 0, 0x08002400)
        data[0x2400 : 0x2400 + len(self.new_sheet)] = self.new_sheet
        self.rom_data = bytes(data)
        self.rom = self.datos / "resultados/fe8/001-sintetica/mod.gba"
        self.air = self.datos / "resultados/fe8/001-sintetica/analisis/air.json"
        self.rom.parent.mkdir(parents=True)
        self.air.parent.mkdir(parents=True)
        self.rom.write_bytes(data)
        self.air.write_bytes(
            json_bytes(
                {
                    "rom": {"sha256": digest(data), "size_bytes": len(data)},
                    "resources": [
                        {
                            "offset": offset,
                            "compression": "lz10",
                            "compressed_bytes": len(blob),
                            "decompressed_bytes": 384,
                            "sha256": digest(decoded),
                            "references": [0x1004],
                        }
                        for offset, blob, decoded in (
                            (0x2000, self.sheet, raw),
                            (0x2400, self.new_sheet, bytes(reversed(range(128))) * 3),
                        )
                    ],
                    "scan": {"truncated": False, "methods": ["lz10"]},
                }
            )
        )
        row = {
            "variant_id": "fe8-001",
            "game": "fe8",
            "variant": "001-sintetica",
            "rom_relative_path": "fe8/001-sintetica/mod.gba",
            "air_relative_path": "fe8/001-sintetica/analisis/air.json",
            "rom_sha256": digest(data),
            "air_sha256": digest(self.air.read_bytes()),
        }
        self.plan = {
            "format": "arcanacart-item-icon-variant-plan-1",
            "variants": [row],
            "reviewed_ranges": {},
        }
        self.plan_path.write_bytes(json_bytes(self.plan))
        mr.review_maps(self.datos, self.source, self.plan_path)
        self.original = {
            p.relative_to(self.source).as_posix(): p.read_bytes()
            for p in self.source.rglob("*")
            if p.is_file()
        }
        for name, value in (
            ("AUDITED_REPORT_SHA256", digest(self.original["revision.json"])),
            ("AUDITED_STATE_SHA256", digest(self.original[mr.STATE])),
        ):
            patcher = patch.object(follow, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_followup(self, source=None):
        return follow.extend_review(source or self.source, self.datos, self.out, self.plan_path)

    def report(self):
        return json.loads((self.out / "revision.json").read_bytes())

    def test_continue_only_128_to_255_and_preserve_all_source_bytes(self):
        with (
            patch.object(mr, "measure", wraps=mr.measure) as measure,
            patch("arcanacart.compression.scan_resources", side_effect=AssertionError("scan")),
            patch("feunpack.lz10.decompress", side_effect=AssertionError("decompression")),
        ):
            result = self.run_followup()
        self.assertEqual(measure.call_count, 2)
        self.assertEqual(result["counts"], {"pending": 2, "error": 0, "approved": 0})
        self.assertEqual(result["old_entries_remeasured"], 0)
        self.assertEqual(result["selected_tail_extensions"], 1)
        self.assertEqual(result["completed_tail_extensions"], 1)
        self.assertEqual(result["palette_contexts_collected"], 2)
        self.assertFalse(result["ready_for_extraction"])
        self.assertFalse(any(self.out.rglob("*.png")))
        for name, raw in self.original.items():
            self.assertEqual((self.out / follow.PREVIOUS / name).read_bytes(), raw)
            self.assertEqual((self.source / name).read_bytes(), raw)
        self.assertEqual(self.rom.read_bytes(), self.rom_data)

    def test_later_sheet_after_a_hole_is_collected_but_marked_for_review(self):
        self.run_followup()
        row = self.report()["results"][1]
        self.assertEqual([e["sprite_id"] for e in row["entries"]], list(range(256)))
        self.assertEqual(row["boundary_hint"], {"sprite_id": 129, "reason": "zero-record-heuristic"})
        self.assertTrue(row["entries"][130]["post_boundary_hint"])
        self.assertEqual((self.out / row["entries"][130]["stored_file"]).read_bytes(), self.new_sheet)
        self.assertFalse(row["range_approved"])
        self.assertTrue(row["tail_extension"]["continued_after_boundary_hint"])

    def test_old_compressed_sheet_is_referenced_without_a_new_copy(self):
        result = self.run_followup()
        row = self.report()["results"][1]
        self.assertEqual(
            row["entries"][128]["stored_file"],
            follow.PREVIOUS + "hojas-comprimidas/" + digest(self.sheet) + ".lz10",
        )
        self.assertEqual(result["additional_unique_stored_sheets"], 1)
        self.assertEqual(result["unique_stored_sheets"], 2)
        self.assertFalse((self.out / "hojas-comprimidas" / (digest(self.sheet) + ".lz10")).exists())

    def test_palette_context_is_exact_bounded_and_not_approved(self):
        self.run_followup()
        for row in self.report()["results"]:
            context = row["palette_load_context"]
            source = self.base if row["variant_id"].endswith("-base") else self.rom
            self.assertEqual(context["offset"], 0x300)
            self.assertEqual(context["size_bytes"], 1024)
            self.assertEqual((self.out / context["file"]).read_bytes(), source.read_bytes()[0x300:0x700])
            self.assertFalse(context["runtime_use_verified"])
            self.assertTrue(all(not p["runtime_use_verified"] for p in row["palette_candidates"]))

    def test_only_the_variant_air_is_reopened(self):
        with patch.object(follow, "_json_file", wraps=follow._json_file) as load:
            self.run_followup()
        self.assertEqual(load.call_count, 1)
        self.assertEqual(load.call_args.args[0], self.air)

    def test_zip_and_directory_sources_produce_identical_payloads(self):
        self.run_followup()
        first = {
            p.relative_to(self.out).as_posix(): p.read_bytes() for p in self.out.rglob("*") if p.is_file()
        }
        archive = self.root / "inicial.zip"
        mr.pack_variants(self.source, archive, state_name=mr.STATE)
        self.out = self.root / "desde-zip"
        self.run_followup(archive)
        for name, raw in first.items():
            if name not in {"revision.json", mr.STATE}:
                self.assertEqual((self.out / name).read_bytes(), raw)

    def test_changed_rom_stays_an_error_with_the_old_evidence_retained(self):
        self.rom.write_bytes(self.rom_data[:-1] + b"\1")
        result = self.run_followup()
        self.assertEqual(result["counts"]["error"], 1)
        row = self.report()["results"][1]
        self.assertEqual(row["status"], "error")
        self.assertFalse(row["followup_rom_bytes_verified"])
        self.assertFalse(row["extraction_enabled"])
        self.assertEqual(
            (self.out / follow.PREVIOUS / "revision.json").read_bytes(), self.original["revision.json"]
        )

    def test_air_crlf_is_rejected_as_a_byte_change(self):
        self.air.write_bytes(self.air.read_bytes().replace(b"\n", b"\r\n"))
        result = self.run_followup()
        self.assertEqual(result["counts"]["error"], 1)
        self.assertIn("AIR", self.report()["results"][1]["error"])

    def test_repository_plan_crlf_preserves_the_canonical_identity(self):
        self.plan_path.write_bytes(self.plan_path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.run_followup()["counts"]["error"], 0)

    def test_report_pin_is_required_before_any_rom_read(self):
        with (
            patch.object(follow, "AUDITED_REPORT_SHA256", "0" * 64),
            patch.object(follow, "load_rom", side_effect=AssertionError("ROM opened")),
        ):
            with self.assertRaises(ValueError):
                self.run_followup()
        self.assertFalse(self.out.exists())

    def test_manifest_pin_is_required_even_for_otherwise_valid_payloads(self):
        with patch.object(follow, "AUDITED_STATE_SHA256", "0" * 64):
            with self.assertRaises(ValueError):
                self.run_followup()

    def test_altered_source_artifact_is_rejected_by_the_manifest(self):
        path = next((self.source / "hojas-comprimidas").glob("*.lz10"))
        path.write_bytes(path.read_bytes() + b"alterado")
        with self.assertRaises(ValueError):
            self.run_followup()
        self.assertFalse(self.out.exists())

    def test_eight_bit_access_gate_rejects_a_seven_bit_candidate(self):
        report = json.loads(self.original["revision.json"])
        row = report["results"][1]
        files = dict(self.original)
        path = row["access_pointers"][0]["context_file"]
        blob = bytearray(files[path])
        blob[22] = 0x7F
        files[path] = bytes(blob)
        with self.assertRaises(ValueError):
            follow._eligible(row, files)

    def test_unsafe_zip_paths_and_case_collisions_are_rejected(self):
        for index, names in enumerate((["../fuera"], ["ABC", "abc"], ["C:/fuera"])):
            archive = self.root / f"unsafe-{index}.zip"
            with ZipFile(archive, "w") as z:
                for name in names:
                    z.writestr(name, b"x")
            with self.assertRaises(ValueError):
                follow._bundle(archive)

    def test_output_inside_source_and_existing_output_are_rejected(self):
        self.out = self.source / "anidada"
        with self.assertRaises(ValueError):
            self.run_followup()
        self.assertFalse(self.out.exists())
        self.out = self.root / "ya-existe"
        self.out.mkdir()
        with self.assertRaises(ValueError):
            self.run_followup()

    def test_completed_output_can_be_packed_after_inputs_are_removed(self):
        self.run_followup()
        self.rom.unlink()
        self.air.unlink()
        self.base.unlink()
        archive = self.root / "ampliada.zip"
        result = mr.pack_variants(self.out, archive, state_name=mr.STATE)
        self.assertTrue(result["crc_verified"])
        with ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            self.assertTrue(all("\\" not in n for n in z.namelist()))
            self.assertEqual(z.read("revision-anterior/revision.json"), self.original["revision.json"])

    def test_cli_returns_json_and_does_not_write_zip_inside_source(self):
        args = [
            "extend",
            "--review",
            str(self.source),
            "--datos",
            str(self.datos),
            "--out",
            str(self.out),
            "--identities",
            str(self.plan_path),
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            result = follow.main(args + ["--zip", str(self.source / "nuevo.zip")])
        self.assertEqual(result, 2)
        self.assertFalse((self.source / "nuevo.zip").exists())
        self.assertFalse(self.out.exists())
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            result = follow.main(args + ["--zip", str(self.root / "ok.zip")])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(text.getvalue())["counts"]["error"], 0)


if __name__ == "__main__":
    unittest.main()
