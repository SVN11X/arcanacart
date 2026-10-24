"""Consolidate completed variant icon batches; preserve bytes and every origin."""

from __future__ import annotations

import argparse
import csv
import io
import json
import stat
import struct
import sys
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from arcanacart import __version__
from arcanacart.core.io import check_destination, digest, json_bytes, read_bounded
from arcanacart.icon_package import _document, _relative
from arcanacart.icon_variants import (
    _destination, _hash, _publish, _sealed, _verify_snapshot, pack_variants,
)
from arcanacart.icons import FORMAT, ICON_BYTES, _csv, _integer, _safe

CATALOG_FORMAT = "arcanacart-consolidated-item-icon-catalog-1"
CATALOG_STATE = "catalog-state.json"


def _input_bundle(source: Path) -> tuple[dict[str, bytes], dict]:
    _safe(source)
    if source.is_dir():
        for name in ("resumen.json", "variant-icons-state.json"):
            _safe(source / name)
            if not (source / name).is_file():
                raise ValueError("Indica la carpeta de un lote terminado, con resumen y manifiesto.")
        metadata = _document({"resumen.json": read_bounded(source / "resumen.json", 32 * 1024 * 1024)}, "resumen.json")
        if metadata.get("format") != "arcanacart-item-icon-variant-batch-1":
            raise ValueError("La carpeta no corresponde a un lote de iconos de variantes.")
        return _sealed(source), {"kind": "directory", "path": str(source), "zip_sha256": None}
    if source.suffix.lower() != ".zip" or not source.is_file() or source.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("Indica una carpeta de lote o su ZIP portable de hasta 256 MiB.")
    import hashlib
    with source.open("rb") as stream:
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
        stream.seek(0)
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= 100000 or sum(i.file_size for i in entries) > 256 * 1024 * 1024:
                raise ValueError("El ZIP excede el presupuesto de archivos o lectura.")
            names = set()
            for entry in entries:
                name = _relative(entry.filename)
                if (name.casefold() in names or entry.is_dir() or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size > 32 * 1024 * 1024
                    or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}):
                    raise ValueError("ZIP con rutas repetidas, enlaces o entradas no compatibles.")
                names.add(name.casefold())
            payloads = {entry.filename: archive.read(entry) for entry in entries}
    return _verify_snapshot(payloads), {"kind": "zip", "path": str(source), "zip_sha256": hasher.hexdigest()}


def _png_pixels(data: bytes) -> bytes:
    """Bounded RGBA8 16x16 decoder, including PNG row filters 0..4; no reencoding."""
    if len(data) > 65536 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG de icono inválido o demasiado grande.")
    position, header, ended, compressed = 8, False, False, bytearray()
    while position + 12 <= len(data):
        length = struct.unpack_from(">I", data, position)[0]
        end = position + 12 + length
        if end > len(data):
            raise ValueError("Chunk PNG truncado.")
        kind, content = data[position + 4:position + 8], data[position + 8:end - 4]
        if zlib.crc32(kind + content) != struct.unpack_from(">I", data, end - 4)[0]:
            raise ValueError("CRC de PNG incorrecto.")
        if kind == b"IHDR":
            if position != 8 or header or content != struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0):
                raise ValueError("Se requiere PNG RGBA8 no entrelazado de 16x16.")
            header = True
        elif not header:
            raise ValueError("PNG sin cabecera inicial.")
        elif kind == b"IDAT":
            compressed.extend(content)
        elif kind == b"IEND":
            if content:
                raise ValueError("Final PNG inválido.")
            ended = True
            position = end
            break
        elif not kind[0] & 32 and kind != b"PLTE":
            raise ValueError("Chunk crítico PNG no compatible.")
        position = end
    if not ended or position != len(data) or not compressed:
        raise ValueError("PNG incompleto o con bytes posteriores.")
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(bytes(compressed), 1041)
    if len(decoded) != 1040 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("La imagen PNG no tiene el tamaño descomprimido esperado.")
    previous, pixels = bytes(64), bytearray()
    for y in range(16):
        filter_ = decoded[y * 65]
        if filter_ > 4:
            raise ValueError("Filtro PNG desconocido.")
        row = bytearray(decoded[y * 65 + 1:y * 65 + 65])
        for x in range(64):
            left, above, upper_left = row[x - 4] if x >= 4 else 0, previous[x], previous[x - 4] if x >= 4 else 0
            predictor = 0
            if filter_ == 1:
                predictor = left
            elif filter_ == 2:
                predictor = above
            elif filter_ == 3:
                predictor = (left + above) // 2
            elif filter_ == 4:
                estimate = left + above - upper_left
                a, b, c = abs(estimate - left), abs(estimate - above), abs(estimate - upper_left)
                predictor = left if a <= b and a <= c else above if b <= c else upper_left
            row[x] = (row[x] + predictor) & 255
        pixels.extend(row)
        previous = bytes(row)
    return bytes(pixels)


