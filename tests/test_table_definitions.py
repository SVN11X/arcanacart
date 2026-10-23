import copy
import unittest

from arcanacart.extractors import extract_tables, validate_tables
from arcanacart.extractors.layouts import custom_layout
from arcanacart.tables import definition, layout_catalog
from examples.generate_synthetic import fixture
from feunpack.gba import header_info


class TableDefinitions(unittest.TestCase):
    def setUp(self):
        self.raw, self.config = fixture()
        self.rom = header_info(self.raw)
        self.custom = {
            "Unit": {
                "size": 4,
                "fields": [
                    {"name": "character_id", "offset": 0, "fmt": "B"},
                    {"name": "signed_adjustment", "offset": 1, "fmt": "b"},
                    {"name": "inventory", "offset": 2, "fmt": "H"},
                ],
                "source": "Synthetic independent unit-like vector",
                "unknown": ["event_semantics"],
            }
        }

    def test_definition_explicit_offsets_and_hash_binding(self):
        result = definition(
            self.rom, "fe8-us", ["Character:0x200:2:1", "Item:0x500:2:1"], ["Synthetic range"]
        )
        self.assertEqual(result["rom_sha256"], self.rom["sha256"])
        self.assertEqual(result["tables"][0]["offset"], 512)

    def test_definition_from_symbols_remains_reference_only(self):
        import tempfile
        from pathlib import Path

        from arcanacart.integrations.symbols import import_symbols

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test.sym").write_text("08000200 D CharacterTable\n")
            symbols = import_symbols(root, Path("test.sym"), rom=self.rom)
        result = definition(
            self.rom, "fe8-us", ["Character:CharacterTable:2:1"], ["Synthetic range"], symbols=symbols
        )
        self.assertEqual(result["tables"][0]["offset"], 512)
        self.assertIn("reference-only", result["evidence"][-1])
        symbols["rom_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            definition(self.rom, "fe8-us", ["Character:CharacterTable:2:1"], ["Test"], symbols=symbols)

    def test_custom_layout_extracts_bytes_without_claiming_game_semantics(self):
        result = definition(self.rom, "fe8-us", ["Unit:0x200:1:1"], ["Test"], layouts=self.custom)
        entities, statuses = extract_tables(self.raw, self.rom, "fe8-us", result)
        self.assertEqual(entities[0]["data"]["character_id"], self.raw[0x200])
        self.assertEqual(entities[0]["validation"], "inferred")
        self.assertEqual(entities[0]["kind"], "Unit")
        self.assertTrue(statuses[0]["custom_layout"])

    def test_custom_layout_rejects_execution_formats_overlaps_and_bounds(self):
        spec = self.custom["Unit"]
        for field, value in [("fmt", '__import__("os")'), ("fmt", "99999I"), ("offset", True), ("offset", 4)]:
            bad = copy.deepcopy(spec)
            bad["fields"][0][field] = value
            with self.assertRaises(ValueError):
                custom_layout(bad)
        bad = copy.deepcopy(spec)
        bad["fields"][1]["offset"] = 0
        with self.assertRaises(ValueError):
            custom_layout(bad)

    def test_overlapping_table_definitions_are_rejected(self):
        bad = copy.deepcopy(self.config)
        bad["tables"][1]["offset"] = 0x210
        with self.assertRaisesRegex(ValueError, "solapan"):
            validate_tables(bad, self.rom, "fe8-us")

    def test_pointer_arrays_are_checked_and_reported(self):
        import struct

        from arcanacart.core.io import digest

        raw = bytearray(self.raw)
        struct.pack_into("<III", raw, 0x300 + 0x38, 0x08000200, 0xFFFFFFFF, 0)
        rom = header_info(bytes(raw))
        config = copy.deepcopy(self.config)
        config["rom_sha256"] = digest(raw)
        entities, statuses = extract_tables(bytes(raw), rom, "fe8-us", config)
        klass = next(e for e in entities if e["kind"] == "Class")
        self.assertEqual([e["status"] for e in klass["data"]["pointer_evidence"]], ["structural", "invalid"])
        status = next(s for s in statuses if s["parser"].endswith("/Class"))
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["invalid_pointers"], 1)

    def test_builtin_catalog_does_not_invent_fe7_item_layout(self):
        catalog = layout_catalog()
        self.assertIn("Item", catalog["fe8-us"])
        self.assertNotIn("Item", catalog["fe7-us"])
        self.assertEqual(catalog["fe8-us"]["Character"]["size"], 0x34)
