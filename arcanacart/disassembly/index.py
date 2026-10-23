"""Document recovered code separately from known data and reference-only symbols."""

from __future__ import annotations

import copy
import re
from pathlib import Path

from arcanacart.core.io import atomic_json, atomic_write, digest, read_bounded, read_json, workspace_lock
from arcanacart.core.memory import interval_coverage
from arcanacart.integrations.symbols import validate_symbols
from arcanacart.resource_compare import _checked
from arcanacart.schemas import entity, validate


def _intersections(left: list[list[int]], right: list[list[int]]) -> list[list[int]]:
    result, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if start < end:
            result.append([start, end])
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return result


def code_index(
    source: Path,
    out: Path,
    *,
    ghidra_summary: Path | None = None,
    symbols: Path | None = None,
    dry_run: bool = False,
) -> dict:
    original = read_json(source, 64 * 1024 * 1024)
    validate(original)
    doc = copy.deepcopy(original)
    size, rom_hash = doc["rom"]["size_bytes"], doc["rom"]["sha256"]
    by_offset: dict[int, list[str]] = {}
    symbol_manifest = read_json(symbols) if symbols else None
    if symbol_manifest is not None:
        validate_symbols(symbol_manifest)
        if symbol_manifest.get("rom_sha256") not in {None, rom_hash}:
            raise ValueError("Los símbolos corresponden a otra ROM.")
        for symbol in symbol_manifest["symbols"]:
            if symbol["offset"] is not None:
                by_offset.setdefault(symbol["offset"], []).append(symbol["name"])
    export = read_json(ghidra_summary, 64 * 1024 * 1024) if ghidra_summary else None
    if export is not None:
        if (
            not isinstance(export, dict)
            or export.get("rom_sha256") != rom_hash
            or export.get("status") not in {"completed", "partial"}
            or not isinstance(export.get("functions"), list)
            or len(export["functions"]) > 100_000
        ):
            raise ValueError("Resumen Ghidra inválido, incompleto o de otra ROM.")
    for path in (out, *out.parents):
        if path.is_symlink():
            raise ValueError("La salida no puede usar symlinks.")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("El índice de código requiere una salida nueva y vacía.")
    for source_path in (source, ghidra_summary, symbols):
        if source_path and source_path.resolve().is_relative_to(out.resolve()):
            raise ValueError("La salida contiene una entrada; elige otra carpeta.")
    known_data = [
        (e["offset"], e["size_bytes"])
        for e in doc["entities"]
        if e["offset"] is not None and e["kind"] != "Function" and e["size_bytes"]
    ]
    # Resource manifests may contain candidates without corresponding AIR Asset records.
    if doc["resources"]:
        records, _, _ = _checked(doc)
        known_data.extend((r["offset"], r["compressed_bytes"]) for r in records)
    data_coverage = interval_coverage(known_data, size)
    if dry_run:
        return {
            "status": "planned",
            "rom_sha256": rom_hash,
            "ghidra_provided": export is not None,
            "output": str(out),
        }
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    with workspace_lock(out):
        atomic_json(out / "code-state.json", {"status": "running"})
        try:
            functions, code_ranges, errors, seen = [], [], [], set()
            total_bytes = 0
            doc["entities"] = [e for e in doc["entities"] if e["kind"] != "Function"]
            for record in export["functions"] if export else []:
                try:
                    if (
                        not isinstance(record, dict)
                        or not isinstance(record.get("address"), str)
                        or not re.fullmatch(r"[0-9a-fA-F]{8}", record["address"])
                    ):
                        raise ValueError("Dirección de función inválida.")
                    key = record["address"]
                    address = int(key, 16)
                    if address in seen or not 0x08000000 <= address < 0x08000000 + min(size, 0x2000000):
                        raise ValueError("Función duplicada o fuera de ROM.")
                    seen.add(address)
                    if record.get("rom_sha256") != rom_hash or record.get("status") not in {
                        "completed",
                        "failed",
                    }:
                        raise ValueError("Procedencia o estado de función inválido.")
                    if not isinstance(record.get("name"), str) or len(record["name"]) > 2000:
                        raise ValueError("Nombre de función inválido.")
                    ranges = record.get("instruction_ranges", [])
                    if not isinstance(ranges, list) or len(ranges) > 100_000:
                        raise ValueError("Rangos de instrucciones inválidos.")
                    function_ranges = []
                    for region in ranges:
                        if (
                            not isinstance(region, list)
                            or len(region) != 2
                            or any(type(n) is not int for n in region)
                            or not 0x08000000 <= region[0] < region[1] <= 0x08000000 + min(size, 0x2000000)
                        ):
                            raise ValueError("Rango de instrucciones fuera de ROM.")
                        function_ranges.append((region[0] - 0x08000000, region[1] - region[0]))
                    files = []
                    for field, extension in (("assembly", ".s"), ("pseudocode", ".c")):
                        if field == "pseudocode" and record["status"] != "completed":
                            continue
                        if record.get(field) != key + extension:
                            raise ValueError("Nombre de exportación de función inválido.")
                        path = ghidra_summary.parent / (key + extension)  # type: ignore[union-attr]
                        if path.is_symlink():
                            raise ValueError("Exportación mediante symlink rechazada.")
                        raw = read_bounded(path, 16 * 1024 * 1024)
                        total_bytes += len(raw)
                        if total_bytes > 512 * 1024 * 1024:
                            raise ValueError("El índice supera su cuota de exportación de 512 MiB.")
                        if record.get(field + "_sha256") != digest(raw):
                            raise ValueError("Hash de exportación incorrecto: " + key + extension)
                        files.append(("functions/" + key + extension, raw))
                    for filename, raw in files:
                        atomic_write(out / filename, raw)
                    offset = address - 0x08000000
                    item = {
                        **record,
                        "offset": offset,
                        "reference_names": by_offset.get(offset, []),
                        "validation": "structural-export",
                        "instruction_ranges_available": bool(ranges),
                    }
                    functions.append(item)
                    code_ranges.extend(function_ranges)
                    doc["entities"].append(
                        entity(
                            "Function",
                            doc["rom"],
                            doc["profile"],
                            key,
                            offset=offset,
                            size=0,
                            parser="ghidra-recovered-function",
                            data=item,
                            evidence=["rom-bound-ghidra-export", "verified-assembly-sha256"],
                            validation="inferred",
                            confidence="heuristic",
                            unknown=["original_source", "semantic_equivalence"],
                        )
                    )
                except (OSError, ValueError) as exc:
                    errors.append(str(exc))
            code_coverage = interval_coverage(code_ranges, size)
            overlap = _intersections(data_coverage["classified_ranges"], code_coverage["classified_ranges"])
            combined = interval_coverage(known_data + code_ranges, size)
            result = {
                "format": "arcanacart-code-index-1",
                "rom_sha256": rom_hash,
                "status": "completed"
                if export and export["status"] == "completed" and not errors and not overlap
                else "partial",
                "recovered_functions": len(functions),
                "reference_symbols": len(symbol_manifest["symbols"]) if symbol_manifest else 0,
                "code_bytes": code_coverage["classified_bytes"],
                "data_or_candidate_bytes": data_coverage["classified_bytes"],
                "code_ranges": code_coverage["classified_ranges"],
                "data_ranges": data_coverage["classified_ranges"],
                "conflicting_ranges": overlap,
                "unknown_bytes": combined["unknown_bytes"],
                "unknown_ranges": combined["unknown_ranges"],
                "errors": errors,
                "limitations": [
                    "Funciones y assembly recuperados no son código fuente original ni una reconstrucción recompilable.",
                    "Los símbolos locales son pistas; no añaden bytes a la cobertura de código.",
                    "Datos incluye candidatos comprimidos; los solapamientos requieren revisión.",
                    "Exportaciones antiguas sin instruction_ranges conservan sus funciones, pero no inventan rangos contiguos.",
                    "Sin resumen Ghidra no se ha ejecutado ningún desensamblador.",
                ],
            }
            doc["coverage"]["code_index"] = result
            doc["stages"].append({"name": "code-index", "status": result["status"]})
            atomic_json(out / "air.json", doc)
            atomic_json(out / "code-map.json", result)
            atomic_json(out / "functions.json", functions)
            from arcanacart.reporting import write_report

            write_report(doc, out / "report.html", format="html")
            write_report(doc, out / "report.md")
            atomic_json(
                out / "code-state.json",
                {"status": result["status"], "recovered_functions": len(functions)},
                force=True,
            )
            return {**result, "output": str(out)}
        except Exception as exc:
            atomic_json(out / "code-state.json", {"status": "failed", "error": str(exc)}, force=True)
            raise
