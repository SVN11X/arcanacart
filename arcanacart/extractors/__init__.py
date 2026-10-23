"""Hash-bound table extraction; never inherit vanilla addresses in an unknown hack."""

from __future__ import annotations

from dataclasses import asdict

from arcanacart.core.io import digest
from arcanacart.core.memory import Reader, resolve
from arcanacart.schemas import KINDS, entity

from .layouts import LAYOUTS, get_layout


def select_profile(rom: dict, requested: str = "auto") -> str:
    known = (rom.get("reference") or {}).get("profile")
    if requested == "auto":
        return known or "generic-gba"
    if requested not in {*LAYOUTS, "generic-gba"}:
        raise ValueError("Perfil desconocido; disponibles: auto, generic-gba, fe7-us, fe8-us.")
    if known and requested not in {known, "generic-gba"}:
        raise ValueError("El perfil seleccionado contradice el hash de referencia de la ROM.")
    return requested


def validate_tables(config: dict, rom: dict, profile: str) -> None:
    required = {"profile", "rom_sha256", "evidence", "tables"}
    if not isinstance(config, dict) or not required <= config.keys() or set(config) - required - {"layouts"}:
        raise ValueError("Definición de tablas requiere profile, rom_sha256, evidence y tables.")
    if config["rom_sha256"] != rom["sha256"] or config["profile"] != profile:
        raise ValueError("Las tablas no corresponden al SHA-256/perfil de esta ROM.")
    if (
        not isinstance(config["evidence"], list)
        or not config["evidence"]
        or any(not isinstance(x, str) or not x for x in config["evidence"])
    ):
        raise ValueError("Las tablas requieren evidencia de procedencia.")
    if not isinstance(config["tables"], list) or len(config["tables"]) > 256:
        raise ValueError("Lista de tablas inválida o excesiva.")
    custom = config.get("layouts", {})
    if not isinstance(custom, dict) or len(custom) > 32:
        raise ValueError("layouts debe ser un objeto de hasta 32 definiciones.")
    for kind in custom:
        if kind not in KINDS or kind in {"Game", "ROMVariant", "Function"}:
            raise ValueError("Tipo de tabla personalizada no permitido.")
        get_layout(profile, kind, custom)
    keys = set()
    total = 0
    ranges = []
    for table in config["tables"]:
        if not isinstance(table, dict) or set(table) != {"kind", "offset", "count", "first_id"}:
            raise ValueError("Cada tabla requiere kind, offset, count y first_id.")
        if any(type(table[n]) is not int or table[n] < 0 for n in ["offset", "count", "first_id"]):
            raise ValueError("Offsets, conteos e índices deben ser enteros no negativos.")
        if table["count"] < 1:
            raise ValueError("La tabla debe contener al menos un registro.")
        if not isinstance(table["kind"], str):
            raise ValueError("El tipo de tabla debe ser una cadena.")
        layout = get_layout(profile, table["kind"], custom)
        total += table["count"]
        if total > 50_000 or table["offset"] + layout.size * table["count"] > rom["size_bytes"]:
            raise ValueError("Tabla fuera de ROM o excede presupuesto de 50000 registros.")
        key = table["kind"]
        if key in keys:
            raise ValueError("Definiciones de tabla duplicadas para el mismo tipo.")
        keys.add(key)
        ranges.append((table["offset"], table["offset"] + layout.size * table["count"]))
    for left, right in zip(sorted(ranges), sorted(ranges)[1:], strict=False):
        if left[1] > right[0]:
            raise ValueError("Las tablas declaradas se solapan; revisa sus rangos.")


def extract_tables(
    data: bytes, rom: dict, profile: str, config: dict | None
) -> tuple[list[dict], list[dict]]:
    if config is None:
        return [], [
            {
                "parser": "fe-tables",
                "status": "skipped",
                "entities": 0,
                "reason": "Se requieren ubicaciones y conteos documentados, ligados al SHA-256 (--tables).",
            }
        ]
    validate_tables(config, rom, profile)
    reader = Reader(data)
    entities: list[dict] = []
    statuses = []
    known_variant = (rom.get("reference") or {}).get("profile") == profile
    config_hash = digest(__import__("json").dumps(config, sort_keys=True).encode())
    for table in config["tables"]:
        kind = table["kind"]
        custom = config.get("layouts", {})
        layout = get_layout(profile, kind, custom)
        mismatches = 0
        invalid_pointers = 0
        for index in range(table["count"]):
            offset = table["offset"] + index * layout.size
            raw = reader.read(offset, layout.size)
            parsed = layout.parse(raw)
            expected_id = table["first_id"] + index
            actual_id = parsed.get("number")
            warnings = []
            if actual_id is not None and actual_id not in {
                0,
                expected_id if kind in custom else expected_id & 0xFF,
            }:
                mismatches += 1
                warnings.append(
                    "ID interno no coincide con el índice declarado; revisar ubicación o variante."
                )
            pointer_evidence = []
            for name, value in parsed.items():
                if not name.endswith(("_pointer", "_pointers")) or not value:
                    continue
                for pointer in value if isinstance(value, list) else [value]:
                    if not pointer:
                        continue
                    try:
                        target = asdict(resolve(pointer, len(data)))
                        pointer_evidence.append(
                            {"field": name, "raw": pointer, "target": target, "status": "structural"}
                        )
                    except ValueError:
                        invalid_pointers += 1
                        pointer_evidence.append({"field": name, "raw": pointer, "status": "invalid"})
                        warnings.append(f"Puntero inválido en {name}.")
            parsed.update(
                table_index=expected_id, slot=index, warnings=warnings, pointer_evidence=pointer_evidence
            )
            entities.append(
                entity(
                    kind,
                    rom,
                    profile,
                    str(expected_id),
                    offset=offset,
                    size=layout.size,
                    parser=profile + "/" + kind,
                    data=parsed,
                    sha256=digest(raw),
                    evidence=[
                        layout.source,
                        "table-definition-sha256:" + config_hash,
                        "bounded-little-endian-read",
                        *config["evidence"],
                    ],
                    validation="structural"
                    if known_variant and kind not in custom and not warnings
                    else "inferred",
                    confidence="documented" if known_variant and kind not in custom else "heuristic",
                    unknown=list(layout.unknown),
                )
            )
        statuses.append(
            {
                "parser": profile + "/" + kind,
                "status": "partial" if mismatches or invalid_pointers else "completed",
                "records_declared": table["count"],
                "entities": table["count"],
                "id_mismatches": mismatches,
                "invalid_pointers": invalid_pointers,
                "layout_source": layout.source,
                "custom_layout": kind in custom,
                "definition_sha256": config_hash,
                "limitations": list(layout.unknown),
                "validated_on_commercial_rom": False,
            }
        )
    # Resolve only references for entities that are actually present; keep absent IDs explicit.
    by_key = {(e["kind"], e["key"]): e["id"] for e in entities}
    for record in entities:
        relation: tuple[str, str] | None = None
        if record["kind"] == "Character" and "class_id" in record["data"]:
            relation = ("Class", str(record["data"]["class_id"]))
        elif record["kind"] == "Class" and record["data"].get("promotion_id"):
            relation = ("Class", str(record["data"]["promotion_id"]))
        if relation and relation in by_key:
            record["references"].append(by_key[relation])
    return entities, statuses
