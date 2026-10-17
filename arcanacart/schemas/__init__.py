"""AIR 1.0: versioned interchange records and dependency-free schema validation."""

from __future__ import annotations

import math
import re
from importlib.resources import files
from typing import Any

from arcanacart import __version__
from arcanacart.core.io import digest, json_bytes

SCHEMA_VERSION = "1.0.0"
KINDS = [
    "Game",
    "ROMVariant",
    "Character",
    "Class",
    "Item",
    "Weapon",
    "Skill",
    "Chapter",
    "Map",
    "Terrain",
    "Unit",
    "Event",
    "Dialogue",
    "Animation",
    "Asset",
    "Function",
    "Reference",
]


def schema() -> dict:
    import json

    return json.loads(files(__package__).joinpath("air.schema.json").read_text(encoding="utf-8"))


def _validate(value: Any, rule: dict, root: dict, path: str = "$", depth: int = 0) -> None:
    if depth > 40:
        raise ValueError("AIR excede profundidad segura.")
    if "$ref" in rule:
        target: Any = root
        for part in rule["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        _validate(value, target, root, path, depth + 1)
        return
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        "boolean": isinstance(value, bool),
    }
    expected = rule.get("type", [])
    if isinstance(expected, str):
        expected = [expected]
    if expected and not any(matches[t] for t in expected):
        raise ValueError(f"{path}: tipo AIR incorrecto; esperado {expected}.")
    if "const" in rule and value != rule["const"] or "enum" in rule and value not in rule["enum"]:
        raise ValueError(f"{path}: valor AIR no permitido.")
    if isinstance(value, dict):
        if set(rule.get("required", [])) - value.keys():
            raise ValueError(f"{path}: faltan campos AIR obligatorios.")
        properties = rule.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], root, path + "." + key, depth + 1)
            elif rule.get("additionalProperties") is False:
                raise ValueError(f"{path}: campo AIR desconocido: {key}.")
            elif isinstance(rule.get("additionalProperties"), dict):
                _validate(item, rule["additionalProperties"], root, path + "." + key, depth + 1)
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", 100_000):
            raise ValueError(f"{path}: longitud AIR fuera de rango.")
        if rule.get("uniqueItems") and len({json_bytes(v) for v in value}) != len(value):
            raise ValueError(f"{path}: valores AIR duplicados.")
        for index, item in enumerate(value):
            if "items" in rule:
                _validate(item, rule["items"], root, f"{path}[{index}]", depth + 1)
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", 1_000_000):
            raise ValueError(f"{path}: cadena AIR fuera de rango.")
        if "pattern" in rule and not re.search(rule["pattern"], value):
            raise ValueError(f"{path}: formato AIR inválido.")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if (
            not math.isfinite(value)
            or value < rule.get("minimum", -math.inf)
            or value > rule.get("maximum", math.inf)
        ):
            raise ValueError(f"{path}: número AIR fuera de rango.")


def validate(document: dict) -> None:
    """Validate the bundled schema vocabulary, plus cross-record consistency."""
    stack = [(document, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 32:
            raise ValueError("AIR excede profundidad segura.")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("AIR requiere claves de texto JSON.")
            stack.extend((value, depth + 1) for value in item.values())
        elif isinstance(item, list):
            stack.extend((value, depth + 1) for value in item)
        elif (
            not isinstance(item, (str, int, float, bool, type(None)))
            or isinstance(item, float)
            and not math.isfinite(item)
        ):
            raise ValueError("AIR contiene un valor no serializable a JSON.")
    root = schema()
    _validate(document, root, root)
    ids = [entity["id"] for entity in document["entities"]]
    if len(ids) != len(set(ids)):
        raise ValueError("AIR contiene IDs duplicados.")
    id_set = set(ids)
    for entity in document["entities"]:
        if entity["variant"] != document["rom"]["sha256"] or entity["game"] != document["profile"]:
            raise ValueError("AIR mezcla procedencias de variantes o juegos.")
        offset = entity["offset"]
        if offset is not None and offset + entity["size_bytes"] > document["rom"]["size_bytes"]:
            raise ValueError("AIR: entidad fuera de ROM.")
        for reference in entity["references"]:
            if reference not in id_set:
                raise ValueError("AIR contiene referencia a entidad inexistente.")


def entity(
    kind: str,
    rom: dict,
    profile: str,
    key: str,
    *,
    offset: int | None = None,
    size: int = 0,
    parser: str,
    data: dict,
    evidence: list[str],
    validation: str = "structural",
    confidence: str = "documented",
    sha256: str | None = None,
    unknown: list[str] | None = None,
) -> dict:
    identity = digest(json_bytes([profile, rom["sha256"], kind, key, offset]))
    return {
        "id": "air:" + identity,
        "kind": kind,
        "key": key,
        "game": profile,
        "variant": rom["sha256"],
        "schema_version": SCHEMA_VERSION,
        "address": 0x08000000 + offset if offset is not None and offset < 0x2000000 else None,
        "offset": offset,
        "size_bytes": size,
        "parser": parser,
        "extractor_version": __version__,
        "sha256": sha256,
        "evidence": evidence,
        "references": [],
        "validation": validation,
        "confidence": confidence,
        "unknown_fields": unknown or [],
        "data": data,
    }


def document(rom: dict, profile: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "arcanacart",
        "tool_version": __version__,
        "profile": profile,
        "rom": rom,
        "entities": [],
        "extractors": [],
        "resources": [],
        "scan": {},
        "coverage": {},
        "stages": [],
        "warnings": [],
        "errors": [],
    }
