"""Run the actual PowerShell launcher on Windows CI with synthetic prepared ROMs."""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from examples.generate_synthetic import fixture


@unittest.skipUnless(sys.platform == "win32", "El lanzador requiere PowerShell en Windows.")
class WindowsReanalysisTests(unittest.TestCase):
    def test_existing_roms_base_comparison_and_cached_repeat(self):
        shell = shutil.which("pwsh") or str(
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        if not Path(shell).is_file():
            self.skipTest("No hay PowerShell instalado.")
        with tempfile.TemporaryDirectory(prefix="arcana windows ") as directory:
            data = Path(directory)
            game = data / "resultados/fe8"
            variant = game / "034-synthetic"
            variant.mkdir(parents=True)
            raw = fixture()[0]
            base_rom, mod_rom = game / "fe8-usa-base.gba", variant / "fe8-mod.gba"
            base_rom.write_bytes(raw)
            mod_rom.write_bytes(raw)
            script = Path(__file__).resolve().parents[1] / "scripts/windows/Reanalizar-Resultados.ps1"
            arguments = [
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Datos",
                str(data),
                "-Game",
                "fe8",
                "-Variant",
                "034-*",
                "-CompareBase",
                "-Compression",
                "lz10",
                "-PythonExe",
                sys.executable,
            ]
            first = subprocess.run(arguments, capture_output=True, text=True, timeout=120)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            out = variant / "analisis-0.4.2-lz10-b64-r20000-c500000"
            air_path = out / "air.json"
            air = json.loads(air_path.read_text(encoding="utf-8"))
            self.assertEqual(air["scan"]["methods"], ["lz10"])
            self.assertEqual(len(air["resources"]), 2)
            summaries = list(game.parent.glob("resumen-reanalisis-0.4.2-lz10-*.csv"))
            self.assertEqual(len(summaries), 1)
            with summaries[0].open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            row = next(r for r in rows if r["Variante"] == "034-synthetic")
            self.assertEqual(row["SinCoincidencia"], "0")
            compared = json.loads((Path(row["Comparacion"]) / "resumen.json").read_text(encoding="utf-8"))
            self.assertEqual(compared["salidas_unicas_coincidentes"], 1)
            timestamp = air_path.stat().st_mtime_ns
            second = subprocess.run(arguments, capture_output=True, text=True, timeout=120)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(air_path.stat().st_mtime_ns, timestamp)
            self.assertEqual(len(list(game.parent.glob("resumen-reanalisis-0.4.2-lz10-*.csv"))), 2)
            self.assertEqual(base_rom.read_bytes(), raw)
            self.assertEqual(mod_rom.read_bytes(), raw)
