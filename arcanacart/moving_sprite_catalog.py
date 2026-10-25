"""Export reviewed movement sheets and AP data using existing palette references."""

from __future__ import annotations

import argparse
import io
import json
import re
import stat
import struct
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from arcanacart import __version__, graphics
from arcanacart import moving_sprite_review as review
from arcanacart.core.io import check_destination, digest, json_bytes, read_bounded
from arcanacart.icon_package import _relative
from arcanacart.icon_variants import _destination, _hash, _publish, _sealed, _verify_snapshot, pack_variants
from arcanacart.icons import _csv, _json_file, _safe
from arcanacart.map_sprite_catalog import FORMAT as STANDING_FORMAT
from arcanacart.map_sprite_catalog import ROLE_LABELS
from arcanacart.map_sprite_catalog import STATE as STANDING_STATE
from feunpack.lz10 import decompress

FORMAT = "arcanacart-moving-resource-catalog-1"
STATE = "moving-resource-catalog-state.json"
DEFINITIONS = Path(__file__).with_name("moving_sprite_definitions.json")


def _bundle(source: Path, state: str) -> tuple[dict[str, bytes], dict]:
    """Read a sealed directory, flat ZIP or recompressed single-folder ZIP."""
    _safe(source)
    if source.is_dir():
        return _sealed(source, state_name=state), {"kind": "directory"}
    if source.suffix.lower() != ".zip":
        raise ValueError("Indica la carpeta del resultado o su ZIP.")
    raw = read_bounded(source, review.MAX_PACKET_BYTES, 4)
    with ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 100000 or sum(e.file_size for e in entries) > review.MAX_PACKET_BYTES:
            raise ValueError("ZIP fuera del presupuesto de archivos o bytes.")
        names, files = set(), {}
        for entry in entries:
            name = _relative(entry.filename[:-1] if entry.is_dir() else entry.filename)
            key = name.casefold() + ("/" if entry.is_dir() else "")
            if key in names or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("ZIP con entradas repetidas, cifradas o enlaces.")
            if entry.file_size > 32 * 1024 * 1024 or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                raise ValueError("Entrada ZIP fuera del presupuesto o formato admitido.")
            names.add(key)
            data = archive.read(entry)  # Includes the CRC check, also for directory entries.
            if not entry.is_dir():
                files[name] = data
    if state not in files:
        folders = {name.split("/", 1)[0] for name in files}
        if len(folders) != 1 or any("/" not in name for name in files):
            raise ValueError("El ZIP no contiene un único resultado con su manifiesto.")
        prefix = next(iter(folders)) + "/"
        files = {name[len(prefix) :]: data for name, data in files.items()}
    return _verify_snapshot(files, state_name=state), {"kind": "zip", "zip_sha256": digest(raw)}


def _definitions(path: Path) -> dict:
    _safe(path)
    doc, _ = _json_file(path, 1024 * 1024)
    rows = doc.get("definitions")
    if (
        doc.get("format") != "arcanacart-moving-resource-definitions-1"
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= 100
        or doc.get("capacity_confirmed") is not False
        or doc.get("runtime_appearance_verified") is not False
        or any(
            not _hash(doc.get(k))
            for k in ("source_report_sha256", "source_state_sha256", "plan_canonical_sha256")
        )
        or not isinstance(doc.get("palette_source"), dict)
        or any(not _hash(doc["palette_source"].get(k)) for k in ("summary_sha256", "state_sha256"))
    ):
        raise ValueError("Registro de rangos o fuentes de paleta inválido.")
    seen = set()
    for spec in rows:
        vid = spec.get("variant_id")
        if (
            not isinstance(vid, str)
            or re.fullmatch(r"fe[78]-(?:base|[0-9]{3})", vid) is None
            or vid in seen
            or spec.get("game") not in {"fe7", "fe8"}
            or not vid.startswith(spec["game"] + "-")
            or not isinstance(spec.get("variant"), str)
            or type(spec.get("first_id")) is not int
            or spec["first_id"] != 1
            or type(spec.get("last_id")) is not int
            or not 1 <= spec["last_id"] <= 255
            or type(spec.get("table_offset")) is not int
            or spec["table_offset"] < 0
            or spec["table_offset"] % 4
            or any(
                not _hash(spec.get(k)) for k in ("rom_sha256", "table_prefix_sha256", "table_window_sha256")
            )
            or (spec.get("air_sha256") is not None and not _hash(spec["air_sha256"]))
            or not isinstance(spec.get("accesses"), list)
            or not 1 <= len(spec["accesses"]) <= 8
        ):
            raise ValueError("Identidad o rango acotado inválido.")
        _relative("definiciones/" + vid + ".json")
        for access in spec["accesses"]:
            if any(
                type(access.get(k)) is not int or access[k] < 0 for k in ("location", "context_offset")
            ) or any(
                not _hash(access.get(k)) for k in ("context_sha256", "context_except_table_literals_sha256")
            ):
                raise ValueError("Acceso sin contexto revisado.")
        seen.add(vid)
    return doc


