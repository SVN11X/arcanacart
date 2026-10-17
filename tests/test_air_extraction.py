import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from arcanacart.compare import binary_compare, semantic_compare
from arcanacart.core.io import digest
from arcanacart.exporters import export_csv, export_json, target_compatibility
from arcanacart.extractors import extract_tables, select_profile
from arcanacart.extractors.layouts import get_layout
from arcanacart.pipeline import analyze
from arcanacart.reporting import render
from arcanacart.schemas import schema, validate
from examples.generate_synthetic import fixture
from feunpack.gba import header_info


class AIRExtractionTests(unittest.TestCase):
    def setUp(self):
        self.data, self.tables = fixture()
        self.rom = header_info(self.data)
        self.doc, self.blobs = analyze(self.data, self.rom, profile="fe8-us", tables=self.tables)

    def test_real_bytes_decode_signed_stats(self):
        records = {r["kind"]: r for r in self.doc["entities"] if r["key"] == "1"}
        self.assertEqual(records["Character"]["data"]["base_hp"], -2)
        self.assertEqual(records["Character"]["data"]["growth_hp"], 41)
        self.assertEqual(records["Class"]["data"]["base_movement"], 5)
        self.assertEqual(records["Class"]["data"]["max_hp"], 61)
        self.assertEqual(records["Item"]["data"]["might"], 7)
        self.assertEqual(records["Item"]["data"]["range_min"], 1)
        self.assertEqual(records["Item"]["data"]["range_max"], 2)
        self.assertEqual(records["Character"]["offset"], 0x200)
        self.assertEqual(records["Character"]["sha256"], digest(self.data[0x200:0x234]))
        self.assertEqual(records["Character"]["references"], [records["Class"]["id"]])

    def test_unknown_variant_explicitly_inferred(self):
        self.assertEqual(self.rom["verification"], "unknown-or-modified")
        self.assertIsNone(self.rom["reference"])
        for record in self.doc["entities"]:
            if record["kind"] in {"Character", "Class", "Item"}:
                self.assertEqual(record["validation"], "inferred")
                self.assertEqual(record["confidence"], "heuristic")
                self.assertTrue(record["unknown_fields"])

    def test_game_code_does_not_promote_profile(self):
        self.assertEqual(select_profile(self.rom), "generic-gba")
        entities, statuses = extract_tables(self.data, self.rom, "fe8-us", None)
        self.assertEqual(entities, [])
        self.assertEqual(statuses[0]["status"], "skipped")

    def test_profile_conflicts_with_reference(self):
        rom = {**self.rom, "reference": {"profile": "fe8-us"}}
        with self.assertRaises(ValueError):
            select_profile(rom, "fe7-us")

    def test_wrong_hash_and_wrong_profile_rejected(self):
        for key, value in [("rom_sha256", "0" * 64), ("profile", "fe7-us")]:
            config = copy.deepcopy(self.tables)
            config[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                extract_tables(self.data, self.rom, "fe8-us", config)

    def test_table_out_of_range_negative_bool_and_count_limit(self):
        for key, value in [
            ("offset", 4090),
            ("offset", -1),
            ("offset", True),
            ("count", 50001),
            ("count", 0),
        ]:
            config = copy.deepcopy(self.tables)
            config["tables"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                extract_tables(self.data, self.rom, "fe8-us", config)

    def test_table_evidence_and_duplicates(self):
        config = copy.deepcopy(self.tables)
        config["evidence"] = []
        with self.assertRaises(ValueError):
            extract_tables(self.data, self.rom, "fe8-us", config)
        config = copy.deepcopy(self.tables)
        config["tables"].append(config["tables"][0])
        with self.assertRaises(ValueError):
            extract_tables(self.data, self.rom, "fe8-us", config)

    def test_unavailable_fe7_item_is_not_invented(self):
        with self.assertRaises(ValueError):
            get_layout("fe7-us", "Item")

    def test_fe7_layouts_with_own_fixture(self):
        raw, config = fixture("fe7-us")
        doc, _ = analyze(raw, header_info(raw), profile="fe7-us", tables=config, scan=False)
        self.assertEqual(len([r for r in doc["entities"] if r["kind"] in {"Character", "Class"}]), 4)
        self.assertIn("battle_palettes", next(r for r in doc["entities"] if r["kind"] == "Character")["data"])
        validate(doc)

    def test_serialization_and_stable_identity(self):
        validate(json.loads(json.dumps(self.doc)))
        again, _ = analyze(self.data, self.rom, profile="fe8-us", tables=self.tables)
        self.assertEqual(self.doc, again)

    def test_external_draft2020_validator(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Install .[dev] for independent JSON Schema validation")
        jsonschema.Draft202012Validator.check_schema(schema())
        jsonschema.Draft202012Validator(schema()).validate(self.doc)

    def test_validator_missing_required(self):
        bad = copy.deepcopy(self.doc)
        del bad["entities"][0]["evidence"]
        with self.assertRaises(ValueError):
            validate(bad)

    def test_validator_types_unknown_fields_and_pattern(self):
        for key, value in [
            ("offset", -1),
            ("offset", True),
            ("kind", "MadeUp"),
            ("variant", "bad"),
            ("confidence", "certain"),
        ]:
            bad = copy.deepcopy(self.doc)
            bad["entities"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(bad)
        bad = copy.deepcopy(self.doc)
        bad["unexpected"] = "not schema"
        with self.assertRaises(ValueError):
            validate(bad)

    def test_validator_duplicate_id_and_dangling_reference(self):
        bad = copy.deepcopy(self.doc)
        bad["entities"].append(bad["entities"][0])
        with self.assertRaises(ValueError):
            validate(bad)
        bad = copy.deepcopy(self.doc)
        bad["entities"][0]["references"] = ["air:" + "0" * 64]
        with self.assertRaises(ValueError):
            validate(bad)

    def test_validator_nan_nested_and_deep_data(self):
        bad = copy.deepcopy(self.doc)
        bad["entities"][0]["data"]["bad"] = float("nan")
        with self.assertRaises(ValueError):
            validate(bad)
        nested = {}
        for _ in range(40):
            nested = {"nested": nested}
        bad["entities"][0]["data"] = nested
        with self.assertRaises(ValueError):
            validate(bad)

    def test_validator_entity_bounds_and_provenance(self):
        for key, value in [("offset", 4096), ("game", "other-game")]:
            bad = copy.deepcopy(self.doc)
            e = next(e for e in bad["entities"] if e["kind"] == "Character")
            e[key] = value
            with self.assertRaises(ValueError):
                validate(bad)

    def test_export_json_and_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            export_json(self.doc, root / "air.json")
            export_csv(self.doc, root / "data.csv")
            validate(json.loads((root / "air.json").read_text()))
            rows = list(csv.reader(io.StringIO((root / "data.csv").read_text())))
            self.assertEqual(len(rows) - 1, len(self.doc["entities"]))
            with self.assertRaises(ValueError):
                export_json(self.doc, root / "air.json")

    def test_csv_formula_and_html_injection(self):
        bad = copy.deepcopy(self.doc)
        bad["entities"][0]["key"] = '=HYPERLINK("bad")'
        bad["rom"]["title"] = "<script>alert(1)</script>"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "out.csv"
            export_csv(bad, path)
            rows = list(csv.reader(io.StringIO(path.read_text())))
            self.assertTrue(rows[1][2].startswith("'="))
        page = render(bad, "html")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("cdn.", page)

    def test_markdown_untrusted_backticks(self):
        bad = copy.deepcopy(self.doc)
        bad["rom"]["title"] = "```\n# injection"
        self.assertIn("````json", render(bad))

    def test_real_coverage_and_no_ltproj_claim(self):
        coverage = self.doc["coverage"]
        self.assertEqual(coverage["classified_bytes"] + coverage["unknown_bytes"], 4096)
        self.assertEqual(coverage["denominator_bytes"], 4096)
        self.assertFalse(target_compatibility(self.doc)["ltmaker_project"])

    def test_semantic_compare_relocated_changed_field(self):
        other = copy.deepcopy(self.doc)
        record = next(r for r in other["entities"] if r["kind"] == "Item")
        record["offset"] += 16
        record["data"]["might"] += 2
        record["sha256"] = "f" * 64
        result = semantic_compare(self.doc, other)
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["fields"], [{"field": "might", "before": 7, "after": 9}])
        self.assertNotEqual(result["changes"][0]["left_offset"], result["changes"][0]["right_offset"])

    def test_binary_diff_range_cap_and_growth(self):
        result = binary_compare(b"abcd", b"XbYdZ", max_ranges=1)
        self.assertEqual(result["changed_bytes"], 3)
        self.assertEqual(result["range_count"], 3)
        self.assertTrue(result["ranges_truncated"])
        self.assertEqual(binary_compare(b"same", b"same")["changed_bytes"], 0)
