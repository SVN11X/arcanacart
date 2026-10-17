"""Spanish CLI; operations are synchronous, local, bounded and JSON-capable."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, NoReturn
from zipfile import BadZipFile

from arcanacart import __version__
from arcanacart.compare import binary_compare, semantic_compare
from arcanacart.compression import ScanLimits, scan_resources
from arcanacart.core.io import (
    atomic_json,
    atomic_write,
    check_destination,
    protect_inputs,
    read_bounded,
    read_json,
)
from arcanacart.disassembly import ghidra
from arcanacart.exporters import export_csv, export_json, export_schema
from arcanacart.integrations.symbols import import_symbols
from arcanacart.pipeline import analyze, load_rom, pipeline
from arcanacart.reporting import write_report
from arcanacart.schemas import validate
from feunpack.archives import inspect_zip, prepare_zip
from feunpack.gba import header_info
from feunpack.lz10 import scan as legacy_scan
from feunpack.manifest import inventory
from feunpack.ups import MAX_SIZE, parse_info, patch_file


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError("Argumentos inválidos: " + message + "; consulta --help.")


def number(value: str) -> int:
    return int(value, 0)


def common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Salida JSON para automatización (también es el valor por defecto).",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=argparse.SUPPRESS, help="Diagnóstico de etapas en stderr."
    )


def build_parser(prog: str = "arcanacart") -> Parser:
    parser = Parser(
        prog=prog,
        description="ArcanaCart: inspección, extracción e investigación local de GBA; sin servicios externos.",
    )
    parser.add_argument("--version", action="version", version=f"ArcanaCart {__version__}")
    common(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help: str, aliases: list[str] | None = None) -> argparse.ArgumentParser:
        cmd = sub.add_parser(name, aliases=aliases or [], help=help, description=help)
        common(cmd)
        return cmd

    def output(cmd: argparse.ArgumentParser, *, force: bool = True, dry: bool = True) -> None:
        cmd.add_argument(
            "--out", required=True, type=Path, help="Archivo o carpeta local de salida explícita."
        )
        if force:
            cmd.add_argument(
                "--force", action="store_true", help="Sustituir exclusivamente salidas; nunca las entradas."
            )
        if dry:
            cmd.add_argument(
                "--dry-run", action="store_true", help="Validar y planificar sin escribir resultados."
            )

    def rom(cmd: argparse.ArgumentParser) -> None:
        cmd.add_argument("--rom", required=True, type=Path, help="ROM .gba o ZIP con una ROM.")
        cmd.add_argument("--member", help="Miembro .gba exacto, si el ZIP contiene varias ROMs.")

    def profile(cmd: argparse.ArgumentParser) -> None:
        cmd.add_argument(
            "--profile",
            choices=["auto", "generic-gba", "fe7-us", "fe8-us"],
            default="auto",
            help="Perfil de estructuras; no confirma identidad por sí mismo.",
        )
        cmd.add_argument(
            "--tables", type=Path, help="Definición JSON con SHA-256 de esta ROM y ubicación de cada tabla."
        )

    def scan_options(cmd: argparse.ArgumentParser, *, default: int = 1000) -> None:
        cmd.add_argument(
            "--limit", type=int, default=default, help="Máximo configurable de bloques encontrados."
        )
        cmd.add_argument("--max-bytes", type=number, default=2_097_152, help="Máximo de salida por bloque.")
        cmd.add_argument(
            "--budget",
            type=number,
            default=64 * 1024 * 1024,
            help="Presupuesto agregado de bytes de intentos de descompresión.",
        )
        cmd.add_argument(
            "--max-candidates", type=int, default=100_000, help="Máximo de intentos de decodificación."
        )
        cmd.add_argument(
            "--step", type=int, default=1, help="Paso del escaneo en bytes; 1 incluye bloques no alineados."
        )

    def ghidra_options(cmd: argparse.ArgumentParser) -> None:
        cmd.add_argument(
            "--ghidra-home", type=Path, help="Instalación local de Ghidra; alternativamente GHIDRA_HOME."
        )
        cmd.add_argument(
            "--loader-dir", type=Path, help="Carpeta de extensión GBA ya instalada, con extension.properties."
        )

    batch = command(
        "batch", "Preparar y analizar FE7, FE8 y variantes UPS independientes, con índice conjunto."
    )
    batch.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Raíz del proyecto; rutas del JSON relativas a esta carpeta.",
    )
    batch.add_argument("--config", type=Path, default=Path("private/fire-emblem.json"))
    batch.add_argument("--init", action="store_true", help="Crear estructura y configuración sin analizar.")
    batch.add_argument("--game", choices=["all", "fe7", "fe8"], default="all")
    batch.add_argument(
        "--all-variants",
        action="store_true",
        help="Procesar todos los UPS catalogados, incluidos los legacy.",
    )
    batch.add_argument("--catalog-only", action="store_true", help="Solo catalogar los paquetes de mods.")
    batch.add_argument("--resume", action="store_true", help="Reutilizar copias y resultados verificados.")
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument(
        "--no-scan", action="store_true", help="Identificar y aplicar UPS; omitir descompresión."
    )
    importer = command(
        "batch-import", "Copiar ZIP originales con nombres canónicos y comprobar su integridad."
    )
    importer.add_argument("--root", type=Path, default=Path.cwd())
    importer.add_argument("--fe7-rom", type=Path)
    importer.add_argument("--fe8-rom", type=Path)
    importer.add_argument("--fe7-mods", type=Path)
    importer.add_argument("--fe8-mods", type=Path)
    importer.add_argument("--dry-run", action="store_true")
    inspect = command("inspect", "Identificar ROM, ZIP o parche UPS con hashes y validación.")
    inspect.add_argument("file", type=Path)
    inspect.add_argument("--member")
    zipinfo = command("inspect-zip", "Compatibilidad: inspeccionar una ROM dentro de ZIP.")
    zipinfo.add_argument("zipfile", type=Path)
    zipinfo.add_argument("--member")
    for name in ["prepare", "prepare-zip"]:
        prepare = command(name, "Copiar una ROM validada a un destino privado y generar manifiesto.")
        if name == "prepare-zip":
            prepare.add_argument("--zip", required=True, type=Path)
            prepare.add_argument("--member")
        else:
            rom(prepare)
        prepare.add_argument(
            "--allow-unknown",
            action="store_true",
            help="Preparar una variante desconocida con cabecera válida.",
        )
        output(prepare)
    patch = command("patch", "Aplicar UPS1 con CRC de parche, base y destino.", ["apply-ups"])
    patch.add_argument("--rom", required=True, type=Path)
    patch.add_argument("--patch", required=True, type=Path)
    patch.add_argument("--direction", choices=["auto", "forward", "reverse"], default="auto")
    output(patch)
    for name in ["scan", "scan-lz10"]:
        scanner = command(
            name, "Buscar bloques comprimidos, documentar candidatos y extraer recursos privados."
        )
        rom(scanner)
        output(scanner, force=False)
        scan_options(scanner, default=100 if name == "scan-lz10" else 1000)
    extract = command("extract", "Exportar tablas documentadas a AIR, con evidencia y campos desconocidos.")
    rom(extract)
    profile(extract)
    extract.add_argument("--scan", action="store_true", help="Añadir escaneo de recursos al AIR.")
    scan_options(extract)
    output(extract)
    full = command("pipeline", "Analizar, extraer y generar AIR, CSV e informes; reanudación por hashes.")
    rom(full)
    profile(full)
    scan_options(full)
    ghidra_options(full)
    full.add_argument("--symbols", type=Path, help="JSON de símbolos importado con symbols.")
    full.add_argument(
        "--resume",
        action="store_true",
        help="Reutilizar salidas verificadas para idénticas entradas/configuración.",
    )
    full.add_argument("--no-scan", action="store_true")
    full.add_argument("--with-ghidra", action="store_true")
    output(full, force=False)
    disasm = command(
        "disasm", "Ejecutar Ghidra Headless y verificar el resumen final; integración experimental."
    )
    rom(disasm)
    ghidra_options(disasm)
    output(disasm, force=False)
    disasm.add_argument("--resume", action="store_true")
    disasm.add_argument("--start", type=number, default=0x08000000)
    disasm.add_argument("--end", type=number, default=0x0A000000)
    disasm.add_argument(
        "--batch", type=int, default=0, help="0 exporta todas; >0 limita el lote y exige reanudar."
    )
    disasm.add_argument(
        "--timeout", type=int, default=600, help="Tiempo de análisis automático por programa, segundos."
    )
    symbols = command(
        "symbols", "Importar un mapa/nm/assignments de una referencia local, registrando commit y hash."
    )
    symbols.add_argument("--reference", type=Path, required=True)
    symbols.add_argument(
        "--file",
        type=Path,
        required=True,
        help="Mapa dentro de la referencia; no se compila ni ejecuta código.",
    )
    symbols.add_argument("--rom", type=Path, help="ROM opcional para ligarlo a su SHA-256.")
    output(symbols)
    compare = command("compare", "Comparar bytes o entidades AIR sin asumir offsets idénticos.")
    compare.add_argument("--left", type=Path, required=True)
    compare.add_argument("--right", type=Path, required=True)
    compare.add_argument(
        "--air", action="store_true", help="Ambas entradas son AIR JSON, comparación por tipo/clave."
    )
    compare.add_argument("--max-ranges", type=int, default=10000)
    output(compare)
    export = command("export", "Validar y exportar AIR JSON, CSV o su esquema JSON.")
    export.add_argument("--input", type=Path)
    export.add_argument("--format", choices=["json", "csv", "schema"], default="json")
    output(export)
    report = command("report", "Generar informe Markdown o HTML local desde AIR validado.")
    report.add_argument("--input", type=Path, required=True)
    report.add_argument("--format", choices=["markdown", "html"], default="markdown")
    output(report)
    doctor = command("doctor", "Comprobar Python, esquemas y disponibilidad opcional de Ghidra.")
    ghidra_options(doctor)
    raw = command("dump", "Compatibilidad: extraer un rango binario explícito y acotado.")
    rom(raw)
    raw.add_argument("--offset", type=number, required=True)
    raw.add_argument("--size", type=number, required=True)
    output(raw)
    manifest = command(
        "inventory", "Compatibilidad: inventariar XML code2text; no contiene los binarios omitidos."
    )
    manifest.add_argument("file", type=Path)
    return parser


def _limits(args: argparse.Namespace) -> ScanLimits:
    return ScanLimits(args.max_bytes, args.budget, args.limit, args.max_candidates, args.step)


def _empty_directory(out: Path) -> None:
    for part in (out, *out.parents):
        if part.is_symlink():
            raise ValueError("Directorio de salida mediante symlink no permitido.")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("La carpeta de salida debe estar vacía o no existir.")


def _guard_output(args: argparse.Namespace) -> None:
    if not hasattr(args, "out"):
        return
    sources = [
        getattr(args, key, None)
        for key in ["rom", "patch", "input", "file", "left", "right", "tables", "symbols", "zip"]
    ]
    for source in sources:
        if isinstance(source, Path):
            protect_inputs(args.out, source)


def execute(args: argparse.Namespace) -> dict:
    cmd = args.command
    _guard_output(args)
    dry = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    if cmd == "batch-import":
        from arcanacart.batch import import_inputs

        sources = {
            key: getattr(args, key)
            for key in ["fe7_rom", "fe8_rom", "fe7_mods", "fe8_mods"]
            if getattr(args, key) is not None
        }
        return import_inputs(args.root, sources, dry_run=dry)
    if cmd == "batch":
        from arcanacart.batch import init_workspace, run_batch

        root = args.root.resolve()
        config = args.config if args.config.is_absolute() else root / args.config
        if args.init:
            return init_workspace(root, config, dry_run=dry)
        progress = (
            (lambda message: print(message, file=sys.stderr, flush=True))
            if getattr(args, "verbose", False) or sys.stderr.isatty()
            else None
        )
        return run_batch(
            root,
            config,
            game=args.game,
            all_variants=args.all_variants,
            dry_run=dry,
            catalog_only=args.catalog_only,
            resume=args.resume,
            no_scan=args.no_scan,
            progress=progress,
        )
    if cmd == "doctor":
        from arcanacart.schemas import schema

        return {
            "status": "ok",
            "version": __version__,
            "python": sys.version.split()[0],
            "core_dependencies": "stdlib-only",
            "air_schema": schema()["title"],
            "ghidra": ghidra.detect(args.ghidra_home, args.loader_dir),
            "compression": ["lz10", "rle"],
            "offline": True,
        }
    if cmd == "inventory":
        return inventory(args.file)
    if cmd == "inspect-zip":
        return inspect_zip(args.zipfile, args.member)
    if cmd == "inspect":
        if args.file.suffix.lower() == ".zip":
            return inspect_zip(args.file, args.member)
        if not args.file.is_file():
            raise ValueError("La entrada debe ser un archivo regular existente.")
        with args.file.open("rb") as stream:
            prefix = stream.read(4)
        data = read_bounded(args.file, 2 * MAX_SIZE + 1024 if prefix == b"UPS1" else MAX_SIZE, 4)
        return (
            parse_info(data)
            if data.startswith(b"UPS1")
            else header_info(data)
            if len(data) <= MAX_SIZE
            else _oversize()
        )
    if cmd in {"prepare", "prepare-zip"}:
        source = args.zip if cmd == "prepare-zip" else args.rom
        data, metadata = load_rom(source, args.member)
        if not metadata["gba_fixed_0x96"] or not metadata["header_checksum_valid"]:
            raise ValueError("Cabecera GBA inválida; prepare requiere checksum y 0x96 válidos.")
        if not args.allow_unknown and not metadata["reference"]:
            raise ValueError("SHA-1 desconocido; usa --allow-unknown para tu variante.")
        check_destination(args.out, force)
        if dry:
            return {"status": "planned", "dry_run": True, "rom": metadata}
        if source.suffix.lower() == ".zip":
            return prepare_zip(source, args.out, args.member, not args.allow_unknown, force)
        manifest = args.out.with_name(args.out.stem + ".manifest.json")
        protect_inputs(manifest, source)
        check_destination(manifest, force)
        atomic_write(args.out, data, force=force)
        atomic_json(manifest, metadata, force=force)
        return {"status": "completed", "output": str(args.out), "manifest": str(manifest), "rom": metadata}
    if cmd in {"patch", "apply-ups"}:
        return patch_file(args.rom, args.patch, args.out, direction=args.direction, force=force, dry_run=dry)
    if cmd in {"scan", "scan-lz10"}:
        _empty_directory(args.out)
        data, metadata = load_rom(args.rom, args.member)
        limits = _limits(args)
        if cmd == "scan-lz10":
            found = legacy_scan(
                data, limits.max_block_bytes, limits.max_results, limits.step, limits.max_decode_bytes
            )
            if not dry:
                args.out.mkdir(parents=True, exist_ok=True)
                for record in found:
                    blob = record.pop("_bytes")
                    record["file"] = f"lz10_{record['rom_offset'][2:]}.bin"
                    atomic_write(args.out / record["file"], blob)
                atomic_json(args.out / "manifest.json", found)
            return {
                "count": len(found),
                "dry_run": dry,
                "output": str(args.out),
                "warning": "Escaneo heurístico, limitado por presupuesto; usa scan para métricas completas.",
            }
        resources, blobs, stats = scan_resources(data, limits)
        if not dry:
            args.out.mkdir(parents=True, exist_ok=True)
            for hash_, blob in blobs.items():
                atomic_write(args.out / (hash_ + ".bin"), blob)
            atomic_json(args.out / "resources.json", {"rom": metadata, "resources": resources, "scan": stats})
        return {
            "status": "planned" if dry else "completed",
            "dry_run": dry,
            "scan": stats,
            "output": str(args.out),
        }
    if cmd in {"extract", "pipeline"}:
        tables = read_json(args.tables) if args.tables else None
        if cmd == "pipeline":
            return pipeline(
                args.rom,
                args.out,
                member=args.member,
                profile=args.profile,
                tables=tables,
                limits=_limits(args),
                scan=not args.no_scan,
                resume=args.resume,
                dry_run=dry,
                symbols=read_json(args.symbols) if args.symbols else None,
                with_ghidra=args.with_ghidra,
                ghidra_home=args.ghidra_home,
                loader_dir=args.loader_dir,
            )
        data, metadata = load_rom(args.rom, args.member)
        result, _ = analyze(
            data, metadata, profile=args.profile, tables=tables, limits=_limits(args), scan=args.scan
        )
        if not dry:
            export_json(result, args.out, force=force)
        return {
            "status": "planned" if dry else "completed",
            "entities": len(result["entities"]),
            "extractors": result["extractors"],
            "output": str(args.out),
            "dry_run": dry,
        }
    if cmd == "dump":
        data, _ = load_rom(args.rom, args.member)
        if args.offset < 0 or args.size <= 0 or args.offset + args.size > len(data):
            raise ValueError("Offset o tamaño fuera de la ROM.")
        if not dry:
            atomic_write(args.out, data[args.offset : args.offset + args.size], force=force)
        return {
            "status": "planned" if dry else "completed",
            "dry_run": dry,
            "output": str(args.out),
            "size_bytes": args.size,
        }
    if cmd == "symbols":
        rom = load_rom(args.rom)[1] if args.rom else None
        result = import_symbols(args.reference, args.file, rom=rom)
        protect_inputs(args.out, (args.reference / args.file).resolve())
        if not dry:
            atomic_json(args.out, result, force=force)
        return result
    if cmd == "compare":
        result = (
            semantic_compare(read_json(args.left), read_json(args.right))
            if args.air
            else binary_compare(load_rom(args.left)[0], load_rom(args.right)[0], args.max_ranges)
        )
        if not dry:
            atomic_json(args.out, result, force=force)
        return result
    if cmd == "disasm":
        return ghidra.run(
            args.rom,
            args.out,
            home=args.ghidra_home,
            loader_dir=args.loader_dir,
            resume=args.resume,
            start=args.start,
            end=args.end,
            batch=args.batch,
            timeout=args.timeout,
            dry_run=dry,
        )
    if cmd == "export":
        if args.format == "schema":
            if not dry:
                export_schema(args.out, force=force)
        else:
            if not args.input:
                raise ValueError("--input es obligatorio para exportar AIR.")
            result = read_json(args.input)
            validate(result)
            if not dry:
                (export_json if args.format == "json" else export_csv)(result, args.out, force=force)
        return {
            "status": "planned" if dry else "completed",
            "format": args.format,
            "output": str(args.out),
            "dry_run": dry,
        }
    if cmd == "report":
        result = read_json(args.input)
        validate(result)
        if not dry:
            write_report(result, args.out, format=args.format, force=force)
        return {
            "status": "planned" if dry else "completed",
            "format": args.format,
            "output": str(args.out),
            "dry_run": dry,
        }
    raise ValueError("Comando no implementado.")


def _oversize() -> Any:
    raise ValueError("ROM excede el máximo de 64 MiB.")


def main(argv: list[str] | None = None, *, prog: str = "arcanacart") -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        args = build_parser(prog).parse_args(arguments)
        if getattr(args, "verbose", False):
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
            logging.info("Iniciando %s: procesamiento local y síncrono.", args.command)
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 3 if result.get("status") == "partial" else 0
    except KeyboardInterrupt:
        print(
            json.dumps(
                {"status": "cancelled", "error": "Operación interrumpida; no se declara éxito."},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 130
    except (ValueError, OSError, BadZipFile, NotImplementedError, UnicodeError) as exc:
        # Machine-readable diagnostics; no stack trace or ROM bytes in normal logs.
        code = 4 if isinstance(exc, ghidra.GhidraUnavailable) else 2
        print(
            json.dumps({"status": "error", "code": code, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return code


def legacy_main(argv: list[str] | None = None) -> int:
    return main(argv, prog="feunpack")
