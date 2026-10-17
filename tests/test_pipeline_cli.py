import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from test_ups import patch_from

from arcanacart.cli import build_parser, main
from arcanacart.core.io import atomic_json
from arcanacart.pipeline import pipeline
from arcanacart.schemas import validate
from examples.generate_synthetic import fixture
from feunpack.cli import main as legacy_main


def call_cli(arguments, legacy=False):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = (legacy_main if legacy else main)(list(map(str, arguments)))
    return status, stdout.getvalue(), stderr.getvalue()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = self.root / "synthetic.gba"
        self.data, self.tables = fixture()
        self.rom.write_bytes(self.data)
        self.config = self.root / "tables.json"
        atomic_json(self.config, self.tables)
        self.out = self.root / "analysis"

    def test_pipeline_complete_and_cache_hashes(self):
        first = pipeline(self.rom, self.out, profile="fe8-us", tables=self.tables)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["resource_count"], 3)
        self.assertEqual(first["entity_count"], 12)
        doc = json.loads((self.out / "air.json").read_text())
        validate(doc)
        self.assertEqual(next(s for s in doc["stages"] if s["name"] == "ghidra")["status"], "skipped")
        time = (self.out / "air.json").stat().st_mtime_ns
        cached = pipeline(self.rom, self.out, profile="fe8-us", tables=self.tables, resume=True)
        self.assertTrue(cached["cache_hit"])
        self.assertEqual((self.out / "air.json").stat().st_mtime_ns, time)

    def test_corrupted_or_missing_artifact_reprocessed(self):
        pipeline(self.rom, self.out, profile="fe8-us", tables=self.tables)
        (self.out / "report.html").write_text("tampered")
        result = pipeline(self.rom, self.out, profile="fe8-us", tables=self.tables, resume=True)
        self.assertFalse(result["cache_hit"])
        self.assertIn("<!doctype html>", (self.out / "report.html").read_text())
        (self.out / "entities.csv").unlink()
        self.assertFalse(
            pipeline(self.rom, self.out, profile="fe8-us", tables=self.tables, resume=True)["cache_hit"]
        )

    def test_changed_configuration_refuses_resume(self):
        pipeline(self.rom, self.out, scan=False)
        with self.assertRaisesRegex(ValueError, "cambiaron"):
            pipeline(self.rom, self.out, scan=True, resume=True)

    def test_dry_run_writes_nothing(self):
        result = pipeline(self.rom, self.out, dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertFalse(self.out.exists())

    def test_dry_run_validates_tables(self):
        bad = {**self.tables, "rom_sha256": "0" * 64}
        with self.assertRaises(ValueError):
            pipeline(self.rom, self.out, profile="fe8-us", tables=bad, dry_run=True)
        self.assertFalse(self.out.exists())

    def test_failure_records_state_and_can_resume(self):
        with patch("arcanacart.pipeline.analyze", side_effect=ValueError("synthetic-stage-failure")):
            with self.assertRaises(ValueError):
                pipeline(self.rom, self.out, scan=False)
        self.assertEqual(json.loads((self.out / "pipeline-state.json").read_text())["status"], "failed")
        self.assertEqual(pipeline(self.rom, self.out, scan=False, resume=True)["status"], "completed")

    def test_optional_ghidra_absence_does_not_break_core(self):
        with patch(
            "arcanacart.disassembly.ghidra.detect",
            return_value={"available": False, "reason": "not installed"},
        ):
            result = pipeline(self.rom, self.out, scan=False, with_ghidra=True)
        self.assertEqual(result["status"], "completed")
        doc = json.loads((self.out / "air.json").read_text())
        self.assertEqual(next(s for s in doc["stages"] if s["name"] == "ghidra")["status"], "skipped")

    def test_optional_ghidra_failure_records_partial(self):
        with patch("arcanacart.disassembly.ghidra.run", side_effect=ValueError("synthetic-tool-failure")):
            result = pipeline(self.rom, self.out, scan=False, with_ghidra=True)
        self.assertEqual(result["status"], "partial")
        self.assertTrue((self.out / "air.json").exists())

    def test_unrelated_output_directory_is_preserved(self):
        self.out.mkdir()
        (self.out / "owned").write_text("mine")
        with self.assertRaises(ValueError):
            pipeline(self.rom, self.out, resume=True)
        self.assertEqual((self.out / "owned").read_text(), "mine")

    def test_zip_pipeline_without_publishing_rom(self):
        archive = self.root / "rom.zip"
        with ZipFile(archive, "w") as z:
            z.writestr("roms/synthetic.gba", self.data)
        result = pipeline(archive, self.out, scan=False)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(list(self.out.rglob("*.gba")), [])

    def test_cache_manifest_cannot_escape_directory(self):
        pipeline(self.rom, self.out, scan=False)
        path = self.out / "pipeline-state.json"
        state = json.loads(path.read_text())
        state["artifacts"]["../secret"] = "0" * 64
        path.write_text(json.dumps(state))
        result = pipeline(self.rom, self.out, scan=False, resume=True)
        self.assertFalse(result["cache_hit"])
        self.assertNotIn("../secret", result["artifacts"])

    def test_no_absolute_source_path_in_report(self):
        pipeline(self.rom, self.out, scan=False)
        self.assertNotIn(str(self.root), (self.out / "report.md").read_text())

    def test_every_command_has_help(self):
        commands = next(
            a for a in build_parser()._actions if isinstance(a, __import__("argparse")._SubParsersAction)
        ).choices
        for command in commands:
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as status:
                    main([command, "--help"])
                self.assertEqual(status.exception.code, 0)

    def test_cli_inspect_error_json_and_invalid_argument(self):
        for arguments in [["inspect", self.root / "missing.gba"], ["nonesuch"], ["inspect"]]:
            code, _, error = call_cli(arguments)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(error)["status"], "error")
        code, out, error = call_cli(["inspect", self.rom, "--json"])
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(out)["verification"], "unknown-or-modified")

    def test_cli_pipeline_and_exports(self):
        code, out, error = call_cli(
            ["pipeline", "--rom", self.rom, "--profile", "fe8-us", "--tables", self.config, "--out", self.out]
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(out)["status"], "completed")
        for command, extra in [("export", ["--format", "csv"]), ("report", ["--format", "html"])]:
            output = self.root / (command + ".out")
            code, _, error = call_cli([command, "--input", self.out / "air.json", "--out", output, *extra])
            self.assertEqual(code, 0, error)
            self.assertTrue(output.exists())

    def test_legacy_all_original_commands(self):
        archive = self.root / "rom.zip"
        with ZipFile(archive, "w") as z:
            z.writestr("synthetic.gba", self.data)
        delta = self.root / "test.ups"
        changed = self.data[:0x200] + b"!" + self.data[0x201:]
        delta.write_bytes(patch_from(self.data, changed))
        listing = self.root / "listing.txt"
        listing.write_text('<entrada ruta="test.ups" tamano_bytes="12"/>')
        commands = [
            ["inspect", self.rom],
            ["inspect", delta],
            ["inspect-zip", archive],
            ["prepare-zip", "--zip", archive, "--out", self.root / "prepared.gba", "--allow-unknown"],
            ["apply-ups", "--rom", self.rom, "--patch", delta, "--out", self.root / "patched.gba"],
            ["scan-lz10", "--rom", self.rom, "--out", self.root / "lz"],
            [
                "dump",
                "--rom",
                self.rom,
                "--offset",
                "0xA0",
                "--size",
                "0x20",
                "--out",
                self.root / "dump.bin",
            ],
            ["inventory", listing],
        ]
        for args in commands:
            with self.subTest(command=args[0]):
                code, out, error = call_cli(args, legacy=True)
                self.assertEqual(code, 0, error)
                json.loads(out)
        self.assertEqual((self.root / "dump.bin").read_bytes(), self.data[0xA0:0xC0])

    def test_cli_force_cannot_mutate_input(self):
        before = self.rom.read_bytes()
        code, _, _ = call_cli(
            ["dump", "--rom", self.rom, "--offset", "0", "--size", "1", "--out", self.rom, "--force"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(self.rom.read_bytes(), before)

    def test_cli_missing_optional_tool_exit_four(self):
        with patch(
            "arcanacart.disassembly.ghidra.detect", return_value={"available": False, "reason": "missing"}
        ):
            code, _, error = call_cli(["disasm", "--rom", self.rom, "--out", self.out])
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(error)["code"], 4)

    def test_cli_dry_run_scan_and_patch(self):
        for cmd in ["scan", "extract", "dump"]:
            args = [cmd, "--rom", self.rom, "--out", self.out, "--dry-run"]
            if cmd == "dump":
                args += ["--offset", "0", "--size", "16"]
            code, _, error = call_cli(args)
            self.assertEqual(code, 0, error)
            self.assertFalse(self.out.exists())

    def test_existing_workspace_lock_refuses_second_writer(self):
        pipeline(self.rom, self.out, scan=False)
        lock = self.out / ".arcanacart.lock"
        lock.write_text("another-process")
        # A cache hit is read-only; force a recomputation to exercise writer lock.
        (self.out / "report.html").unlink()
        with self.assertRaisesRegex(ValueError, "bloqueo"):
            pipeline(self.rom, self.out, scan=False, resume=True)
        self.assertEqual(lock.read_text(), "another-process")

    def test_bad_state_type_controlled_error(self):
        self.out.mkdir()
        atomic_json(self.out / "pipeline-state.json", [])
        code, _, error = call_cli(["pipeline", "--rom", self.rom, "--out", self.out, "--resume"])
        self.assertEqual(code, 2)
        self.assertIn("Estado del pipeline", json.loads(error)["error"])

    def test_bad_symbol_document_controlled_error(self):
        value = self.root / "bad-symbols.json"
        atomic_json(value, [])
        code, _, error = call_cli(["pipeline", "--rom", self.rom, "--symbols", value, "--out", self.out])
        self.assertEqual(code, 2)
        self.assertIn("símbolos", json.loads(error)["error"])

    def test_no_network_or_process_needed_for_core_pipeline(self):
        with (
            patch("socket.socket", side_effect=AssertionError("network forbidden")),
            patch("subprocess.run", side_effect=AssertionError("external processes forbidden")),
        ):
            result = pipeline(self.rom, self.out, profile="fe8-us", tables=self.tables)
        self.assertEqual(result["status"], "completed")
