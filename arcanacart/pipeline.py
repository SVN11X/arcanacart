"""Reproducible local analysis and hash-checked resumable artifact bundles."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from zipfile import ZipFile

from arcanacart import __version__
from arcanacart.compression import ScanLimits, scan_resources
from arcanacart.core.io import (
    atomic_json,
    atomic_write,
    check_destination,
    digest,
    json_bytes,
    read_bounded,
    read_json,
    workspace_lock,
)
from arcanacart.core.memory import interval_coverage
from arcanacart.disassembly import ghidra
from arcanacart.exporters import export_csv, export_json
from arcanacart.extractors import extract_tables, select_profile
from arcanacart.integrations.symbols import correlate, validate_symbols
from arcanacart.reporting import write_report
from arcanacart.schemas import document, entity, validate
from feunpack.archives import ArchiveLimits, _member, inspect_zip
from feunpack.gba import MAX_ROM_SIZE, header_info, read_rom


def load_rom(path: Path, member: str | None = None) -> tuple[bytes, dict]:
    if path.suffix.lower() == ".zip":
        rom = inspect_zip(path, member)
        with ZipFile(path) as archive:
            selected = _member(archive, member, ArchiveLimits())
            with archive.open(selected) as stream:
                data = stream.read(MAX_ROM_SIZE + 1)
        if len(data) != rom["size_bytes"] or digest(data) != rom["sha256"]:
            raise ValueError("El ZIP cambió durante el análisis.")
    else:
        data = read_rom(path)
        rom = header_info(data)
    rom["source_name"] = path.name
    return data, rom


def analyze(
    data: bytes,
    rom: dict,
    *,
    profile: str = "auto",
    tables: dict | None = None,
    limits: ScanLimits | None = None,
    scan: bool = True,
    symbols: dict | None = None,
) -> tuple[dict, dict[str, bytes]]:
    profile = select_profile(rom, profile)
    result = document(rom, profile)
    result["stages"].append({"name": "identify", "status": "completed", "verification": rom["verification"]})
    if not rom["gba_fixed_0x96"] or not rom["header_checksum_valid"]:
        result["warnings"].append(
            "Cabecera inválida; se conserva el análisis genérico y no se confirma identidad."
        )
    if rom["verification"] != "exact-reference":
        result["warnings"].append("Variante desconocida o modificada. Game Code no demuestra originalidad.")
    result["entities"].extend(
        [
            entity(
                "Game",
                rom,
                profile,
                profile,
                parser="gba-header",
                data={"profile": profile, "game_code_hint": rom["game_code"]},
                evidence=[
                    "header-game-code",
                    "sha1-reference-match" if rom["reference"] else "unknown-variant",
                ],
                validation="confirmed" if rom["reference"] else "inferred",
                confidence="exact" if rom["reference"] else "heuristic",
                unknown=["campaign", "mechanics"],
            ),
            entity(
                "ROMVariant",
                rom,
                profile,
                rom["sha256"],
                parser="gba-header",
                data={"sha1": rom["sha1"], "crc32": rom["crc32"]},
                evidence=["whole-file-hashes"],
                validation="confirmed",
                confidence="exact",
                sha256=rom["sha256"],
            ),
        ]
    )
    result["entities"].append(
        entity(
            "Asset",
            rom,
            profile,
            "cartridge-header",
            offset=0,
            size=0xC0,
            parser="gba-header",
            data={"type": "header"},
            sha256=digest(data[:0xC0]),
            evidence=["fixed-size-header", "checksum-calculation"],
            unknown=["entrypoint_semantics"],
        )
    )
    table_entities, statuses = extract_tables(data, rom, profile, tables)
    result["entities"].extend(table_entities)
    result["extractors"] = statuses
    result["stages"].append(
        {
            "name": "tables",
            "status": "completed" if tables is not None else "skipped",
            "entities": len(table_entities),
            "reason": None if tables is not None else "No hay definición de tablas ligada a este hash.",
        }
    )
    blobs: dict[str, bytes] = {}
    if scan:
        resources, blobs, stats = scan_resources(data, limits)
        result.update(resources=resources, scan=stats)
        for record in resources:
            result["entities"].append(
                entity(
                    "Asset",
                    rom,
                    profile,
                    "compressed:" + str(record["offset"]),
                    offset=record["offset"],
                    size=record["compressed_bytes"],
                    parser="bios-compression",
                    data={k: v for k, v in record.items() if k not in {"references", "evidence"}},
                    evidence=record["evidence"],
                    sha256=record["encoded_sha256"],
                    confidence="heuristic",
                    unknown=record["unknown_fields"],
                )
            )
        if stats["truncated"]:
            result["warnings"].append("Escaneo incompleto por presupuesto: " + str(stats["stop_reason"]))
        result["stages"].append(
            {"name": "resources", "status": "partial" if stats["truncated"] else "completed"}
        )
    else:
        result["stages"].append({"name": "resources", "status": "skipped", "reason": "Escaneo desactivado."})
    ranges = [(e["offset"], e["size_bytes"]) for e in result["entities"] if e["offset"] is not None]
    result["coverage"] = interval_coverage(ranges, len(data))
    result["coverage"]["by_category_bytes"] = {
        "header": 0xC0,
        "table_records": sum(e["size_bytes"] for e in table_entities),
        "compressed_candidates": sum(r["compressed_bytes"] for r in result["resources"]),
    }
    result["coverage"]["category_note"] = (
        "Categorías pueden solaparse; classified_bytes usa unión de intervalos."
    )
    if symbols is not None:
        validate_symbols(symbols)
        if symbols.get("rom_sha256") not in {None, rom["sha256"]}:
            raise ValueError("El archivo de símbolos está ligado a otra ROM.")
        result["coverage"]["symbols"] = correlate(symbols, result["entities"])
        result["stages"].append(
            {"name": "symbols", "status": "completed", "interpretation": "reference-only"}
        )
    else:
        result["stages"].append(
            {"name": "symbols", "status": "skipped", "reason": "No se proporcionó referencia local."}
        )
    validate(result)
    return result, blobs


def _cache_valid(out: Path, state: dict, fingerprint: str) -> bool:
    if state.get("fingerprint") != fingerprint or state.get("status") not in {"completed", "partial"}:
        return False
    # A bounded partial scan is reusable, but failed optional stages must be retried.
    if state.get("status") == "partial" and state.get("errors"):
        return False
    artifacts = state.get("artifacts")
    if (
        not isinstance(artifacts, dict)
        or not {"air.json", "report.md", "report.html", "entities.csv"} <= artifacts.keys()
    ):
        return False
    for name, expected in artifacts.items():
        path = out / name
        if Path(name).is_absolute() or ".." in Path(name).parts:
            return False
        try:
            check_destination(path, force=True)
            if digest(read_bounded(path, 64 * 1024 * 1024)) != expected:
                return False
        except (OSError, ValueError):
            return False
    return True


def pipeline(
    rom_path: Path,
    out: Path,
    *,
    member: str | None = None,
    profile: str = "auto",
    tables: dict | None = None,
    limits: ScanLimits | None = None,
    symbols: dict | None = None,
    scan: bool = True,
    resume: bool = False,
    dry_run: bool = False,
    with_ghidra: bool = False,
    ghidra_home: Path | None = None,
    loader_dir: Path | None = None,
) -> dict:
    data, rom = load_rom(rom_path, member)
    options = {
        "version": __version__,
        "rom": rom["sha256"],
        "profile": profile,
        "tables": tables,
        "limits": asdict(limits or ScanLimits()),
        "symbols": symbols,
        "scan": scan,
        "ghidra": ghidra.detect(ghidra_home, loader_dir) if with_ghidra else None,
    }
    fingerprint = digest(json_bytes(options))
    state_path = out / "pipeline-state.json"
    resolved_profile = select_profile(rom, profile)
    if tables is not None:
        from arcanacart.extractors import validate_tables

        validate_tables(tables, rom, resolved_profile)
    if dry_run:
        return {
            "status": "planned",
            "dry_run": True,
            "input": rom,
            "fingerprint": fingerprint,
            "stages": ["identify", "tables", "resources", "symbols", "ghidra", "export", "report"],
        }
    for directory in (out, *out.parents):
        if directory.is_symlink():
            raise ValueError("No se permite un directorio de salida mediante symlink.")
    if state_path.is_symlink():
        raise ValueError("El estado del pipeline no puede ser un symlink.")
    state = read_json(state_path) if state_path.exists() else None
    if state is not None and not isinstance(state, dict):
        raise ValueError("Estado del pipeline inválido; se esperaba objeto JSON.")
    if resume and state and _cache_valid(out, state, fingerprint):
        validate(read_json(out / "air.json"))
        return {**state, "cache_hit": True, "output": str(out)}
    if out.exists() and any(out.iterdir()):
        if not resume or state is None:
            raise ValueError(
                "La carpeta de salida debe estar vacía; --resume requiere un estado ArcanaCart previo."
            )
        if state.get("fingerprint") != fingerprint:
            raise ValueError(
                "Las entradas o configuración cambiaron. Usa una carpeta nueva para conservar los resultados."
            )
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    with workspace_lock(out):
        atomic_json(
            state_path,
            {"status": "running", "fingerprint": fingerprint, "artifacts": {}},
            force=state is not None,
        )
        try:
            result, blobs = analyze(
                data, rom, profile=profile, tables=tables, limits=limits, scan=scan, symbols=symbols
            )
            if with_ghidra:
                try:
                    if rom_path.suffix.lower() == ".zip":
                        raise ghidra.GhidraUnavailable(
                            "Prepara primero una ROM .gba para Ghidra; no se importan ZIP genéricos."
                        )
                    code = ghidra.run(
                        rom_path, out / "ghidra", home=ghidra_home, loader_dir=loader_dir, resume=resume
                    )
                    result["coverage"]["disassembly"] = code["summary"]
                    result["stages"].append({"name": "ghidra", "status": "completed"})
                except ghidra.GhidraUnavailable as exc:
                    result["stages"].append({"name": "ghidra", "status": "skipped", "reason": str(exc)})
                except (ValueError, OSError) as exc:
                    result["stages"].append({"name": "ghidra", "status": "failed", "reason": str(exc)})
                    result["errors"].append({"stage": "ghidra", "error": str(exc)})
            else:
                result["stages"].append(
                    {
                        "name": "ghidra",
                        "status": "skipped",
                        "reason": "Integración opcional; habilitar con --with-ghidra.",
                    }
                )
            artifacts: dict[str, str] = {}
            for hash_, blob in blobs.items():
                name = "resources/" + hash_ + ".bin"
                atomic_write(out / name, blob, force=resume)
                artifacts[name] = hash_
            result["stages"].extend(
                [{"name": "export", "status": "completed"}, {"name": "report", "status": "completed"}]
            )
            export_csv(result, out / "entities.csv", force=resume)
            write_report(result, out / "report.md", force=resume)
            write_report(result, out / "report.html", format="html", force=resume)
            export_json(result, out / "air.json", force=resume)
            for name in ["air.json", "entities.csv", "report.md", "report.html"]:
                artifacts[name] = digest(read_bounded(out / name, 64 * 1024 * 1024))
            final = {
                "status": "partial"
                if result["errors"] or result["scan"].get("truncated", False)
                else "completed",
                "fingerprint": fingerprint,
                "tool_version": __version__,
                "rom_sha256": rom["sha256"],
                "artifacts": artifacts,
                "entity_count": len(result["entities"]),
                "resource_count": len(result["resources"]),
                "scan_truncated": result["scan"].get("truncated", False),
                "warnings": result["warnings"],
                "errors": result["errors"],
            }
            atomic_json(state_path, final, force=True)
            return {**final, "cache_hit": False, "output": str(out)}
        except Exception as exc:
            atomic_json(
                state_path,
                {"status": "failed", "fingerprint": fingerprint, "error": str(exc), "artifacts": {}},
                force=True,
            )
            raise
