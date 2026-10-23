"""Build ROM-bound table definitions from explicit offsets or local symbols."""

from __future__ import annotations

from dataclasses import asdict

from arcanacart.extractors import select_profile, validate_tables
from arcanacart.extractors.layouts import LAYOUTS
from arcanacart.integrations.symbols import validate_symbols


def layout_catalog() -> dict:
    return {
        profile: {kind: asdict(layout) for kind, layout in layouts.items()}
        for profile, layouts in LAYOUTS.items()
    }


def definition(
    rom: dict,
    profile: str,
    specs: list[str],
    evidence: list[str],
    *,
    symbols: dict | None = None,
    layouts: dict | None = None,
) -> dict:
    profile = select_profile(rom, profile)
    by_name = {}
    if symbols is not None:
        validate_symbols(symbols)
        if symbols.get("rom_sha256") not in {None, rom["sha256"]}:
            raise ValueError("El mapa de símbolos está ligado a otra ROM.")
        if symbols.get("conflicts"):
            raise ValueError("Resuelve los símbolos con direcciones contradictorias antes de usarlos.")
        by_name = {s["name"]: s["offset"] for s in symbols["symbols"]}
        evidence = [
            *evidence,
            "symbol-file-sha256:" + symbols["symbol_file_sha256"],
            "Symbol offsets remain reference-only; verify on this ROM.",
        ]
    tables = []
    for spec in specs:
        parts = spec.split(":")
        if len(parts) != 4:
            raise ValueError("Usa --table Tipo:OFFSET_O_SIMBOLO:CONTEO:PRIMER_ID.")
        kind, location, count, first_id = parts
        try:
            offset = int(location, 0)
        except ValueError:
            symbol_offset = by_name.get(location)
            if symbol_offset is None:
                raise ValueError("Offset o símbolo ROM desconocido: " + location) from None
            offset = symbol_offset
        tables.append({"kind": kind, "offset": offset, "count": int(count, 0), "first_id": int(first_id, 0)})
    result = {"profile": profile, "rom_sha256": rom["sha256"], "evidence": evidence, "tables": tables}
    if layouts is not None:
        result["layouts"] = layouts
    validate_tables(result, rom, profile)
    return result
