"""Independently implemented binary layouts, documented against pinned headers.

The layouts describe on-disk fields. They do not contain names, dialogue or assets.
FE7 PInfo/JInfo are separately checked against unit.h; FE7 Item is not yet verified.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any, Protocol

from arcanacart.core.memory import Reader

FE7_REF = "https://github.com/StanHash/fe7_us/blob/5c8b3c5e254e00f0f3458b9772c27e1a5a326e3b/include/unit.h"
FE8_REF = "https://github.com/FireEmblemUniverse/fireemblem8u/blob/f2e1f060dbe5b0cc35285df5a0f6659860644a04/include/"


@dataclass(frozen=True)
class Field:
    name: str
    offset: int
    fmt: str


class Extractor(Protocol):
    size: int
    source: str

    def parse(self, data: bytes) -> dict: ...


@dataclass(frozen=True)
class Layout:
    size: int
    fields: tuple[Field, ...]
    source: str
    unknown: tuple[str, ...]

    def parse(self, data: bytes) -> dict:
        if len(data) != self.size:
            raise ValueError("Registro de tabla truncado.")
        reader = Reader(data)
        result: dict[str, Any] = {}
        for field in self.fields:
            values = reader.unpack("<" + field.fmt, field.offset)
            result[field.name] = values[0] if len(values) == 1 else list(values)
        if "range_encoded" in result:
            value = result["range_encoded"]
            # Special ranges are interpreted by game code, not a simple min/max pair.
            result["range_min"] = value >> 4 if value not in {0, 0xFF} and (value & 0xF) != 0xF else None
            result["range_max"] = value & 0xF if value not in {0, 0xFF} and (value & 0xF) != 0xF else None
        return result


CHARACTER_FIELDS = (
    Field("name_text_id", 0, "H"),
    Field("description_text_id", 2, "H"),
    Field("number", 4, "B"),
    Field("class_id", 5, "B"),
    Field("portrait_id", 6, "H"),
    Field("mini_portrait_id", 8, "B"),
    Field("affinity", 9, "B"),
    Field("sort_order", 10, "B"),
    Field("base_level", 11, "b"),
    *(
        Field("base_" + name, 12 + i, "b")
        for i, name in enumerate(
            ["hp", "power", "skill", "speed", "defense", "resistance", "luck", "constitution"]
        )
    ),
    Field("weapon_ranks", 0x14, "8B"),
    *(
        Field("growth_" + name, 0x1C + i, "B")
        for i, name in enumerate(["hp", "power", "skill", "speed", "defense", "resistance", "luck"])
    ),
    Field("attributes", 0x28, "I"),
    Field("support_pointer", 0x2C, "I"),
)
CLASS_FIELDS = (
    Field("name_text_id", 0, "H"),
    Field("description_text_id", 2, "H"),
    Field("number", 4, "B"),
    Field("promotion_id", 5, "B"),
    Field("map_sprite_id", 6, "B"),
    Field("walk_speed", 7, "B"),
    Field("portrait_id", 8, "H"),
    Field("sort_order", 10, "B"),
    *(
        Field("base_" + name, 11 + i, "b")
        for i, name in enumerate(
            ["hp", "power", "skill", "speed", "defense", "resistance", "constitution", "movement"]
        )
    ),
    *(
        Field("max_" + name, 0x13 + i, "b")
        for i, name in enumerate(["hp", "power", "skill", "speed", "defense", "resistance", "constitution"])
    ),
    Field("relative_power", 0x1A, "b"),
    *(
        Field("growth_" + name, 0x1B + i, "b")
        for i, name in enumerate(["hp", "power", "skill", "speed", "defense", "resistance", "luck"])
    ),
    *(
        Field("promotion_bonus_" + name, 0x22 + i, "B")
        for i, name in enumerate(["hp", "power", "skill", "speed", "defense", "resistance"])
    ),
    Field("attributes", 0x28, "I"),
    Field("weapon_ranks", 0x2C, "8B"),
    Field("animation_pointer", 0x34, "I"),
    Field("movement_pointers", 0x38, "3I"),
    Field("terrain_avoid_pointer", 0x44, "I"),
    Field("terrain_defense_pointer", 0x48, "I"),
    Field("terrain_resistance_pointer", 0x4C, "I"),
    Field("unknown_50", 0x50, "I"),
)
ITEM_FIELDS = (
    Field("name_text_id", 0, "H"),
    Field("description_text_id", 2, "H"),
    Field("use_description_text_id", 4, "H"),
    Field("number", 6, "B"),
    Field("weapon_type", 7, "B"),
    Field("attributes", 8, "I"),
    Field("bonuses_pointer", 12, "I"),
    Field("effectiveness_pointer", 16, "I"),
    *(
        Field(name, 20 + i, "B")
        for i, name in enumerate(["durability", "might", "hit", "weight", "critical", "range_encoded"])
    ),
    Field("cost_per_use", 26, "H"),
    Field("required_exp", 28, "B"),
    Field("icon_id", 29, "B"),
    Field("use_effect_id", 30, "B"),
    Field("weapon_effect_id", 31, "B"),
    Field("weapon_exp", 32, "B"),
)

LAYOUTS: dict[str, dict[str, Layout]] = {
    "fe7-us": {
        "Character": Layout(
            0x34,
            CHARACTER_FIELDS
            + (
                Field("battle_palettes", 0x23, "2B"),
                Field("animation_overrides", 0x25, "2B"),
                Field("talk_tone", 0x30, "B"),
            ),
            FE7_REF,
            ("inventory", "support_relationships", "decoded_text", "recruitment", "padding"),
        ),
        "Class": Layout(
            0x54, CLASS_FIELDS, FE7_REF, ("animation", "terrain_tables", "unknown_50", "special_rules")
        ),
    },
    "fe8-us": {
        "Character": Layout(
            0x34,
            CHARACTER_FIELDS + (Field("visit_group", 0x30, "B"),),
            FE8_REF + "bmunit.h",
            ("inventory", "support_relationships", "decoded_text", "recruitment", "reserved_bytes"),
        ),
        "Class": Layout(
            0x54,
            CLASS_FIELDS,
            FE8_REF + "bmunit.h",
            ("animation", "terrain_tables", "unknown_50", "branch_promotions", "special_rules"),
        ),
        "Item": Layout(
            0x24,
            ITEM_FIELDS,
            FE8_REF + "bmitem.h",
            ("decoded_text", "bonuses", "effectiveness", "effect_logic", "padding"),
        ),
    },
}


def custom_layout(spec: dict) -> Layout:
    """Parse a declarative record layout; no expressions, imports or executable plugins."""
    if not isinstance(spec, dict) or set(spec) != {"size", "fields", "source", "unknown"}:
        raise ValueError("Layout requiere size, fields, source y unknown.")
    if type(spec["size"]) is not int or not 1 <= spec["size"] <= 65536:
        raise ValueError("Tamaño de registro fuera de rango.")
    if not isinstance(spec["source"], str) or not spec["source"].strip() or len(spec["source"]) > 2000:
        raise ValueError("El layout requiere una fuente documental.")
    if (
        not isinstance(spec["unknown"], list)
        or len(spec["unknown"]) > 128
        or any(not isinstance(x, str) or len(x) > 200 for x in spec["unknown"])
    ):
        raise ValueError("Lista de campos desconocidos inválida.")
    if not isinstance(spec["fields"], list) or not 1 <= len(spec["fields"]) <= 256:
        raise ValueError("Se requieren 1..256 campos.")
    fields: list[Field] = []
    occupied: set[int] = set()
    names: set[str] = set()
    for item in spec["fields"]:
        if not isinstance(item, dict) or set(item) != {"name", "offset", "fmt"}:
            raise ValueError("Campo requiere name, offset y fmt.")
        name, offset, fmt = item["name"], item["offset"], item["fmt"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or name in names:
            raise ValueError("Nombre de campo inválido o duplicado.")
        if not isinstance(fmt, str) or not re.fullmatch(r"(?:[1-9][0-9]{0,3})?[bBhHiI]", fmt):
            raise ValueError("fmt solo admite enteros b/B/h/H/i/I y repeticiones acotadas, little-endian.")
        size = struct.calcsize("<" + fmt)
        if name in {"number", "class_id", "promotion_id", "range_encoded"} and fmt not in {"B", "H", "I"}:
            raise ValueError("Los campos de índices y rango requieren un entero escalar sin signo.")
        if name == "range_encoded" and fmt != "B":
            raise ValueError("range_encoded describe el rango FE de un byte.")
        if type(offset) is not int or offset < 0 or offset + size > spec["size"]:
            raise ValueError("Campo fuera del registro.")
        positions = set(range(offset, offset + size))
        if positions & occupied:
            raise ValueError("Campos de layout solapados.")
        occupied.update(positions)
        names.add(name)
        fields.append(Field(name, offset, fmt))
    return Layout(spec["size"], tuple(fields), spec["source"], tuple(spec["unknown"]))


def get_layout(profile: str, kind: str, custom: dict | None = None) -> Layout:
    if custom and kind in custom:
        return custom_layout(custom[kind])
    try:
        return LAYOUTS[profile][kind]
    except KeyError as exc:
        raise ValueError(f"Extractor no disponible para {profile}/{kind}.") from exc