def _raw_pixels(raw: bytes, palette: bytes) -> bytes:
    pixels = bytearray()
    for y in range(16):
        for x in range(16):
            value = raw[((y // 8) * 2 + x // 8) * 32 + (y % 8) * 4 + (x % 8) // 2]
            index = (value >> (4 * (x % 2))) & 15
            color = struct.unpack_from("<H", palette, index * 2)[0]
            pixels.extend(((color & 31) * 255 // 31, ((color >> 5) & 31) * 255 // 31,
                           ((color >> 10) & 31) * 255 // 31, 255 if index else 0))
    return bytes(pixels)


def _rows(raw: bytes) -> list[dict]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("CSV sin cabecera única.")
    rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError("CSV con columnas ausentes o adicionales.")
    return rows


def _csv_row(row: dict) -> dict:
    return {key: "" if value is None else str(value) for key, value in row.items()}


def _checked_batch(files: dict[str, bytes]) -> tuple[dict, list[dict], dict[str, bytes]]:
    summary = _document(files, "resumen.json")
    results = summary.get("results")
    if (summary.get("format") != "arcanacart-item-icon-variant-batch-1" or summary.get("status") != "completed"
        or not isinstance(results, list) or not 1 <= len(results) <= 100
        or type(summary.get("processed_variants")) is not int or summary["processed_variants"] != len(results)
        or not _integer(summary.get("expected_variants"), len(results), 100)
        or type(summary.get("partial_selection")) is not bool or not isinstance(summary.get("skipped_variants"), list)
        or len(summary["skipped_variants"]) != summary["expected_variants"] - len(results)):
        raise ValueError("Se requiere un lote de iconos de variantes terminado y coherente.")
    if any(not _hash(summary.get(key)) for key in ("plan_canonical_sha256", "review_report_sha256")):
        raise ValueError("El lote no conserva los hashes del plan y de su revisión.")
    hashes = {name: digest(raw) for name, raw in files.items()}
    png_pixels, raw_pixels, seen, origins, retained = {}, {}, set(), [], {}
    source_csv_rows = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Resultado de variante inválido.")
        vid = result.get("variant_id")
        if (not isinstance(vid, str) or len(vid) != 7 or vid[:4] not in {"fe7-", "fe8-"}
            or not vid[4:].isascii() or not vid[4:].isdigit() or vid in seen
            or result.get("game") != vid[:3] or not isinstance(result.get("variant"), str)):
            raise ValueError("Identidad de variante inválida o repetida.")
        seen.add(vid)
        root = vid + "/"
        local = _document(files, root + "summary.json")
        catalog = _document(files, root + "catalog.json")
        state = _document(files, root + "icons-state.json")
        layout = _document(files, root + "definition.json")
        rows = catalog.get("icons")
        if (local.get("format") != "arcanacart-item-icon-catalog-1" or local.get("status") != "completed"
            or catalog.get("summary") != local or {k: result.get(k) for k in local} != local
            or local.get("game") != vid[:3] or not _hash(local.get("rom_sha256"))
            or not _hash(local.get("source_manifest_sha256"))
            or not _integer(local.get("rom_size_bytes"), 192, 32 * 1024 * 1024)
            or not isinstance(rows, list) or not 1 <= len(rows) <= 4096):
            raise ValueError("Resumen, catálogo o identidad incoherentes: " + vid)
        expected = {n[len(root):] for n in files if n.startswith(root)} - {"icons-state.json"}
        if (state.get("status") != "completed" or not isinstance(state.get("artifacts"), dict)
            or set(state["artifacts"]) != expected
            or any(hashes[root + name] != hash_ for name, hash_ in state["artifacts"].items())):
            raise ValueError("Manifiesto de variante incoherente: " + vid)
        size = local["rom_size_bytes"]
        if (layout.get("format") != FORMAT or layout.get("game") != vid[:3]
            or layout.get("rom_sha256") != local["rom_sha256"] or layout.get("icon_bytes") != ICON_BYTES
            or not _integer(layout.get("first_id"), 0, 65535) or not _integer(layout.get("icon_count"), 1, 4096)
            or not _integer(layout.get("table_offset"), 0, size - 128)
            or layout["table_offset"] + 128 * layout["icon_count"] > size
            or not _integer(layout.get("palette_offset"), 0, size - 32)
            or not _integer(local.get("first_id"), layout["first_id"], layout["first_id"] + layout["icon_count"] - 1)
            or not _integer(local.get("last_id"), local["first_id"], layout["first_id"] + layout["icon_count"] - 1)
            or local.get("icon_occurrences") != len(rows)
            or [r.get("icon_id") if isinstance(r, dict) else None for r in rows]
               != list(range(local["first_id"], local["last_id"] + 1))):
            raise ValueError("Definición o rango incoherente: " + vid)
        definition = files[root + "definition.json"]
        if layout["table_offset"] < layout["palette_offset"] + 32 and layout["palette_offset"] < (
                layout["table_offset"] + 128 * layout["icon_count"]):
            raise ValueError("La definición solapa el banco con la paleta: " + vid)
        if (files.get("definiciones/" + vid + ".json") != definition
            or digest(definition) != local.get("definition_file_sha256")
            or digest(json_bytes(layout)) != local.get("resolved_layout_sha256")):
            raise ValueError("La definición no coincide con su SHA-256: " + vid)
        for name in ("summary.json", "definition.json", "icons-state.json"):
            retained["fuentes/" + root + name] = files[root + name]
        unique_png, unique_raw, unique_pal, visible_png = set(), set(), set(), set()
        visible_count = 0
        for row in rows:
            reserved = {"variant_id", "variant", "source_png", "source_raw_file", "source_palette_file",
                        "source_catalog", "definition_sha256"}
            if (reserved.intersection(row) or row.get("game") != vid[:3] or row.get("rom_sha256") != local["rom_sha256"]
                or row.get("air_sha256") != local["source_manifest_sha256"]
                or not _integer(row.get("icon_id"), 0, 65535)
                or not _integer(row.get("source_offset"), 0, size - 128)
                or not _integer(row.get("palette_offset"), 0, size - 32)
                or row.get("icon_id_hex") != f"0x{row['icon_id']:02X}"
                or row.get("source_offset") != layout["table_offset"] + 128 * (row["icon_id"] - layout["first_id"])
                or row.get("palette_offset") != layout["palette_offset"]
                or row.get("size_bytes") != 128 or row.get("width") != 16 or row.get("height") != 16
                or row.get("kind") != "item-icon" or row.get("compression") != "none"
                or row.get("data_origin") != "local-rom-raw" or type(row.get("visible")) is not bool):
                raise ValueError("Procedencia o geometría incoherente: " + vid)
            for field, hash_field, prefix, suffix in (
                ("file", "png_sha256", "imagenes/", ".png"),
                ("raw_file", "source_sha256", "raw/", ".bin"),
                ("palette_file", "palette_sha256", "paletas/", ".bin"),
            ):
                hash_ = row.get(hash_field)
                if (not _hash(hash_) or row.get(field) != prefix + hash_ + suffix
                    or hashes.get(root + row[field]) != hash_):
                    raise ValueError("Recurso sin referencia o SHA-256 correcto: " + vid)
                retained[row[field]] = files[root + row[field]]
            raw, pal = files[root + row["raw_file"]], files[root + row["palette_file"]]
            if len(raw) != 128 or len(pal) != 32:
                raise ValueError("Raw o paleta de longitud incorrecta: " + vid)
            if row["png_sha256"] not in png_pixels:
                png_pixels[row["png_sha256"]] = _png_pixels(files[root + row["file"]])
            pair = (row["source_sha256"], row["palette_sha256"])
            if pair not in raw_pixels:
                raw_pixels[pair] = _raw_pixels(raw, pal)
            pixels = png_pixels[row["png_sha256"]]
            if pixels != raw_pixels[pair] or row["visible"] != any(pixels[3::4]):
                raise ValueError("El PNG no coincide con su raw, paleta o transparencia: " + vid)
            visible_count += row["visible"]
            unique_png.add(row["png_sha256"])
            unique_raw.add(row["source_sha256"])
            unique_pal.add(row["palette_sha256"])
            if row["visible"]:
                visible_png.add(row["png_sha256"])
            source_row = {"variant_id": vid, "variant": result["variant"], **row}
            for key in ("file", "raw_file", "palette_file"):
                source_row[key] = root + row[key]
            source_csv_rows.append(_csv_row(source_row))
            origins.append({**row, "variant_id": vid, "variant": result["variant"],
                            "source_png": root + row["file"], "source_raw_file": root + row["raw_file"],
                            "source_palette_file": root + row["palette_file"],
                            "source_catalog": root + "catalog.json",
                            "definition_sha256": local["definition_file_sha256"]})
        counts = {"unique_images": len(unique_png), "unique_raw_resources": len(unique_raw),
                  "unique_palettes": len(unique_pal), "visible_images": len(visible_png),
                  "transparent_images": len(unique_png - visible_png), "visible_occurrences": visible_count,
                  "transparent_occurrences": len(rows) - visible_count,
                  "duplicate_png_copies_avoided": len(rows) - len(unique_png)}
        if any(local.get(k) != v for k, v in counts.items()):
            raise ValueError("Conteos de variante incoherentes: " + vid)
        for sub, field in (("imagenes/", "file"), ("raw/", "raw_file"), ("paletas/", "palette_file")):
            if {root + r[field] for r in rows} != {n for n in files if n.startswith(root + sub)}:
                raise ValueError("Recursos ausentes o sin procedencia: " + vid)
        if _rows(files[root + "icons.csv"]) != [_csv_row(r) for r in rows]:
            raise ValueError("El CSV local no coincide con su catálogo: " + vid)
    if (_rows(files["ocurrencias.csv"]) != source_csv_rows
        or summary.get("icon_occurrences") != len(origins)
        or summary.get("unique_pngs_across_variants") != len(png_pixels)):
        raise ValueError("El CSV o los conteos globales no conservan todas las procedencias.")
    skipped = summary["skipped_variants"]
    if any(not isinstance(v, str) for v in skipped) or len(set(skipped)) != len(skipped) or set(skipped) & seen:
        raise ValueError("Selección parcial de variantes incoherente.")
    roots = seen | {"definiciones", "resumen.json", "ocurrencias.csv", "galerias.csv", "variant-icons-state.json"}
    if "index.html" in files:
        roots.add("index.html")
    if ({n.split("/", 1)[0] for n in files} != roots
        or {n for n in files if n.startswith("definiciones/")} != {"definiciones/" + vid + ".json" for vid in seen}):
        raise ValueError("El lote contiene archivos raíz o definiciones ajenos a sus variantes.")
    retained["fuentes/resumen-original.json"] = files["resumen.json"]
    retained["fuentes/manifesto-original.json"] = files["variant-icons-state.json"]
    return summary, origins, retained


def consolidate(source: Path, out: Path) -> dict:
    _destination(out, [source])
    if source.is_dir() and out.resolve().is_relative_to(source.resolve()):
        raise ValueError("Guarda el catálogo fuera de la carpeta del lote.")
    files, source_info = _input_bundle(source)
    original, origins, payloads = _checked_batch(files)
    origins.sort(key=lambda r: (r["variant_id"], r["icon_id"]))
    grouped: dict[str, dict] = {}
    for origin in origins:
        key = origin["png_sha256"]
        if key not in grouped:
            grouped[key] = {"png_sha256": key, "file": origin["file"], "width": 16, "height": 16,
                            "visible": origin["visible"], "origins": []}
        grouped[key]["origins"].append(origin)
    images = []
    for key in sorted(grouped):
        image = grouped[key]
        image.update(games=sorted({r["game"] for r in image["origins"]}),
                     variant_ids=sorted({r["variant_id"] for r in image["origins"]}),
                     occurrences=len(image["origins"]))
        images.append(image)
    png_count = sum("/imagenes/" in n for n in files)
    summary = {"format": CATALOG_FORMAT, "status": "completed", "tool_version": __version__,
               "source": source_info, "source_summary_sha256": digest(files["resumen.json"]),
               "source_manifest_sha256": digest(files["variant-icons-state.json"]),
               "source_verified_files": len(files), "plan_canonical_sha256": original["plan_canonical_sha256"],
               "review_report_sha256": original["review_report_sha256"],
               "variants": original["processed_variants"], "source_expected_variants": original["expected_variants"],
               "source_skipped_variants": original["skipped_variants"], "icon_occurrences": len(origins),
               "unique_images": len(images), "visible_images": sum(i["visible"] for i in images),
               "transparent_images": sum(not i["visible"] for i in images),
               "transparent_occurrences": sum(not r["visible"] for r in origins),
               "unique_raw_resources": len({r["source_sha256"] for r in origins}),
               "unique_palettes": len({r["palette_sha256"] for r in origins}),
               "source_png_files": png_count, "duplicate_png_copies_avoided": png_count - len(images),
               "deduplication": "Exact file SHA-256; every variant/ID occurrence is retained.",
               "roms_read": False, "rescanned": False, "assets_reencoded": False, "inputs_modified": False,
               "scope": "Solo los rangos y la primera paleta del lote; capacidad total y uso en el juego sin confirmar."}
    catalog = {"summary": summary, "variants": original["results"], "images": images}
    image_rows = [{k: image[k] for k in ("png_sha256", "file", "width", "height", "visible", "occurrences")}
                  | {"games": "|".join(image["games"]), "variant_ids": "|".join(image["variant_ids"])}
                  for image in images]
    from arcanacart.icon_catalog_gallery import gallery
    fields = list(dict.fromkeys(key for r in origins for key in r))
    payloads.update({"resumen.json": json_bytes(summary), "catalogo.json": json_bytes(catalog),
                     "imagenes.csv": _csv(image_rows, list(image_rows[0])),
                     "ocurrencias.csv": _csv(origins, fields), "index.html": gallery(catalog)})
    if len(payloads) >= 100000 or sum(map(len, payloads.values())) > 256 * 1024 * 1024 or any(
            len(raw) > 32 * 1024 * 1024 for raw in payloads.values()):
        raise ValueError("El catálogo excede el presupuesto de archivos o tamaño.")
    _publish(out, payloads, state_name=CATALOG_STATE)
    return summary | {"output": str(out), "gallery": str(out / "index.html")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("consolidate", "pack"):
        command = commands.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        if name == "consolidate":
            command.add_argument("--zip", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            result = pack_variants(args.input, args.out, state_name=CATALOG_STATE)
        else:
            if args.zip:
                check_destination(args.zip)
                if args.zip.resolve().is_relative_to(args.out.resolve()):
                    raise ValueError("Guarda el ZIP fuera del catálogo.")
            result = consolidate(args.input, args.out)
            if args.zip:
                result["zip"] = pack_variants(args.out, args.zip, state_name=CATALOG_STATE)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, struct.error, zlib.error, csv.Error) as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "rescanned": False}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
