import json
import tempfile
import unittest
from pathlib import Path

from arcanacart.core.io import digest
from arcanacart.disassembly.index import code_index
from arcanacart.pipeline import analyze
from arcanacart.schemas import validate
from examples.generate_synthetic import fixture
from feunpack.gba import header_info


class CodeIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw, tables = fixture()
        self.rom = header_info(self.raw)
        self.doc, _ = analyze(self.raw, self.rom, profile="fe8-us", tables=tables, scan=False)
        self.source = self.root / "air.json"
        self.source.write_text(json.dumps(self.doc))
        self.export = self.root / "ghidra/functions"
        self.export.mkdir(parents=True)
        self.assembly = b"; Synthetic vector\n08000100 mov r0, r0\n"
        self.pseudocode = b"/* Generated synthetic pseudocode */\nvoid f(void) {}\n"
        (self.export / "08000100.s").write_bytes(self.assembly)
        (self.export / "08000100.c").write_bytes(self.pseudocode)
        self.record = {
            "address": "08000100",
            "name": "synthetic_function",
            "rom_sha256": self.rom["sha256"],
            "status": "completed",
            "assembly": "08000100.s",
            "pseudocode": "08000100.c",
            "assembly_sha256": digest(self.assembly),
            "pseudocode_sha256": digest(self.pseudocode),
            "instruction_ranges": [[0x08000100, 0x08000102], [0x08000108, 0x0800010A]],
        }
        self.summary = self.export / "summary.json"

    def save(self, status="completed"):
        self.summary.write_text(
            json.dumps({"rom_sha256": self.rom["sha256"], "status": status, "functions": [self.record]})
        )

    def test_no_tool_is_not_reported_as_disassembly(self):
        result = code_index(self.source, self.root / "no-tool")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["code_bytes"], 0)
        self.assertEqual(result["recovered_functions"], 0)

    def test_verified_exports_preserve_gaps_and_create_valid_air(self):
        self.save()
        out = self.root / "review"
        result = code_index(self.source, out, ghidra_summary=self.summary)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["code_bytes"], 4)
        self.assertEqual(result["code_ranges"], [[256, 258], [264, 266]])
        self.assertEqual((out / "functions/08000100.s").read_bytes(), self.assembly)
        doc = json.loads((out / "air.json").read_text())
        validate(doc)
        self.assertEqual(next(e for e in doc["entities"] if e["kind"] == "Function")["size_bytes"], 0)

    def test_legacy_exports_without_ranges_do_not_invent_size(self):
        del self.record["instruction_ranges"]
        self.record["size_bytes"] = 100
        self.save()
        result = code_index(self.source, self.root / "legacy", ghidra_summary=self.summary)
        self.assertEqual(result["recovered_functions"], 1)
        self.assertEqual(result["code_bytes"], 0)

    def test_modified_assembly_hash_is_rejected(self):
        self.save()
        (self.export / "08000100.s").write_bytes(b"changed")
        result = code_index(self.source, self.root / "tampered", ghidra_summary=self.summary)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["recovered_functions"], 0)
        self.assertEqual(result["code_bytes"], 0)
        self.assertTrue(result["errors"])

    def test_data_code_overlap_is_visible(self):
        self.record["instruction_ranges"] = [[0x08000200, 0x08000202]]
        self.save()
        result = code_index(self.source, self.root / "overlap", ghidra_summary=self.summary)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["conflicting_ranges"], [[512, 514]])

    def test_wrong_rom_and_path_traversal_rejected(self):
        self.save()
        data = json.loads(self.summary.read_text())
        data["rom_sha256"] = "f" * 64
        self.summary.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            code_index(self.source, self.root / "wrong", ghidra_summary=self.summary)
        self.record["assembly"] = "../outside.s"
        self.save()
        result = code_index(self.source, self.root / "traversal", ghidra_summary=self.summary)
        self.assertEqual(result["recovered_functions"], 0)
        self.assertTrue(result["errors"])

    def test_dry_run_writes_nothing(self):
        out = self.root / "dry"
        self.assertEqual(code_index(self.source, out, dry_run=True)["status"], "planned")
        self.assertFalse(out.exists())
