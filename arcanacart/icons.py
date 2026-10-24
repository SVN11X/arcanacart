"""Bounded, ROM-bound extraction of the raw FE item-icon bank; never a scanner."""

from __future__ import annotations

import csv
import io
import json
import struct
from pathlib import Path

from arcanacart import __version__, graphics
from arcanacart.core.io import atomic_json, atomic_write, digest, json_bytes, read_bounded, workspace_lock
from arcanacart.faces import FE7_SHA256, FE8_SHA256
from arcanacart.pipeline import load_rom
from arcanacart.resource_compare import _checked
from arcanacart.schemas import validate

FORMAT = "arcanacart-item-icon-layout-1"
ICON_BYTES = 128
MAX_ICONS = 4096
FEBUILDER = (
    "https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/"
)
FE8_DECOMP = (
    "https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/"
)


def _builtin(game: str, rom_hash: str, table: int, pointer: int, palette_pointer: int, count: int) -> dict:
    return {
        "format": FORMAT,
        "rom_sha256": rom_hash,
        "game": game,
        "table_offset": table,
        "pointer_location": pointer,
        "first_id": 0,
        "icon_count": count,
        "icon_bytes": ICON_BYTES,
        "palette_offset": None,
        "palette_pointer_location": palette_pointer,
        "sources": [FEBUILDER + "ROM" + game.upper() + "U.cs", FEBUILDER + "ImageItemIconForm.cs"],
    }


# Inclusive last IDs: AC and DF. FEBuilder's GetIconMax is a maximum
# INDEX, not a count. Unknown hashes never inherit these locations or bounds.
BUILTIN_LAYOUTS = {
    FE7_SHA256: _builtin("fe7", FE7_SHA256, 0xC5EA4, 0x4E20, 0x4D40, 0xAD),
    FE8_SHA256: _builtin("fe8", FE8_SHA256, 0x5926F4, 0x36B4, 0x35D0, 0xE0),
}
BUILTIN_LAYOUTS[FE8_SHA256]["sources"] += [FE8_DECOMP + "src/icon.c", FE8_DECOMP + "include/icon.h"]


def _safe(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("No se admiten rutas mediante enlaces simbólicos.")


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _pointer(data: bytes, location: int, length: int) -> int:
    value = struct.unpack_from("<I", data, location)[0]
    if not 0x08000000 <= value < 0x0E000000:
        raise ValueError("El puntero de iconos/paleta no apunta a una ventana ROM GBA.")
    offset = (value - 0x08000000) % 0x02000000
    if offset + length > len(data):
        raise ValueError("El puntero de iconos/paleta excede el tamaño de esta ROM.")
    return offset


def checked_layout(value: dict, rom: dict, data: bytes) -> dict:
    required = set(BUILTIN_LAYOUTS[FE7_SHA256])
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("format") != FORMAT
        or value.get("rom_sha256") != rom["sha256"]
        or not isinstance(value.get("game"), str)
        or value["game"] not in {"fe7", "fe8"}
        or type(value.get("icon_bytes")) is not int
        or value["icon_bytes"] != ICON_BYTES
        or not _integer(value.get("first_id"), 0, 65535)
        or not _integer(value.get("icon_count"), 1, MAX_ICONS)
        or value["first_id"] + value["icon_count"] > 65536
        or not _integer(value.get("table_offset"), 0, len(data) - ICON_BYTES)
        or value["table_offset"] + value["icon_count"] * ICON_BYTES > len(data)
        or not isinstance(value.get("sources"), list)
        or not 1 <= len(value["sources"]) <= 16
        or any(not isinstance(s, str) or not s.strip() or len(s) > 2000 for s in value["sources"])
    ):
        raise ValueError("Definición de iconos inválida, fuera de rango o ligada a otra ROM.")
    profile = (rom.get("reference") or {}).get("profile")
    if profile in {"fe7-us", "fe8-us"} and value["game"] != profile[:3]:
        raise ValueError("El juego declarado contradice la identidad exacta de la ROM.")
    result = dict(value)
    for name in ("pointer_location", "palette_pointer_location"):
        location = result[name]
        if location is not None and not _integer(location, 0, len(data) - 4):
            raise ValueError("Ubicación de puntero fuera de la ROM.")
    if result["pointer_location"] is not None:
        if (
            _pointer(data, result["pointer_location"], result["icon_count"] * ICON_BYTES)
            != result["table_offset"]
        ):
            raise ValueError("El puntero de iconos no coincide con la tabla declarada.")
    palette_offset = result["palette_offset"]
    if palette_offset is not None and not _integer(palette_offset, 0, len(data) - 32):
        raise ValueError("Paleta fuera de la ROM.")
    if result["palette_pointer_location"] is not None:
        pointed = _pointer(data, result["palette_pointer_location"], 32)
        if palette_offset is not None and pointed != palette_offset:
            raise ValueError("El puntero de paleta no coincide con la definición.")
        palette_offset = pointed
    if palette_offset is None:
        raise ValueError("Se requiere un offset de paleta o un puntero documentado.")
    result["palette_offset"] = palette_offset
    start, end = result["table_offset"], result["table_offset"] + result["icon_count"] * ICON_BYTES
    if start < palette_offset + 32 and palette_offset < end:
        raise ValueError("El rango de iconos se solapa con la paleta declarada.")
    return result


