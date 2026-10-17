"""Binary differences and explicit AIR field changes; no automatic combat claims."""

from __future__ import annotations

from arcanacart.core.io import digest
from arcanacart.schemas import validate


def binary_compare(left: bytes, right: bytes, max_ranges: int = 10000) -> dict:
    if max_ranges < 1:
        raise ValueError("El límite de rangos debe ser positivo.")
    ranges: list[dict] = []
    active = None
    changed = 0
    range_count = 0
    for i in range(max(len(left), len(right))):
        differs = i >= len(left) or i >= len(right) or left[i] != right[i]
        if differs:
            changed += 1
            if active is None:
                active = i
        elif active is not None:
            if len(ranges) < max_ranges:
                ranges.append({"offset": active, "size_bytes": i - active, "interpretation": "uninterpreted"})
            range_count += 1
            active = None
    if active is not None:
        if len(ranges) < max_ranges:
            ranges.append(
                {
                    "offset": active,
                    "size_bytes": max(len(left), len(right)) - active,
                    "interpretation": "uninterpreted",
                }
            )
        range_count += 1
    return {
        "left_sha256": digest(left),
        "right_sha256": digest(right),
        "left_size": len(left),
        "right_size": len(right),
        "changed_bytes": changed,
        "denominator_bytes": max(len(left), len(right)),
        "range_count": range_count,
        "ranges_truncated": range_count > len(ranges),
        "ranges": ranges,
    }


def semantic_compare(left: dict, right: dict) -> dict:
    validate(left)
    validate(right)
    if left["profile"] != right["profile"]:
        raise ValueError("La comparación semántica requiere perfiles iguales.")

    def index(doc: dict) -> dict:
        return {
            (e["kind"], e["key"]): e for e in doc["entities"] if e["kind"] in {"Character", "Class", "Item"}
        }

    a, b = index(left), index(right)
    changes = []
    ignored = {"warnings", "pointer_evidence", "slot", "table_index"}
    for key in sorted(a.keys() | b.keys()):
        before, after = a.get(key), b.get(key)
        if before is None or after is None:
            changes.append(
                {
                    "kind": key[0],
                    "key": key[1],
                    "change": "added" if before is None else "removed",
                    "validation": "inferred",
                    "limitation": "Puede reflejar diferente cobertura de extracción.",
                }
            )
            continue
        fields = []
        for field in sorted(before["data"].keys() | after["data"].keys()):
            if field not in ignored and before["data"].get(field) != after["data"].get(field):
                fields.append(
                    {"field": field, "before": before["data"].get(field), "after": after["data"].get(field)}
                )
        if fields or before["sha256"] != after["sha256"]:
            changes.append(
                {
                    "kind": key[0],
                    "key": key[1],
                    "change": "modified",
                    "fields": fields,
                    "raw_changed": before["sha256"] != after["sha256"],
                    "left_offset": before["offset"],
                    "right_offset": after["offset"],
                    "validation": "structural"
                    if all(e["validation"] == "structural" for e in [before, after])
                    else "inferred",
                    "uninterpreted_bytes_possible": True,
                }
            )
    return {
        "profile": left["profile"],
        "changes": changes,
        "compared_keys": len(a.keys() & b.keys()),
        "limitations": [
            "Las tablas deben definirse para cada variante.",
            "No se infieren reglas de combate, eventos ni nuevas funciones.",
        ],
    }
