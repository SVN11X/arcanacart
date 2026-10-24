"""Documented face-table links, standard portrait assembly and local RGB555 palettes."""

from __future__ import annotations

import csv
import io
import logging
import struct
from collections import Counter
from pathlib import Path

from arcanacart import __version__, graphics
from arcanacart.compression import DECODERS
from arcanacart.core.io import (
    atomic_json,
    atomic_write,
    digest,
    json_bytes,
    read_bounded,
    read_json,
    workspace_lock,
)
from arcanacart.interpret import BlobReader
from arcanacart.resource_compare import _checked
from arcanacart.schemas import validate

FE7_SHA256 = "f1200d19771b366b6ead15dec0eee4a7785b538d894c069c36f7592321ee799b"
FE8_SHA256 = "638cda9d9b72657220fbf7e7a500cd3b64d9686c36e8a56fca69d26d13886f2f"
SOURCES = [
    "https://github.com/StanHash/fe7_us/blob/5c8b3c5e254e00f0f3458b9772c27e1a5a326e3b/asm/code_1.s",
    "https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ImagePortraitForm.cs",
]
DEFAULT_LAYOUT = {
    "format": "arcanacart-face-layout-1",
    "rom_sha256": FE7_SHA256,
    "table_offset": 0xC96584,
    "pointer_location": 0x6B30,
    "entry_size": 28,
    "entry_count": 229,
    "sources": SOURCES,
}
FE8_REFERENCE = (
    "https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2"
)
FE8_LAYOUT = {
    "format": "arcanacart-face-layout-1",
    "rom_sha256": FE8_SHA256,
    # GetPortraitData(fid) uses portrait_data + fid - 1. The first real entry
    # is at 0x8ACBE0; the code's pointer addresses the virtual entry zero.
    "table_offset": 0x8ACBC4,
    "pointer_location": 0x5524,
    "entry_size": 28,
    "entry_count": 173,
    "sources": [
        FE8_REFERENCE + "/src/portrait_data.c",
        FE8_REFERENCE + "/include/types.h",
        FE8_REFERENCE + "/src/face.c",
        FE8_REFERENCE + "/src/bmlib.c",
        FE8_REFERENCE + "/scripts/compressor.py",
        "https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ROMFE8U.cs",
    ],
}
BUILTIN_LAYOUTS = {FE7_SHA256: DEFAULT_LAYOUT, FE8_SHA256: FE8_LAYOUT}
EXPECTED_COUNTS = {FE8_SHA256: {"portrait": 115, "miniature": 111, "classcard": 57}}
FIELDS = {0: "portrait", 4: "miniature", 16: "classcard"}
FOLDERS = {"portrait": "retratos", "miniature": "miniaturas", "classcard": "tarjetas-clase"}


def _safe(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("No se admiten rutas mediante enlaces simbólicos.")


def checked_layout(value: dict, rom: dict) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) != set(DEFAULT_LAYOUT)
        or value.get("format") != "arcanacart-face-layout-1"
        or value.get("rom_sha256") != rom["sha256"]
        or type(value.get("entry_size")) is not int
        or value["entry_size"] != 28
        or type(value.get("entry_count")) is not int
        or not 2 <= value["entry_count"] <= 4096
        or type(value.get("table_offset")) is not int
        or value["table_offset"] < 0
        or value["table_offset"] + value["entry_count"] * 28 > rom["size_bytes"]
        or not isinstance(value.get("sources"), list)
        or not 1 <= len(value["sources"]) <= 16
        or any(not isinstance(s, str) or not s.strip() or len(s) > 2000 for s in value["sources"])
    ):
        raise ValueError("Definición de retratos inválida o ligada a otra ROM.")
    pointer = value["pointer_location"]
    if pointer is not None and (type(pointer) is not int or not 0 <= pointer <= rom["size_bytes"] - 4):
        raise ValueError("Ubicación del puntero a la tabla fuera de la ROM.")
    return value


