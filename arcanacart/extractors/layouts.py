"""Independently implemented binary layouts, documented against pinned headers.

The layouts describe on-disk fields. They do not contain names, dialogue or assets.
FE7 PInfo/JInfo are separately checked against unit.h; FE7 Item is not yet verified.
"""

from __future__ import annotations

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


def get_layout(profile: str, kind: str) -> Layout:
    try:
        return LAYOUTS[profile][kind]
    except KeyError as exc:
        raise ValueError(f"Extractor no disponible para {profile}/{kind}.") from exc