def _profile(spec: dict, row: dict, files: dict[str, bytes]) -> tuple[list[dict], dict[str, bytes]]:
    vid = spec["variant_id"]
    if (
        row.get("status") != "pending"
        or row.get("rom_bytes_verified") is not True
        or (not vid.endswith("-base") and row.get("air_bytes_verified") is not True)
        or any(
            row.get(k) != spec.get(k) for k in ("variant_id", "variant", "game", "rom_sha256", "air_sha256")
        )
        or len(row.get("tables", [])) != 1
        or row.get("issues")
    ):
        raise ValueError("La identidad o tabla no coincide con la revisión: " + vid)
    table = row["tables"][0]
    window = files[table["table_window_file"]]
    count = spec["last_id"]
    if (
        table["table_offset"] != spec["table_offset"]
        or digest(window) != spec["table_window_sha256"]
        or digest(window[: count * 8]) != spec["table_prefix_sha256"]
        or len(table["entries"]) < count
        or len(row["access_pointers"]) != len(spec["accesses"])
    ):
        raise ValueError("La ventana de tabla o su rango no coincide con los hashes revisados.")
    extras = {"evidencias/" + vid + "/tabla.bin": window}
    for access, observed in zip(spec["accesses"], row["access_pointers"], strict=True):
        raw = files[observed["context_file"]]
        canonical = bytearray(raw)
        if (
            observed["location"] != access["location"]
            or observed["context_offset"] != access["context_offset"]
            or digest(raw) != access["context_sha256"]
            or observed["table_offset"] != spec["table_offset"]
            or review._offset(observed["value"], 8, row["rom_size_bytes"]) != spec["table_offset"]
        ):
            raise ValueError("Un acceso no coincide con el contexto revisado.")
        pos = observed["location"] - observed["context_offset"]
        if struct.unpack_from("<I", raw, pos)[0] != observed["value"]:
            raise ValueError("Literal de acceso contradictorio.")
        for other in row["access_pointers"]:
            pos = other["location"] - observed["context_offset"]
            if 0 <= pos <= len(canonical) - 4:
                canonical[pos : pos + 4] = bytes(4)
        if digest(canonical) != access["context_except_table_literals_sha256"]:
            raise ValueError("Cambió el código fuera de los literales de tabla revisados.")
        extras["evidencias/" + vid + f"/acceso-{observed['location']:08x}.bin"] = raw
    entries = table["entries"][:count]
    for index, entry in enumerate(entries):
        if (
            entry["class_id"] != index + 1
            or entry["table_index"] != index
            or entry["entry_offset"] != spec["table_offset"] + index * 8
            or entry["status"] != "candidate"
            or entry["issues"]
            or entry["post_boundary_hint"]
            or entry["sheet_status"] != "lz10-measured"
            or entry["motion_status"] != "native-layout-candidate"
            or struct.unpack_from("<2I", window, index * 8)
            != (entry["sheet_pointer"], entry["motion_pointer"])
            or review._offset(entry["sheet_pointer"], entry["compressed_bytes"], row["rom_size_bytes"])
            != entry["sheet_offset"]
            or review._offset(
                entry["motion_pointer"], entry["motion_bytes"], row["rom_size_bytes"], alignment=2
            )
            != entry["motion_offset"]
        ):
            raise ValueError("Entrada fuera del prefijo explícitamente revisado.")
    extras["definiciones/" + vid + ".json"] = json_bytes(
        {
            "format": "arcanacart-moving-resource-layout-1",
            **spec,
            "capacity_confirmed": False,
            "runtime_appearance_verified": False,
        }
    )
    return entries, extras