def _pointer(value: int, size: int, length: int = 1) -> int:
    if not 0x08000000 <= value < 0x0E000000:
        raise ValueError("Puntero de datos fuera de las ventanas ROM de GBA.")
    offset = (value - 0x08000000) % 0x02000000
    if offset + length > size:
        raise ValueError("Puntero o rango de datos fuera de esta ROM.")
    return offset


def _reference_links(records: list[dict], layout: dict) -> dict[int, dict]:
    links: dict[int, dict] = {}
    low, high = layout["table_offset"], layout["table_offset"] + layout["entry_count"] * 28
    for record in records:
        for reference in record["references"]:
            if not isinstance(reference, dict) or type(reference.get("location")) is not int:
                raise ValueError("Referencia sin ubicación válida en el AIR.")
            location = reference["location"]
            if not low <= location < high or (location - low) % 28 not in FIELDS:
                continue
            if reference.get("target_offset") != record["offset"]:
                raise ValueError("La referencia y el offset del bloque no coinciden.")
            if location in links and links[location] != record:
                raise ValueError("Dos bloques reclaman el mismo campo de la tabla.")
            links[location] = record
    return links


def _render(raw: bytes, kind: str, colors: list[tuple[int, int, int]] | None) -> tuple[int, int, bytes]:
    if kind == "portrait":
        return graphics.portrait(raw, colors=colors)
    if kind == "miniature" and len(raw) != 512:
        raise ValueError("La miniatura estándar requiere 512 bytes (32x32, 4 bpp).")
    if not raw or len(raw) % 32 or len(raw) > 8192:
        raise ValueError("Componente gráfico incompatible con el layout estándar.")
    return graphics.tiles(
        raw, width_tiles=4 if kind == "miniature" else 10, colors=colors, transparent_zero=True
    )


def _read_raw_component(rom: bytes, offset: int) -> tuple[bytes, str, int]:
    """FE UnpackRaw: type 00 and a 24-bit stored size INCLUDING its header."""
    if offset % 4 or offset + 4 > len(rom) or rom[offset] != 0:
        raise ValueError(
            "El componente no está en el AIR ni tiene una cabecera raw 00 documentada y alineada."
        )
    stored = int.from_bytes(rom[offset + 1 : offset + 4], "little")
    if not 4 < stored <= 8196 or offset + stored > len(rom):
        raise ValueError("El tamaño raw incluye 4 bytes de cabecera y debe caber en la ROM y en el límite.")
    return rom[offset + 4 : offset + stored], digest(rom[offset : offset + stored]), stored