def _json_file(path: Path, limit: int) -> tuple[dict, str]:
    raw = read_bounded(path, limit)
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except RecursionError as exc:
        raise ValueError("JSON excede profundidad segura.") from exc
    if not isinstance(value, dict):
        raise ValueError("Se requiere un objeto JSON.")
    return value, digest(raw)


def _csv(rows: list[dict], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def extract_icons(
    rom_path: Path,
    out: Path,
    *,
    source: Path | None = None,
    definition: Path | None = None,
    first_id: int | None = None,
    last_id: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Read only declared raw icon slots and palette; hash the ROM without scanning it."""
    inputs = [rom_path, *([source] if source else []), *([definition] if definition else [])]
    for path in [out, *inputs]:
        _safe(path)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("Elige una carpeta de salida nueva y vacía.")
    if any(p.resolve().is_relative_to(out.resolve()) for p in inputs):
        raise ValueError("La salida debe estar separada de las entradas.")
    data, rom = load_rom(rom_path)
    definition_file_hash = None
    automatic = definition is None
    if definition:
        spec, definition_file_hash = _json_file(definition, 1024 * 1024)
    else:
        automatic_spec = BUILTIN_LAYOUTS.get(rom["sha256"])
        if automatic_spec is None:
            raise ValueError(
                "La extracción automática requiere la base FE7/FE8 USA exacta. "
                "Una variante necesita --definition ligada a su SHA-256 y a un rango revisado."
            )
        spec = automatic_spec
    layout = checked_layout(spec, rom, data)
    low, high = layout["first_id"], layout["first_id"] + layout["icon_count"] - 1
    first_id = low if first_id is None else first_id
    last_id = high if last_id is None else last_id
    if not _integer(first_id, low, high) or not _integer(last_id, first_id, high):
        raise ValueError("Los IDs solicitados exceden el rango documentado de esta definición.")
    records: list[dict] = []
    source_hash = None
    scan = None
    if source:
        document, source_hash = _json_file(source, 64 * 1024 * 1024)
        records, scan, _ = _checked(document)
        if "schema_version" in document:
            validate(document)
        if document["rom"]["sha256"] != rom["sha256"] or document["rom"]["size_bytes"] != len(data):
            raise ValueError("El AIR no corresponde a los bytes exactos de esta ROM.")
    palette_raw = data[layout["palette_offset"] : layout["palette_offset"] + 32]
    palette_hash = digest(palette_raw)
    colors = graphics.palette(palette_raw)
    payloads = {"paletas/" + palette_hash + ".bin": palette_raw}
    rows = []
    for icon_id in range(first_id, last_id + 1):
        offset = layout["table_offset"] + (icon_id - low) * ICON_BYTES
        raw = data[offset : offset + ICON_BYTES]
        raw_hash = digest(raw)
        width, height, rgba = graphics.tiles(raw, bpp=4, width_tiles=2, colors=colors, transparent_zero=True)
        image = graphics.png(width, height, rgba)
        png_hash = digest(image)
        png_file, raw_file = "imagenes/" + png_hash + ".png", "raw/" + raw_hash + ".bin"
        payloads[png_file], payloads[raw_file] = image, raw
        rows.append(
            {
                "game": layout["game"],
                "kind": "item-icon",
                "icon_id": icon_id,
                "icon_id_hex": f"0x{icon_id:02X}",
                "source_offset": offset,
                "size_bytes": ICON_BYTES,
                "compression": "none",
                "source_sha256": raw_hash,
                "raw_file": raw_file,
                "png_sha256": png_hash,
                "file": png_file,
                "width": width,
                "height": height,
                "visible": any(raw),
                "palette_offset": layout["palette_offset"],
                "palette_sha256": palette_hash,
                "palette_file": "paletas/" + palette_hash + ".bin",
                "rom_sha256": rom["sha256"],
                "air_sha256": source_hash,
                "data_origin": "local-rom-raw",
                "review": "unreviewed",
            }
        )
    unique_images = {r["png_sha256"] for r in rows}
    summary = {
        "format": "arcanacart-item-icon-catalog-1",
        "status": "completed",
        "tool_version": __version__,
        "game": layout["game"],
        "rom_sha256": rom["sha256"],
        "rom_size_bytes": len(data),
        "rom_source_name": rom_path.name,
        "rom_bytes_verified": True,
        "definition_origin": "builtin-exact-rom" if automatic else "user-rom-bound-definition",
        "definition_file_sha256": definition_file_hash,
        "resolved_layout_sha256": digest(json_bytes(layout)),
        "source_manifest_sha256": source_hash,
        "air_candidates_inventoried": len(records),
        "source_scan_truncated": scan["truncated"] if scan else None,
        "first_id": first_id,
        "last_id": last_id,
        "icon_occurrences": len(rows),
        "unique_images": len(unique_images),
        "visible_images": len({r["png_sha256"] for r in rows if r["visible"]}),
        "transparent_images": len({r["png_sha256"] for r in rows if not r["visible"]}),
        "visible_occurrences": sum(r["visible"] for r in rows),
        "transparent_occurrences": sum(not r["visible"] for r in rows),
        "unique_raw_resources": len({r["source_sha256"] for r in rows}),
        "unique_palettes": 1,
        "duplicate_png_copies_avoided": len(rows) - len(unique_images),
        "icon_bytes_read": len(rows) * ICON_BYTES,
        "palette_bytes_read": 32,
        "rescanned": False,
        "inputs_modified": False,
        "limitations": [
            "El rango exportado no demuestra el total de recursos ni la capacidad reservada de una variante.",
            "Se usa la primera paleta de iconos documentada; no se infiere el contexto de cada icono en el juego.",
            "Un ID de icono no es un ID ni un nombre de objeto; varios objetos pueden compartir icono.",
            "El inventario AIR opcional conserva metadatos; no verifica los archivos .bin externos ni reclasifica candidatos.",
            "La apariencia no se ha contrastado con capturas del juego; review permanece unreviewed.",
        ],
    }
    result = {
        **summary,
        "status": "planned" if dry_run else "completed",
        "dry_run": dry_run,
        "output": str(out),
        "gallery": str(out / "index.html"),
    }
    if dry_run:
        return result
    from arcanacart.icon_gallery import gallery

    payloads.update(
        {
            "definition.json": json_bytes(layout),
            "summary.json": json_bytes(summary),
            "catalog.json": json_bytes({"summary": summary, "icons": rows}),
            "icons.csv": _csv(rows, list(rows[0])),
            "index.html": gallery(summary, rows),
        }
    )
    if source:
        inventory = [
            {
                "offset": r["offset"],
                "compression": r["compression"],
                "stored_bytes": r["compressed_bytes"],
                "decoded_bytes": r["decompressed_bytes"],
                "sha256": r["sha256"],
                "references": len(r["references"]),
                "classification": "unclassified-air-candidate",
            }
            for r in records
        ]
        payloads["air-inventory.csv"] = _csv(
            inventory,
            [
                "offset",
                "compression",
                "stored_bytes",
                "decoded_bytes",
                "sha256",
                "references",
                "classification",
            ],
        )
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    with workspace_lock(out):
        atomic_json(out / "icons-state.json", {"status": "running"})
        try:
            for name, payload in sorted(payloads.items()):
                atomic_write(out / name, payload)
            atomic_json(
                out / "icons-state.json",
                {
                    "status": "completed",
                    "artifacts": {name: digest(raw) for name, raw in sorted(payloads.items())},
                },
                force=True,
            )
        except Exception:
            atomic_json(out / "icons-state.json", {"status": "failed"}, force=True)
            raise
    return result
