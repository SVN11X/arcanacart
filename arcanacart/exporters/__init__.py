"""AIR JSON/CSV exchange, separate from target-engine campaign formats."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from arcanacart.core.io import atomic_json, atomic_write
from arcanacart.schemas import schema, validate


def export_json(document: dict, out: Path, *, force: bool = False) -> None:
    validate(document)
    atomic_json(out, document, force=force)


def export_csv(document: dict, out: Path, *, force: bool = False) -> None:
    validate(document)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["id", "kind", "key", "offset", "validation", "sha256", "data_json", "unknown_fields"])
    for record in document["entities"]:
        cells = [record[k] for k in ["id", "kind", "key", "offset", "validation", "sha256"]]
        cells.extend(
            [
                json.dumps(record["data"], ensure_ascii=False, sort_keys=True),
                ", ".join(record["unknown_fields"]),
            ]
        )
        # Protect text fields opened by spreadsheet applications from formula execution.
        writer.writerow(
            [
                "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in cells
            ]
        )
    atomic_write(out, stream.getvalue().encode("utf-8"), force=force)


def export_schema(out: Path, *, force: bool = False) -> None:
    atomic_json(out, schema(), force=force)


def target_compatibility(document: dict) -> dict:
    return {
        "air": True,
        "json": True,
        "csv": True,
        "ltmaker_project": False,
        "ltmaker_compatible_entities_verified": 0,
        "reason": "No se ha validado una versión ni campaña .ltproj en LT-Maker.",
        "candidate_entity_types": sorted(
            {e["kind"] for e in document["entities"]} & {"Character", "Class", "Item"}
        ),
        "requires_adaptation": ["IDs", "rules", "assets", "events", "progression"],
    }