def _catalog_csv(rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    fields = (
        "face_id",
        "face_id_hex",
        "kind",
        "source_offset",
        "source_sha256",
        "size_bytes",
        "compression",
        "compressed_bytes",
        "data_origin",
        "payload_offset",
        "stored_bytes",
        "encoded_sha256",
        "raw_blob",
        "table_entry_offset",
        "pointer_location",
        "palette_pointer_location",
        "palette_offset",
        "palette_sha256",
        "colors",
        "width",
        "height",
        "png",
        "status",
        "error",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def reconstruct_faces(
    source: Path,
    out: Path,
    *,
    resources: Path | None = None,
    rom_path: Path | None = None,
    definition: Path | None = None,
    dry_run: bool = False,
) -> dict:
    document = read_json(source, 64 * 1024 * 1024)
    records, scan, _ = _checked(document)
    if "schema_version" in document:
        validate(document)
    automatic_layout = BUILTIN_LAYOUTS.get(document["rom"]["sha256"])
    if definition is None and automatic_layout is None:
        raise ValueError(
            "El layout automático requiere una base FE7/FE8 USA exacta; para otra ROM usa --definition validada."
        )
    layout = checked_layout(
        read_json(definition) if definition else dict(automatic_layout or {}), document["rom"]
    )
    expected_counts = EXPECTED_COUNTS.get(document["rom"]["sha256"], {}) if definition is None else {}
    root = resources or source.parent / "resources"
    for path in (source, root, out, *([rom_path] if rom_path else [])):
        _safe(path)
    if not root.is_dir():
        raise ValueError("Falta la carpeta resources del análisis existente.")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("Elige una salida nueva y vacía para conservar las extracciones anteriores.")
    if source.resolve().is_relative_to(out.resolve()) or out.resolve().is_relative_to(root.resolve()):
        raise ValueError("La salida debe estar separada del AIR y de los bloques originales.")
    if rom_path and rom_path.resolve().is_relative_to(out.resolve()):
        raise ValueError("La salida debe estar separada de la ROM.")
    links = _reference_links(records, layout)
    rom = None
    if rom_path:
        rom = read_bounded(rom_path, 64 * 1024 * 1024, 4)
        if len(rom) != document["rom"]["size_bytes"] or digest(rom) != document["rom"]["sha256"]:
            raise ValueError("La ROM local no coincide con el hash y tamaño del AIR.")
        if layout["pointer_location"] is not None:
            offset = _pointer(struct.unpack_from("<I", rom, layout["pointer_location"])[0], len(rom))
            if offset != layout["table_offset"]:
                raise ValueError("El puntero real a la tabla no coincide con la definición.")
    if dry_run:
        return {
            "status": "planned",
            "table_entries": layout["entry_count"],
            "observed_component_links": len(links),
            "rom_bytes_verified": rom is not None,
            "rescanned": False,
            "output": str(out),
        }
    by_offset = {r["offset"]: r for r in records}
    sizes = {r["sha256"]: r["decompressed_bytes"] for r in records}
    reader = BlobReader(root, sizes, 64 * 1024 * 1024)
    cache: dict[str, bytes] = {}
    raw_by_offset: dict[int, tuple[bytes, str, int]] = {}
    raw_data: dict[str, bytes] = {}
    verified_encodings: set[int] = set()
    palette_data: dict[str, bytes] = {}
    rows: list[dict] = []
    entries_without_observed_graphics = []
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    with workspace_lock(out):
        atomic_json(out / "faces-state.json", {"status": "running"})
        try:
            for face_id in range(1, layout["entry_count"]):
                if face_id == 1 or face_id % 32 == 0:
                    logging.info("Reconstruyendo retratos: entrada %d/%d", face_id, layout["entry_count"] - 1)
                entry = layout["table_offset"] + face_id * 28
                entry_rows = []
                for field, kind in FIELDS.items():
                    location = entry + field
                    record = links.get(location)
                    target_offset = record["offset"] if record else None
                    if rom is not None:
                        pointer = struct.unpack_from("<I", rom, location)[0]
                        if pointer == 0:
                            if record:
                                raise ValueError("El AIR declara una referencia en un campo nulo de la ROM.")
                            continue
                        target_offset = _pointer(pointer, len(rom))
                        if record and target_offset != record["offset"]:
                            raise ValueError("La referencia del AIR no coincide con la tabla de la ROM.")
                        record = by_offset.get(target_offset)
                    elif record is None:
                        continue
                    if target_offset is None:
                        raise ValueError("El componente no tiene un offset de origen válido.")
                    row = {
                        "face_id": face_id,
                        "face_id_hex": f"0x{face_id:03X}",
                        "kind": kind,
                        "table_entry_offset": entry,
                        "pointer_location": location,
                        "source_offset": target_offset,
                        "source_sha256": record["sha256"] if record else None,
                        "size_bytes": record["decompressed_bytes"] if record else None,
                        "compression": record["compression"] if record else None,
                        "compressed_bytes": record["compressed_bytes"] if record else None,
                        "data_origin": "air-resource" if record else "local-rom-raw",
                        "encoded_sha256": record.get("encoded_sha256") if record else None,
                        "stored_bytes": record["compressed_bytes"] if record else None,
                        "palette_pointer_location": entry + 8,
                        "palette_offset": None,
                        "palette_sha256": None,
                        "colors": "grayscale-placeholder",
                        "classification": "documented-table-link",
                        "verification": "rom-table-and-blobs"
                        if rom is not None
                        else "air-references-and-blobs",
                        "review": "unreviewed",
                        "status": "pending",
                    }
                    rows.append(row)
                    entry_rows.append(row)
                    try:
                        if record is None and rom is not None:
                            if target_offset not in raw_by_offset:
                                raw_by_offset[target_offset] = _read_raw_component(rom, target_offset)
                            raw, encoded_hash, stored_bytes = raw_by_offset[target_offset]
                            hash_ = digest(raw)
                            row.update(
                                source_sha256=hash_,
                                size_bytes=len(raw),
                                compression="none",
                                compressed_bytes=0,
                                payload_offset=target_offset + 4,
                                stored_bytes=stored_bytes,
                                encoded_sha256=encoded_hash,
                                verification="rom-table-and-raw-data",
                            )
                        elif record is not None:
                            hash_ = record["sha256"]
                            if record["decompressed_bytes"] > 8192 or record["compressed_bytes"] > 32768:
                                raise ValueError(
                                    "El componente supera los límites del layout estándar de retratos."
                                )
                            if hash_ not in cache:
                                cache[hash_] = reader.read(hash_)
                            raw = cache[hash_]
                        else:
                            raise ValueError("El componente requiere la ROM local o un bloque del AIR.")
                        colors = None
                        if rom is not None:
                            offset = target_offset
                            if record is not None and offset not in verified_encodings:
                                end = offset + record["compressed_bytes"]
                                if end > len(rom) or digest(rom[offset:end]) != record.get("encoded_sha256"):
                                    raise ValueError(
                                        "El bloque comprimido no coincide con el encoded_sha256 del AIR."
                                    )
                                decoder = DECODERS.get(rom[offset])
                                if decoder is None or decoder[0] != record["compression"]:
                                    raise ValueError("La compresión del bloque no coincide con el AIR.")
                                decoded, consumed = decoder[1](rom, offset, 8192, None)
                                if consumed != record["compressed_bytes"] or decoded != raw:
                                    raise ValueError(
                                        "La descompresión puntual no coincide con el bloque extraído."
                                    )
                                verified_encodings.add(offset)
                            palette_offset = _pointer(
                                struct.unpack_from("<I", rom, entry + 8)[0], len(rom), 32
                            )
                            raw_palette = rom[palette_offset : palette_offset + 32]
                            palette_hash = digest(raw_palette)
                            palette_data[palette_hash] = raw_palette
                            colors = graphics.palette(raw_palette)
                            row.update(
                                palette_offset=palette_offset,
                                palette_sha256=palette_hash,
                                colors="rgb555-rom",
                            )
                        width, height, pixels = _render(raw, kind, colors)
                        name = f"{FOLDERS[kind]}/face-{face_id:03X}.png"
                        atomic_write(out / name, graphics.png(width, height, pixels))
                        row.update(width=width, height=height, png=name, status="generated")
                        if record is None:
                            raw_data[hash_] = raw
                            row["raw_blob"] = f"raw-resources/{hash_}.bin"
                    except (OSError, ValueError) as exc:
                        row.update(status="error", error=str(exc))
                if not entry_rows:
                    entries_without_observed_graphics.append(face_id)
            for hash_, raw_palette in palette_data.items():
                atomic_write(out / "paletas" / (hash_ + ".bin"), raw_palette)
                w, h, rgba = graphics.swatches(raw_palette)
                atomic_write(out / "paletas" / (hash_ + ".png"), graphics.png(w, h, rgba))
            for hash_, raw in raw_data.items():
                atomic_write(out / "raw-resources" / (hash_ + ".bin"), raw)
            generated = [r for r in rows if r["status"] == "generated"]
            counts = Counter(r["kind"] for r in generated)
            errors = sum(r["status"] == "error" for r in rows)
            classified_hashes = {r["source_sha256"] for r in generated if r["data_origin"] == "air-resource"}
            pending_counts = {kind: max(0, count - counts[kind]) for kind, count in expected_counts.items()}
            summary = {
                "format": "arcanacart-face-extraction-1",
                "tool_version": __version__,
                "rom_sha256": document["rom"]["sha256"],
                "source_manifest_sha256": digest(read_bounded(source, 64 * 1024 * 1024)),
                "candidate_inventory_sha256": digest(json_bytes(records)),
                "source_scan": scan,
                "rom_bytes_verified": rom is not None,
                "layout": layout,
                "candidates": len(records),
                "unique_input_blobs": len(sizes),
                "portraits": counts["portrait"],
                "miniatures": counts["miniature"],
                "classcards": counts["classcard"],
                "generated_component_pngs": len(generated),
                "unique_classified_blobs": len(classified_hashes),
                "unclassified_input_blobs": len(sizes) - len(classified_hashes),
                "resolved_palettes": len(palette_data),
                "raw_rom_components": sum(r["data_origin"] == "local-rom-raw" for r in generated),
                "unique_raw_rom_blobs": len(raw_data),
                "raw_rom_bytes_read": sum(item[2] for item in raw_by_offset.values()),
                "unique_component_blobs": len({r["source_sha256"] for r in generated}),
                "expected_component_counts": expected_counts,
                "pending_component_counts": pending_counts,
                "pending_component_total": sum(pending_counts.values()),
                "components_without_real_palette": sum(
                    r["colors"] == "grayscale-placeholder" for r in generated
                ),
                "entries_without_observed_graphics": entries_without_observed_graphics,
                "errors": errors,
                "rescanned": False,
                "decoded_known_offsets": len(verified_encodings),
                "resource_bytes_read": reader.used,
                "manual_reviews_modified": False,
                "rendering": {
                    "bpp": 4,
                    "transparent_zero": True,
                    "portrait_rectangles_in_tiles": graphics.PORTRAIT_RECTS,
                    "miniature_width_tiles": 4,
                    "classcard_width_tiles": 10,
                    "palette_bytes": 32,
                },
                "status": "partial"
                if errors or entries_without_observed_graphics or rom is None or any(pending_counts.values())
                else "completed",
                "limitations": [
                    "La clasificación usa campos de una tabla documentada; no asigna nombres de personaje.",
                    "Los PNG en gris usan índices de diagnóstico y no representan los colores originales.",
                    "La lectura opcional de ROM verifica tabla, paletas y descompresiones puntuales; no ejecuta el escáner.",
                    "Los componentes raw 00 incluyen la cabecera en su tamaño y se exportan aparte del inventario LZ10.",
                    "Esta etapa no reconstruye animaciones de ojos/boca ni identifica todos los recursos del juego.",
                    "Se conservan el AIR, los bloques y las decisiones manuales de la interpretación anterior.",
                ],
            }
            atomic_json(out / "summary.json", summary)
            atomic_json(out / "catalog.json", {"summary": summary, "resources": rows})
            atomic_write(out / "catalog.csv", _catalog_csv(rows))
            from arcanacart.face_gallery import render_face_gallery

            atomic_write(out / "index.html", render_face_gallery(summary, rows).encode("utf-8"))
            atomic_write(
                out / "report.md",
                (
                    "# Recursos de la tabla de retratos\n\n```json\n" + json_bytes(summary).decode() + "```\n"
                ).encode(),
            )
            artifacts = {
                path.relative_to(out).as_posix(): digest(read_bounded(path, 64 * 1024 * 1024))
                for path in out.rglob("*")
                if path.is_file() and path.name not in {".arcanacart.lock", "faces-state.json"}
            }
            atomic_json(
                out / "faces-state.json", {"status": summary["status"], "artifacts": artifacts}, force=True
            )
            return {**summary, "output": str(out), "gallery": str(out / "index.html")}
        except BaseException:
            atomic_json(out / "faces-state.json", {"status": "failed"}, force=True)
            raise
