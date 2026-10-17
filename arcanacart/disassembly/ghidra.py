from __future__ import annotations

import os
import re
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path
from xml.etree import ElementTree

from arcanacart.core.io import check_destination, digest, read_bounded, read_json
from feunpack.gba import read_rom


class GhidraUnavailable(ValueError):
    """Optional tool is missing or its installation cannot be validated."""


def detect(home: Path | None = None, loader_dir: Path | None = None) -> dict:
    candidate = home or (Path(os.environ["GHIDRA_HOME"]) if os.environ.get("GHIDRA_HOME") else None)
    if candidate is None:
        return {
            "available": False,
            "reason": "Indica --ghidra-home o GHIDRA_HOME.",
            "runtime_verified": False,
        }
    home = candidate.resolve()
    executable = home / "support" / ("analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless")
    properties = home / "Ghidra" / "application.properties"
    if not executable.is_file() or not properties.is_file():
        return {
            "available": False,
            "reason": "No se encontró support/analyzeHeadless o application.properties.",
            "runtime_verified": False,
        }
    text = read_bounded(properties, 65536).decode("utf-8")
    version_match = re.search(r"^application.version=(.+)$", text, re.M)
    version = version_match[1].strip() if version_match else None
    ldefs = home / "Ghidra/Processors/ARM/data/languages/ARM.ldefs"
    language_ok = False
    if ldefs.is_file():
        xml = read_bounded(ldefs, 1024 * 1024)
        if b"<!DOCTYPE" not in xml.upper():
            language_ok = any(
                node.get("id") == "ARM:LE:32:v4t" for node in ElementTree.fromstring(xml).iter("language")
            )
    loader_properties = loader_dir / "extension.properties" if loader_dir else None
    loader_version = None
    if loader_properties and loader_properties.is_file():
        loader_text = read_bounded(loader_properties, 65536).decode("utf-8")
        match = re.search(r"^version=(.+)$", loader_text, re.M)
        loader_version = match[1].strip() if match else None
    java = shutil.which("java")
    if os.environ.get("JAVA_HOME"):
        explicit_java = Path(os.environ["JAVA_HOME"]) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if explicit_java.is_file():
            java = str(explicit_java)
    java_version = None
    if java:
        try:
            proc = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=10, check=False)
            java_version = (proc.stderr or proc.stdout).splitlines()[0] if proc.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, IndexError):
            pass
    return {
        "available": bool(language_ok and java_version),
        "home": str(home),
        "executable": str(executable),
        "version": version,
        "armv4t_present": language_ok,
        "java_version": java_version,
        "loader_version": loader_version,
        "loader_version_matches": bool(version and version == loader_version),
        "runtime_verified": False,
        "reason": "La carga real comprueba arquitectura, mapa y éxito del exportador; metadata no prueba instalación del loader.",
    }


def command(
    home: Path,
    rom: Path,
    out: Path,
    *,
    resume: bool = False,
    start: int = 0x08000000,
    end: int = 0x0A000000,
    batch: int = 0,
    timeout: int = 600,
) -> list[str]:
    if not 0x08000000 <= start < end <= 0x0A000000 or batch < 0 or timeout < 1:
        raise ValueError("Rango ROM, lote o timeout Ghidra inválido.")
    fingerprint = digest(read_rom(rom))
    executable = (
        home.resolve() / "support" / ("analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless")
    )
    script_dir = str(files("arcanacart.disassembly").joinpath("scripts"))
    project = "arcana_" + fingerprint[:16]
    operation = (
        ["-process", rom.name]
        if resume
        else ["-import", str(rom.resolve()), "-loader", "GBALoader", "-processor", "ARM:LE:32:v4t"]
    )
    return [
        str(executable),
        str((out / "project").resolve()),
        project,
        *operation,
        "-scriptPath",
        script_dir,
        "-analysisTimeoutPerFile",
        str(timeout),
        "-max-cpu",
        "2",
        "-log",
        str((out / "headless.log").resolve()),
        "-postScript",
        "ArcanaExport.java",
        str((out / "functions").resolve()),
        fingerprint,
        hex(start),
        hex(end),
        str(batch),
        "true" if resume else "false",
    ]


def run(
    rom: Path,
    out: Path,
    *,
    home: Path | None = None,
    loader_dir: Path | None = None,
    resume: bool = False,
    start: int = 0x08000000,
    end: int = 0x0A000000,
    batch: int = 0,
    timeout: int = 600,
    dry_run: bool = False,
) -> dict:
    info = detect(home, loader_dir)
    if not info.get("available"):
        raise GhidraUnavailable(info["reason"])
    if not info.get("loader_version_matches"):
        raise GhidraUnavailable(
            "Indica --loader-dir con extension.properties de la extensión GBA instalada para esta versión."
        )
    args = command(
        Path(info["home"]), rom, out, resume=resume, start=start, end=end, batch=batch, timeout=timeout
    )
    if os.name == "nt" and any(re.search(r'[%!^&|<>\r\n"()]', arg) for arg in args):
        raise ValueError(
            "Ghidra .bat en Windows requiere rutas sin metacaracteres del shell; usa WSL o renombra la carpeta."
        )
    if dry_run:
        return {"status": "planned", "dry_run": True, "argv": args, "installation": info}
    # Never re-use an unrelated or stale export as proof of success.
    check_destination(out / "process.log", force=resume)
    if out.exists() and any(out.iterdir()) and not resume:
        raise ValueError("El directorio Ghidra debe estar vacío, o usa --resume para el mismo proyecto.")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out / "project").mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = out / "functions" / "summary.json"
    if marker.exists():
        if marker.is_symlink():
            raise ValueError("Resumen Ghidra es un symlink.")
        marker.unlink()
    try:
        with (out / "process.log").open("wb") as log:
            proc = subprocess.run(
                args, stdout=log, stderr=subprocess.STDOUT, timeout=timeout + 600, check=False, shell=False
            )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            "Ghidra excedió el timeout; usa --resume. El proceso no se declara completado."
        ) from exc
    if proc.returncode != 0 or not marker.is_file():
        raise ValueError("Ghidra falló o no produjo summary.json; revisa process.log.")
    result = read_json(marker)
    expected_hash = digest(read_rom(rom))
    if result.get("rom_sha256") != expected_hash or result.get("status") != "completed":
        raise ValueError("Exportación Ghidra incompleta o de otra ROM; revisa summary.json y reanuda.")
    return {"status": "completed", "summary": result, "installation": info}