def extract_movement(source: Path, palette_source: Path, out: Path, definitions: Path = DEFINITIONS) -> dict:
    _destination(out, [source, palette_source, definitions])
    if any(p.is_dir() and out.resolve().is_relative_to(p.resolve()) for p in (source, palette_source)):
        raise ValueError("Guarda el catálogo fuera de las carpetas de entrada.")
    registry = _definitions(definitions)
    files, source_info = _bundle(source, review.STATE)
    palette_files, palette_info = _bundle(palette_source, STANDING_STATE)
    if (
        digest(files.get("revision.json", b"")) != registry["source_report_sha256"]
        or digest(files[review.STATE]) != registry["source_state_sha256"]
    ):
        raise ValueError("La revisión de movimiento no es la auditada para estas definiciones.")
    if (
        digest(palette_files.get("resumen.json", b"")) != registry["palette_source"]["summary_sha256"]
        or digest(palette_files[STANDING_STATE]) != registry["palette_source"]["state_sha256"]
    ):
        raise ValueError("El catálogo de paletas no coincide con el catálogo de reposo revisado.")
    report = json.loads(files["revision.json"])
    palette_catalog = json.loads(palette_files["catalogo.json"])
    if (
        report.get("format") != review.FORMAT
        or report.get("status") != "completed"
        or report.get("counts", {}).get("error") != 0
        or report.get("plan_canonical_sha256") != registry["plan_canonical_sha256"]
        or palette_catalog.get("summary", {}).get("format") != STANDING_FORMAT
        or palette_catalog["summary"] != json.loads(palette_files["resumen.json"])
    ):
        raise ValueError("Metadatos de origen incompatibles.")
    rows = {r["variant_id"]: r for r in report["results"]}
    references = {r["variant_id"]: r for r in palette_catalog["profiles"]}
    expected = {d["variant_id"] for d in registry["definitions"]}
    if (
        len(rows) != len(report["results"])
        or set(rows) != expected
        or len(references) != len(palette_catalog["profiles"])
        or set(references) != expected
    ):
        raise ValueError("Las fuentes no contienen exactamente las identidades de las definiciones.")
    payloads = {
        "fuentes/revision-movimiento.json": files["revision.json"],
        "fuentes/estado-revision-movimiento.json": files[review.STATE],
        "fuentes/resumen-reposo.json": palette_files["resumen.json"],
        "fuentes/estado-reposo.json": palette_files[STANDING_STATE],
        "fuentes/definiciones-usadas.json": json_bytes(registry),
    }
    occurrences, profiles = [], []
    decoded: dict[str, bytes] = {}
    aps: dict[str, dict] = {}
    previews, resources, images = {}, {}, {}
    common_palettes = None
    for spec in registry["definitions"]:
        vid = spec["variant_id"]
        entries, evidence = _profile(spec, rows[vid], files)
        reference = references[vid]
        if any(
            reference.get(k) != spec.get(k) for k in ("game", "variant", "rom_sha256", "air_sha256")
        ) or set(reference["palettes"]) != set(ROLE_LABELS):
            raise ValueError("La procedencia de las paletas no corresponde a esta ROM.")
        if common_palettes is None:
            common_palettes = reference["palettes"]
        if reference["palettes"] != common_palettes:
            raise ValueError("Esta revisión utiliza las siete paletas comunes verificadas.")
        for key in common_palettes.values():
            name = "paletas/" + key + ".bin"
            raw = palette_files[name]
            if len(raw) != 32 or digest(raw) != key:
                raise ValueError("Paleta RGB555 de referencia alterada.")
            payloads[name] = raw
        payloads.update(evidence)
        profile = {
            k: spec.get(k)
            for k in (
                "variant_id",
                "variant",
                "game",
                "rom_sha256",
                "air_sha256",
                "first_id",
                "last_id",
                "table_offset",
            )
        }
        profile.update(
            definition="definiciones/" + vid + ".json",
            palette_offsets=reference["palette_offsets"],
            palettes=common_palettes,
            palette_binding_for_movement_verified=False,
        )
        profiles.append(profile)
        for entry in entries:
            stored_key, ap_key = entry["stored_sha256"], entry["motion_sha256"]
            stored, motion = files[entry["stored_file"]], files[entry["motion_file"]]
            if (
                digest(stored) != stored_key
                or len(stored) != entry["compressed_bytes"]
                or digest(motion) != ap_key
                or len(motion) != entry["motion_bytes"]
            ):
                raise ValueError("Un recurso no coincide con sus bytes originales revisados.")
            if stored_key not in decoded:
                raw, consumed = decompress(stored, max_size=review.MAX_SHEET_BYTES)
                if consumed != len(stored):
                    raise ValueError("La hoja contiene bytes ajenos al flujo LZ10.")
                decoded[stored_key] = raw
            raw = decoded[stored_key]
            raw_key = digest(raw)
            if (
                len(raw) != entry["decoded_bytes"]
                or len(raw) % 32
                or entry.get("air_decoded_sha256", raw_key) != raw_key
            ):
                raise ValueError("El raw descomprimido contradice el tamaño o hash del AIR.")
            if ap_key not in aps:
                layout = review._motion_layout(motion)
                if layout != json.loads(files[entry["motion_layout_file"]]) or layout[
                    "captured_bytes"
                ] != len(motion):
                    raise ValueError("Los datos AP contradicen su descripción estructural.")
                aps[ap_key] = layout
                payloads["ap/" + ap_key + ".bin"] = motion
                payloads["ap/" + ap_key + ".json"] = json_bytes(layout)
            raw_file, compressed_file = "raw/" + raw_key + ".4bpp", "comprimidos/" + stored_key + ".lz10"
            payloads[raw_file], payloads[compressed_file] = raw, stored
            if raw_key not in previews:
                renderings = {}
                for role, palette_key in common_palettes.items():
                    width, height, pixels = graphics.tiles(
                        raw,
                        width_tiles=4,
                        colors=graphics.palette(payloads["paletas/" + palette_key + ".bin"]),
                        transparent_zero=True,
                    )
                    png = graphics.png(width, height, pixels)
                    key = digest(png)
                    name = "imagenes/" + key + ".png"
                    payloads[name] = png
                    images[key] = {
                        "sha256": key,
                        "file": name,
                        "width": width,
                        "height": height,
                        "visible": any(pixels[3::4]),
                    }
                    renderings[role] = {
                        "png_sha256": key,
                        "palette_sha256": palette_key,
                        "palette_file": "paletas/" + palette_key + ".bin",
                    }
                previews[raw_key] = {
                    "raw_sha256": raw_key,
                    "raw_file": raw_file,
                    "width": width,
                    "height": height,
                    "tile_count": len(raw) // 32,
                    "padding_tiles": width // 8 * (height // 8) - len(raw) // 32,
                    "visible": images[renderings["player"]["png_sha256"]]["visible"],
                    "renderings": renderings,
                }
            resource_id = digest(json_bytes({"raw_sha256": raw_key, "ap_sha256": ap_key}))
            resources[resource_id] = {
                "resource_id": resource_id,
                "raw_sha256": raw_key,
                "ap_sha256": ap_key,
                "ap_file": "ap/" + ap_key + ".bin",
                "ap_layout_file": "ap/" + ap_key + ".json",
                "ap_frames": aps[ap_key]["frame_count"],
                "ap_animations": aps[ap_key]["animation_count"],
                "preview_kind": "4bpp-tile-sheet",
                "runtime_appearance_verified": False,
            }
            occurrences.append(
                {
                    "variant_id": vid,
                    "variant": spec["variant"],
                    "game": spec["game"],
                    "class_id": entry["class_id"],
                    "class_id_hex": entry["class_id_hex"],
                    "table_index": entry["table_index"],
                    "entry_offset": entry["entry_offset"],
                    "rom_sha256": spec["rom_sha256"],
                    "air_sha256": spec.get("air_sha256"),
                    "resource_id": resource_id,
                    "raw_sha256": raw_key,
                    "raw_file": raw_file,
                    "decoded_bytes": len(raw),
                    "stored_sha256": stored_key,
                    "compressed_file": compressed_file,
                    "compressed_bytes": len(stored),
                    "sheet_offset": entry["sheet_offset"],
                    "ap_sha256": ap_key,
                    "ap_offset": entry["motion_offset"],
                    "ap_bytes": len(motion),
                    "definition": profile["definition"],
                    "definition_sha256": digest(evidence[profile["definition"]]),
                    "data_origin": "audited-movement-review",
                    "runtime_appearance_verified": False,
                }
            )
    summary = {
        "format": FORMAT,
        "status": "completed",
        "tool_version": __version__,
        "source": source_info,
        "palette_source": palette_info,
        "source_report_sha256": registry["source_report_sha256"],
        "source_state_sha256": registry["source_state_sha256"],
        "definitions_canonical_sha256": digest(json_bytes(registry)),
        "palette_summary_sha256": registry["palette_source"]["summary_sha256"],
        "palette_state_sha256": registry["palette_source"]["state_sha256"],
        "roms": len(profiles),
        "bases": sum(p["variant_id"].endswith("-base") for p in profiles),
        "variants": sum(not p["variant_id"].endswith("-base") for p in profiles),
        "occurrences": len(occurrences),
        "variant_occurrences": sum(not o["variant_id"].endswith("-base") for o in occurrences),
        "unique_resources": len(resources),
        "unique_stored_sheets": len(decoded),
        "unique_raw_sheets": len(previews),
        "unique_ap_snapshots": len(aps),
        "unique_reference_palettes": len(set(common_palettes.values())) if common_palettes else 0,
        "unique_preview_pngs": len(images),
        "visible_raw_sheets": sum(bool(p["visible"]) for p in previews.values()),
        "transparent_raw_sheets": sum(not p["visible"] for p in previews.values()),
        "png_references": len(occurrences) * len(ROLE_LABELS),
        "duplicate_png_copies_avoided": len(occurrences) * len(ROLE_LABELS) - len(images),
        "roms_read": False,
        "air_files_read": False,
        "rescanned": False,
        "inputs_modified": False,
        "runtime_frames_composed": False,
        "animations_executed": False,
        "limits": [
            "Only explicit reviewed table prefixes; total capacities and in-game class usage are not established.",
            "PNG files are complete 4bpp tile-sheet previews using seven existing reference palettes, not reconstructed AP frames.",
            "Preview padding is transparent and recorded; raw bytes, extra source tiles and AP object data remain intact.",
            "Runtime palette selection, OAM composition and animation timing remain unverified.",
        ],
    }
    catalog = {
        "summary": summary,
        "profiles": profiles,
        "resources": list(resources.values()),
        "previews": previews,
        "images": images,
        "occurrences": occurrences,
        "palette_roles": ROLE_LABELS,
    }
    from arcanacart.moving_sprite_gallery import gallery

    payloads.update(
        {
            "resumen.json": json_bytes(summary),
            "catalogo.json": json_bytes(catalog),
            "ocurrencias.csv": _csv(occurrences, list(occurrences[0])),
            "recursos.csv": _csv(list(resources.values()), list(next(iter(resources.values())))),
            "imagenes.csv": _csv(list(images.values()), ["sha256", "file", "width", "height", "visible"]),
            "index.html": gallery(catalog),
        }
    )
    if (
        len(payloads) >= 100000
        or sum(map(len, payloads.values())) > review.MAX_PACKET_BYTES
        or any(len(b) > 32 * 1024 * 1024 for b in payloads.values())
    ):
        raise ValueError("El catálogo excede el presupuesto de publicación.")
    _publish(out, payloads, state_name=STATE)
    return summary | {"output": str(out), "gallery": str(out / "index.html")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract")
    extract.add_argument("--review", type=Path, required=True)
    extract.add_argument("--palettes", type=Path, required=True)
    extract.add_argument("--out", type=Path, required=True)
    extract.add_argument("--definitions", type=Path, default=DEFINITIONS)
    extract.add_argument("--zip", type=Path)
    pack = commands.add_parser("pack")
    pack.add_argument("--input", type=Path, required=True)
    pack.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            result = pack_variants(args.input, args.out, state_name=STATE)
        else:
            if args.zip:
                check_destination(args.zip)
                if args.zip.resolve().is_relative_to(args.out.resolve()) or any(
                    p.is_dir() and args.zip.resolve().is_relative_to(p.resolve())
                    for p in (args.review, args.palettes)
                ):
                    raise ValueError("Guarda el ZIP fuera de las carpetas de entrada y salida.")
            result = extract_movement(args.review, args.palettes, args.out, args.definitions)
            if args.zip:
                result["zip"] = pack_variants(args.out, args.zip, state_name=STATE)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, struct.error, BadZipFile) as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc), "rescanned": False}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
