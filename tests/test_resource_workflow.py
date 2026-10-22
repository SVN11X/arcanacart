"""Selected-format pipelines and comparisons use original synthetic fixtures."""

import contextlib
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from arcanacart.cli import main
from arcanacart.core.io import atomic_json, digest
from arcanacart.pipeline import analyze, load_rom, pipeline
from arcanacart.resource_compare import catalog_csv, compare_resources
from examples.generate_synthetic import fixture


def cli(arguments):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(map(str, arguments)))
    return code, stdout.getvalue(), stderr.getvalue()


class ResourceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = self.root / "fixture.gba"
        self.rom.write_bytes(fixture()[0])
        data, metadata = load_rom(self.rom)
        self.base, _ = analyze(data, metadata, compression_methods=("lz10",))

    def manifest(self, document):
        return {k: copy.deepcopy(document[k]) for k in ("rom", "resources", "scan")}

    def append(self, document, content, offset=0x901):
        record = copy.deepcopy(document["resources"][0])
        record.update(offset=offset, sha256=digest(content), decompressed_bytes=len(content), references=[])
        document["resources"].append(record)
        document["scan"]["decoded_blocks"] = len(document["resources"])
        document["scan"]["unique_outputs"] = len({r["sha256"] for r in document["resources"]})

    def test_pipeline_selects_formats_and_records_scope(self):
        for methods, count in [(("lz10",), 2), (("rle",), 1), (("rle", "lz10"), 3)]:
            out = self.root / "-".join(methods)
            state = pipeline(self.rom, out, compression_methods=methods)
            doc = json.loads((out / "air.json").read_text())
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["resource_count"], count)
            self.assertTrue(all(r["compression"] in methods for r in doc["resources"]))
            self.assertEqual(set(doc["scan"]["methods"]), set(methods))
            if len(methods) == 1:
                report = (out / "report.md").read_text()
                self.assertIn("Formatos fuera de este barrido", report)
                self.assertIn("No mide comprensión del juego", report)

    def test_methods_are_in_cache_identity_and_order_is_canonical(self):
        out = self.root / "cache"
        pipeline(self.rom, out, compression_methods=("rle", "lz10"))
        self.assertTrue(
            pipeline(self.rom, out, compression_methods=("lz10", "rle", "lz10"), resume=True)["cache_hit"]
        )
        with self.assertRaisesRegex(ValueError, "cambiaron"):
            pipeline(self.rom, out, compression_methods=("lz10",), resume=True)

    def test_invalid_api_methods_fail_without_writing(self):
        for methods in [(), ("zip",), (["lz10"],)]:
            with self.subTest(methods=methods), self.assertRaises(ValueError):
                pipeline(self.rom, self.root / "invalid", compression_methods=methods)
            self.assertFalse((self.root / "invalid").exists())

    def test_native_cli_scan_pipeline_and_extract_select_formats(self):
        for command in ("scan", "pipeline", "extract"):
            output = self.root / command
            args = [command, "--rom", self.rom, "--out", output, "--compression", "lz10"]
            if command == "extract":
                args += ["--scan"]
            code, text, error = cli(args)
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(text)["status"], "completed")
            path = (
                output / "resources.json"
                if command == "scan"
                else output / "air.json"
                if command == "pipeline"
                else output
            )
            document = json.loads(path.read_text())
            self.assertEqual(document["scan"]["methods"], ["lz10"])
            self.assertEqual(len(document["resources"]), 2)

    def test_comparison_deduplicates_content_and_ignores_location(self):
        variant = self.manifest(self.base)
        variant["resources"][0]["offset"] = 0x801
        self.append(variant, b"DIFFERENT")
        result, rows = compare_resources(self.base, variant)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["salidas_unicas_coincidentes"], 1)
        self.assertEqual(result["salidas_unicas_sin_coincidencia"], 1)
        self.assertEqual(result["candidatos_variante"], 3)
        self.assertFalse(rows[0]["coincide_base"])
        self.assertEqual(sum(r["coincide_base"] for r in rows), 2)
        csv_rows = list(csv.DictReader(io.StringIO(catalog_csv(rows).decode("utf-8-sig"))))
        self.assertEqual(len(csv_rows), 3)
        self.assertEqual(csv_rows[0]["archivo"], digest(b"DIFFERENT") + ".bin")

    def test_uniform_hash_is_marked_and_does_not_lead_review_queue(self):
        variant = self.manifest(self.base)
        self.append(variant, bytes(32), 0x901)
        variant["resources"][-1]["references"] = [{}] * 100
        self.append(variant, b"OTHER", 0x941)
        _, rows = compare_resources(self.base, variant)
        self.assertEqual(rows[0]["sha256"], digest(b"OTHER"))
        zero = next(r for r in rows if r["sha256"] == digest(bytes(32)))
        self.assertEqual(zero["patron_uniforme"], "00")

    def test_partial_sampled_or_unrecorded_scope_stays_partial(self):
        for key, value in [("truncated", True), ("step", 4), ("methods", None)]:
            other = self.manifest(self.base)
            if value is None:
                del other["scan"][key]
            else:
                other["scan"][key] = value
            result, _ = compare_resources(self.base, other)
            self.assertEqual(result["status"], "partial")

    def test_empty_valid_scan_compares_and_exports_headers(self):
        empty = self.manifest(self.base)
        empty["resources"] = []
        empty["scan"].update(decoded_blocks=0, unique_outputs=0)
        result, rows = compare_resources(empty, empty)
        self.assertEqual(result["salidas_unicas_variante"], 0)
        self.assertEqual(rows, [])
        self.assertIn(b"offset", catalog_csv(rows))

    def test_same_hash_must_have_same_size_across_manifests(self):
        other = self.manifest(self.base)
        for record in other["resources"]:
            record["decompressed_bytes"] = 99
        with self.assertRaisesRegex(ValueError, "tamaños diferentes"):
            compare_resources(self.base, other)

    def test_invalid_manifests_are_rejected(self):
        corruptions = [
            lambda d: d["rom"].update(sha256="bad"),
            lambda d: d["scan"].update(truncated="False"),
            lambda d: d["scan"].update(unique_outputs=999),
            lambda d: d.update(methods=["rle"]),
            lambda d: d["scan"].update(methods=None),
            lambda d: d["scan"].update(methods=[["lz10"]]),
            lambda d: d["resources"][0].update(offset=999999),
            lambda d: d["resources"][0].update(references=None),
            lambda d: d["resources"][0].update(sha256="=formula"),
            lambda d: d["resources"][1].update(offset=d["resources"][0]["offset"]),
            lambda d: d["resources"][1].update(decompressed_bytes=999),
        ]
        for corrupt in corruptions:
            with self.subTest(corrupt=corrupt):
                other = self.manifest(self.base)
                corrupt(other)
                with self.assertRaises(ValueError):
                    compare_resources(self.base, other)

    def test_cli_comparison_accepts_previous_terminal_manifest(self):
        left = self.root / "base-lz10.json"
        right = self.root / "resources.json"
        old = self.manifest(self.base)
        old["methods"] = old["scan"].pop("methods")
        atomic_json(left, old)
        atomic_json(right, old)
        out = self.root / "comparison"
        args = ["compare-resources", "--left", left, "--right", right, "--out", out]
        before = left.read_bytes(), right.read_bytes()
        code, text, error = cli([*args, "--dry-run"])
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(text)["status"], "planned")
        self.assertFalse(out.exists())
        code, text, error = cli(args)
        self.assertEqual(code, 0, error)
        self.assertTrue((out / "catalogo-comparado.csv").exists())
        self.assertEqual(json.loads(text)["salidas_unicas_coincidentes"], 1)
        self.assertEqual(cli(args)[0], 2)
        self.assertEqual((left.read_bytes(), right.read_bytes()), before)

    def test_cli_partial_comparison_returns_exit_three(self):
        partial = self.manifest(self.base)
        partial["scan"]["truncated"] = True
        left, right = self.root / "left.json", self.root / "right.json"
        atomic_json(left, self.base)
        atomic_json(right, partial)
        code, text, error = cli(
            ["compare-resources", "--left", left, "--right", right, "--out", self.root / "diff"]
        )
        self.assertEqual(code, 3, error)
        self.assertEqual(json.loads(text)["status"], "partial")
