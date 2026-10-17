"""Import simple nm/map, linker assignments and FE-CLib SET_DATA/SET_FUNC files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from arcanacart.core.io import digest, read_bounded
from arcanacart.core.memory import resolve

NAME = r"[A-Za-z_.$][A-Za-z0-9_.$]*"
PATTERNS = [
    re.compile(
        r"^\s*(?:SET_(?:DATA|FUNC)|\.equ|\.set)\s+(" + NAME + r")\s*,\s*(0x[0-9a-fA-F]+)\s*(?:$|[@;#/])"
    ),
    re.compile(r"^\s*(" + NAME + r")\s*=\s*(0x[0-9a-fA-F]+)\s*;?\s*(?:$|[/#])"),
    re.compile(r"^\s*(?:0x)?([0-9a-fA-F]{7,8})\s+(?:[A-Za-z]\s+)?(" + NAME + r")\s*$"),
]


def import_symbols(reference: Path, symbol_file: Path, *, rom: dict | None = None) -> dict:
    root = reference.resolve()
    path = (root / symbol_file).resolve() if not symbol_file.is_absolute() else symbol_file.resolve()
    if not root.is_dir() or not path.is_relative_to(root):
        raise ValueError("El mapa de símbolos debe estar dentro de la referencia local.")
    raw = read_bounded(path, 16 * 1024 * 1024)
    text = raw.decode("utf-8-sig")
    symbols = []
    errors = []
    seen: dict[str, int] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        for index, pattern in enumerate(PATTERNS):
            match = pattern.match(line)
            if match is None:
                continue
            name, address = (match[1], int(match[2], 16)) if index < 2 else (match[2], int(match[1], 16))
            if name in seen:
                if seen[name] != address:
                    errors.append({"line": line_number, "symbol": name, "error": "conflicting-address"})
                break
            seen[name] = address
            try:
                target = resolve(
                    address,
                    rom["size_bytes"] if rom else 0x2000000,
                    kind="function" if address & 1 else "data",
                )
                region, offset = target.region, target.file_offset
            except ValueError:
                region, offset = "unmapped", None
            symbols.append(
                {
                    "name": name,
                    "address": address,
                    "offset": offset,
                    "region": region,
                    "line": line_number,
                    "validation": "reference-only",
                }
            )
            break
    commit = None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and re.fullmatch("[0-9a-f]{40,64}", proc.stdout.strip()):
            commit = proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "format": "arcanacart-symbols-1",
        "reference_name": root.name,
        "symbol_file": path.relative_to(root).as_posix(),
        "symbol_file_sha256": digest(raw),
        "reference_commit": commit,
        "working_tree_matches_commit": None,
        "rom_sha256": rom["sha256"] if rom else None,
        "symbols": symbols,
        "count": len(symbols),
        "conflicts": errors,
        "limitations": [
            "Una dirección importada no prueba equivalencia de función o código.",
            "El hash del mapa identifica sus bytes incluso si la copia local tiene cambios.",
        ],
    }


def correlate(symbols: dict, entities: list[dict]) -> dict:
    validate_symbols(symbols)
    by_offset: dict[int, list[str]] = {}
    for symbol in symbols["symbols"]:
        if symbol["offset"] is not None:
            by_offset.setdefault(symbol["offset"], []).append(symbol["name"])
    matches = [
        {
            "entity": e["id"],
            "offset": e["offset"],
            "names": by_offset[e["offset"]],
            "validation": "inferred",
            "evidence": "same-offset-in-reference",
        }
        for e in entities
        if e["offset"] in by_offset
    ]
    return {
        "symbol_count": symbols["count"],
        "entity_count": len(entities),
        "same_offset_matches": matches,
        "verified_function_matches": 0,
        "reference_commit": symbols["reference_commit"],
        "symbol_file_sha256": symbols["symbol_file_sha256"],
    }


def validate_symbols(value: dict) -> None:
    if not isinstance(value, dict) or value.get("format") != "arcanacart-symbols-1":
        raise ValueError("Formato de símbolos inválido; usa arcanacart symbols.")
    symbols = value.get("symbols")
    if not isinstance(symbols, list) or len(symbols) > 200000 or value.get("count") != len(symbols):
        raise ValueError("Lista o conteo de símbolos inválido.")
    for record in symbols:
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            raise ValueError("Registro de símbolos inválido.")
        if record.get("offset") is not None and (
            type(record["offset"]) is not int or not 0 <= record["offset"] < 0x2000000
        ):
            raise ValueError("Offset de símbolo fuera de la ventana ROM.")
    for key in ["reference_commit", "symbol_file_sha256", "rom_sha256"]:
        if key not in value:
            raise ValueError("Procedencia del mapa de símbolos incompleta.")
