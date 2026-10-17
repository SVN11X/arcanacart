import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arcanacart.core.io import digest
from arcanacart.disassembly import ghidra
from arcanacart.integrations.symbols import import_symbols
from examples.generate_synthetic import fixture
from feunpack.gba import header_info


class ReferenceTests(unittest.TestCase):
    def test_reference_formats_and_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            symbols = root / "test.sym"
            symbols.write_text(
                "08000100 T First\n08000200 Data\nThird = 0x08000300;\n.equ Fourth, 0x02000010\nSET_FUNC Thumb, 0x08000401\nSET_DATA Mirror, 0x0A000500\nFirst = 0x08000900;\n"
            )
            result = import_symbols(root, Path("test.sym"), rom=header_info(fixture()[0]))
            self.assertEqual(result["count"], 6)
            self.assertEqual(result["symbols"][4]["offset"], 0x400)
            self.assertEqual(result["symbols"][5]["offset"], 0x500)
            self.assertEqual(len(result["conflicts"]), 1)
            self.assertEqual(result["symbol_file_sha256"], digest(symbols.read_bytes()))
            self.assertIsNone(result["reference_commit"])
            self.assertTrue(all(s["validation"] == "reference-only" for s in result["symbols"]))

    def test_reference_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "reference"
            folder.mkdir()
            outside = root / "outside.map"
            outside.write_text("08000100 T Test")
            with self.assertRaises(ValueError):
                import_symbols(folder, outside)

    def test_reference_tracks_commit_without_building(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            path = root / "test.map"
            path.write_text("08000100 T Test\n")
            subprocess.run(["git", "-C", str(root), "add", "test.map"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@localhost",
                    "commit",
                    "-qm",
                    "synthetic map",
                ],
                check=True,
            )
            result = import_symbols(root, Path("test.map"))
            self.assertEqual(len(result["reference_commit"]), 40)
            self.assertIsNone(result["working_tree_matches_commit"])


class GhidraContractTests(unittest.TestCase):
    """Fake process contracts do NOT validate an installed Ghidra or compile Java."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = self.root / "synthetic name.gba"
        self.rom.write_bytes(fixture()[0])
        self.home = self.root / "ghidra"
        self.out = self.root / "output"
        self.detected = {"available": True, "home": str(self.home), "loader_version_matches": True}

    def test_argv_armv4t_no_shell_and_resume(self):
        args = ghidra.command(self.home, self.rom, self.out)
        self.assertIn("ARM:LE:32:v4t", args)
        self.assertIn("GBALoader", args)
        self.assertNotIn("-overwrite", args)
        self.assertIn(str(self.rom), args)
        resumed = ghidra.command(self.home, self.rom, self.out, resume=True)
        self.assertIn("-process", resumed)
        self.assertNotIn("-import", resumed)

    def test_invalid_range_rejected(self):
        for options in [{"start": 0x07000000}, {"end": 0x08000000}, {"batch": -1}, {"timeout": 0}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                ghidra.command(self.home, self.rom, self.out, **options)

    def test_dry_run_never_executes_or_writes(self):
        with (
            patch.object(ghidra, "detect", return_value=self.detected),
            patch.object(ghidra.subprocess, "run", side_effect=AssertionError("must not execute")),
        ):
            result = ghidra.run(self.rom, self.out, dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertFalse(self.out.exists())

    def test_exit_zero_without_export_is_failure(self):
        with (
            patch.object(ghidra, "detect", return_value=self.detected),
            patch.object(ghidra.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
        ):
            with self.assertRaisesRegex(ValueError, "summary"):
                ghidra.run(self.rom, self.out)

    def test_partial_or_wrong_hash_is_never_success(self):
        for state, hash_ in [("partial", digest(self.rom.read_bytes())), ("completed", "0" * 64)]:
            with self.subTest(state=state):

                def fake_run(args, status=state, fingerprint=hash_, **kwargs):
                    self.assertFalse(kwargs["shell"])
                    path = self.out / "functions" / "summary.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"status": status, "rom_sha256": fingerprint}))
                    return subprocess.CompletedProcess(args, 0)

                with (
                    patch.object(ghidra, "detect", return_value=self.detected),
                    patch.object(ghidra.subprocess, "run", side_effect=fake_run),
                ):
                    with self.assertRaisesRegex(ValueError, "incompleta"):
                        ghidra.run(self.rom, self.out, resume=self.out.exists())

    def test_stale_summary_not_reused(self):
        path = self.out / "functions" / "summary.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"status": "completed", "rom_sha256": digest(self.rom.read_bytes())}))
        with (
            patch.object(ghidra, "detect", return_value=self.detected),
            patch.object(ghidra.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
        ):
            with self.assertRaises(ValueError):
                ghidra.run(self.rom, self.out, resume=True)
        self.assertFalse(path.exists())

    def test_script_packaged_and_compat_copy_identical(self):
        package = Path(ghidra.__file__).parent / "scripts" / "ArcanaExport.java"
        self.assertTrue(package.is_file())
        self.assertEqual(package.read_bytes(), Path("scripts/ghidra/ArcanaExport.java").read_bytes())
        self.assertNotIn("askDirectory", package.read_text())
        self.assertNotIn("maximum = 1000", package.read_text())

    def test_detect_missing_or_invalid_installation(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(ghidra.detect()["available"])
        self.assertFalse(ghidra.detect(self.home)["available"])
