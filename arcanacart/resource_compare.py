"""Compare decoded candidate hashes without interpreting them as game assets."""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from typing import Any

from arcanacart.compression import normalize_methods
from arcanacart.core.io import digest


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _checked(document: dict) -> tuple[list[dict], dict, tuple[str, ...] | None]:
    if not isinstance(document, dict):
        raise ValueError("Se necesita AIR o un manifiesto resources.json.")
    rom, records, scan = (document.get(k) for k in ("rom", "resources", "scan"))
    if not isinstance(rom, dict) or not _hash(rom.get("sha256")) or not _integer(rom.get("size_bytes"), 4):
        raise ValueError("El manifiesto debe identificar la ROM por SHA-256 y tamaño.")
    if not isinstance(scan, dict) or type(scan.get("truncated")) is not bool:
        raise ValueError("El manifiesto debe registrar un escaneo y su estado truncated.")
    if not isinstance(records, list) or len(records) > 100_000:
        raise ValueError("Lista de candidatos inválida o fuera de límite.")
    declared = document.get("methods", scan.get("methods"))
    methods = None
    if declared is None and ("methods" in document or "methods" in scan):
        raise ValueError("Los métodos registrados deben ser una lista no vacía.")
    if declared is not None:
        if not isinstance(declared, list):
            raise ValueError("Los métodos del manifiesto deben ser una lista.")
        methods = normalize_methods(tuple(declared))
        if "methods" in scan:
            if not isinstance(scan["methods"], list) or normalize_methods(tuple(scan["methods"])) != methods:
                raise ValueError("El manifiesto y scan declaran métodos diferentes.")
    sizes: dict[str, int] = {}
    offsets: set[int] = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or not _hash(record.get("sha256"))
            or not _integer(record.get("offset"))
            or not _integer(record.get("compressed_bytes"), 4)
            or not _integer(record.get("decompressed_bytes"), 1)
            or record.get("compression") not in ("lz10", "rle")
            or not isinstance(record.get("references"), list)
            or len(record["references"]) > 100_000
        ):
            raise ValueError("Candidato comprimido inválido.")
        if record["offset"] + record["compressed_bytes"] > rom["size_bytes"]:
            raise ValueError("Candidato fuera de la ROM.")
        if record["offset"] in offsets:
            raise ValueError("Offset de candidato duplicado.")
        offsets.add(record["offset"])
        if methods is not None and record["compression"] not in methods:
            raise ValueError("El candidato usa un formato fuera del alcance declarado.")
        hash_, size = record["sha256"], record["decompressed_bytes"]
        if hash_ in sizes and sizes[hash_] != size:
            raise ValueError("Un mismo hash declara tamaños de salida diferentes.")
        sizes[hash_] = size
    for field, count in (("decoded_blocks", len(records)), ("unique_outputs", len(sizes))):
        if field in scan and (not _integer(scan[field]) or scan[field] != count):
            raise ValueError("Los contadores del escaneo no coinciden con los candidatos.")
    return records, scan, methods


def _uniform_hashes(records: list[dict]) -> dict[str, str]:
    """Recognize zero/FF outputs by digest; bound speculative hashing to 128 MiB."""
    patterns: dict[str, str] = {}
    used = 0
    for size in sorted({r["decompressed_bytes"] for r in records}):
        if size > 2_097_152 or used + size * 2 > 128 * 1024 * 1024:
            break
        for byte in (0, 255):
            patterns[digest(bytes([byte]) * size)] = f"{byte:02X}"
        used += size * 2
    return patterns


def compare_resources(left: dict, right: dict) -> tuple[dict, list[dict]]:
    base, base_scan, base_methods = _checked(left)
    variant, variant_scan, variant_methods = _checked(right)
    warnings = [
        "Las coincidencias se comparan por hash de salida descomprimida, aunque cambie el offset.",
        "Sin coincidencia significa no observado en los candidatos de la base; el tipo y uso siguen desconocidos.",
        "Referencias detectadas y validez estructural son evidencia heurística.",
        "Patrón uniforme identifica solo hashes conocidos de 00/FF; un valor vacío no identifica el contenido.",
    ]
    limited = bool(base_scan["truncated"] or variant_scan["truncated"])
    if limited:
        warnings.append("Algún escaneo está truncado; la comparación cubre solo los candidatos disponibles.")
    if base_methods is None or variant_methods is None or base_methods != variant_methods:
        limited = True
        warnings.append("Los formatos seleccionados difieren o no están registrados en algún informe.")
    if any(s.get("step", 1) != 1 for s in (base_scan, variant_scan)):
        limited = True
        warnings.append("Algún escaneo usa muestreo; no revisa todas las posiciones.")
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for record in base:
        by_hash[record["sha256"]].append(record)
    base_hashes, variant_hashes = set(by_hash), {r["sha256"] for r in variant}
    if any(
        r["sha256"] in by_hash and by_hash[r["sha256"]][0]["decompressed_bytes"] != r["decompressed_bytes"]
        for r in variant
    ):
        raise ValueError("Un hash compartido declara tamaños diferentes entre la base y la variante.")
    patterns = _uniform_hashes(variant)
    rows = [
        {
            "offset": r["offset"],
            "coincide_base": r["sha256"] in base_hashes,
            "referencias": len(r["references"]),
            "bytes_salida": r["decompressed_bytes"],
            "compression": r["compression"],
            "sha256": r["sha256"],
            "archivo": r["sha256"] + ".bin",
            "patron_uniforme": patterns.get(r["sha256"], ""),
        }
        for r in variant
    ]
    rows.sort(key=lambda r: (r["coincide_base"], bool(r["patron_uniforme"]), -r["referencias"], r["offset"]))
    summary = {
        "format": "arcanacart-resource-comparison-1",
        "status": "partial" if limited else "completed",
        "base_sha256": left["rom"]["sha256"],
        "variante_sha256": right["rom"]["sha256"],
        "base_methods": list(base_methods) if base_methods is not None else None,
        "variant_methods": list(variant_methods) if variant_methods is not None else None,
        "candidatos_base": len(base),
        "candidatos_variante": len(variant),
        "salidas_unicas_base": len(base_hashes),
        "salidas_unicas_variante": len(variant_hashes),
        "salidas_unicas_coincidentes": len(base_hashes & variant_hashes),
        "salidas_unicas_sin_coincidencia": len(variant_hashes - base_hashes),
        "warnings": warnings,
    }
    return summary, rows


def catalog_csv(rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=[
            "offset",
            "coincide_base",
            "referencias",
            "bytes_salida",
            "compression",
            "sha256",
            "archivo",
            "patron_uniforme",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")
