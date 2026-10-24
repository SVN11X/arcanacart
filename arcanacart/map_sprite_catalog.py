"""Extract reviewed standing sprites from the evidence packet, without reading ROMs."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path
from zipfile import BadZipFile

from arcanacart import __version__, graphics
from arcanacart import map_sprite_followup as follow
from arcanacart import map_sprite_review as review
from arcanacart.core.io import check_destination, digest, json_bytes
from arcanacart.icon_variants import _destination, _hash, _publish
from arcanacart.icons import _csv, _json_file, _safe
from feunpack.lz10 import decompress

FORMAT = "arcanacart-standing-map-sprite-catalog-1"
STATE = "map-sprite-catalog-state.json"
DEFINITIONS = Path(__file__).with_name("map_sprite_definitions.json")
DEFINITION_FORMAT = "arcanacart-standing-map-sprite-definitions-1"
ROLE_LABELS = {
    "player": "Jugador",
    "enemy": "Enemigo",
    "npc": "Aliado",
    "gray": "Gris",
    "fourth": "Cuarto grupo",
    "light-rune": "Runa de luz",
    "sepia": "Sepia",
}


def _definitions(path: Path) -> dict:
    _safe(path)
    document, _ = _json_file(path, 1024 * 1024)
    rows = document.get("definitions")
    if (
        document.get("format") != DEFINITION_FORMAT
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= 100
        or document.get("capacity_confirmed") is not False
        or document.get("in_game_verified") is not False
        or any(
            not _hash(document.get(k))
            for k in ("source_report_sha256", "source_state_sha256", "plan_canonical_sha256")
        )
    ):
        raise ValueError("Definiciones de sprites sin revisión acotada válida.")
    seen = set()
    for row in rows:
        vid, game = row.get("variant_id"), row.get("game")
        if (
            game not in {"fe7", "fe8"}
            or not isinstance(vid, str)
            or not re.fullmatch(game + r"-(?:base|[0-9]{3})", vid)
            or vid in seen
            or not isinstance(row.get("variant"), str)
            or not row["variant"]
            or not _hash(row.get("rom_sha256"))
            or (row.get("air_sha256") is not None and not _hash(row["air_sha256"]))
            or type(row.get("first_id")) is not int
            or row["first_id"] != 0
            or type(row.get("last_id")) is not int
            or not 0 <= row["last_id"] <= 255
            or any(
                type(row.get(k)) is not int or row[k] < 0 or row[k] % 4
                for k in ("table_offset", "palette_loader_offset")
            )
            or any(
                not _hash(row.get(k))
                for k in ("table_sha256", "table_window_sha256", "palette_loader_sha256")
            )
            or not isinstance(row.get("palettes"), dict)
            or set(row["palettes"]) != set(review.PALETTES)
        ):
            raise ValueError("Identidad, rango o evidencia inválida en las definiciones.")
        for pal in row["palettes"].values():
            if (
                not isinstance(pal, dict)
                or type(pal.get("offset")) is not int
                or pal["offset"] < 0
                or pal["offset"] % 2
                or not _hash(pal.get("sha256"))
            ):
                raise ValueError("Paleta sin offset y hash verificados.")
        seen.add(vid)
    return document


def _profile(spec: dict, row: dict, files: dict[str, bytes]) -> tuple[dict, list[dict], dict[str, bytes]]:
    for key in ("variant_id", "game", "variant", "rom_sha256", "air_sha256"):
        if row.get(key) != spec.get(key):
            raise ValueError("La identidad no corresponde a la definición: " + spec["variant_id"])
    if row.get("status") != "pending" or row.get("followup_rom_bytes_verified") is not True:
        raise ValueError("La ampliación no confirmó la identidad actual de esta ROM.")
    table = files[row["table_window_file"]]
    count = spec["last_id"] + 1
    if (
        row["table_offset"] != spec["table_offset"]
        or digest(table) != spec["table_window_sha256"]
        or row["table_window_sha256"] != spec["table_window_sha256"]
        or digest(table[: count * 8]) != spec["table_sha256"]
    ):
        raise ValueError("La tabla no coincide con el rango revisado.")
    entries = row["entries"][:count]
    if len(entries) != count or [e["sprite_id"] for e in entries] != list(range(count)):
        raise ValueError("El prefijo aprobado tiene IDs ausentes o repetidos.")
    for entry in entries:
        geometry = review.SIZE.get(entry["size_code"])
        if (
            entry["status"] != "candidate"
            or entry.get("post_boundary_hint")
            or entry["issues"]
            or geometry is None
            or entry.get("frame_width") != geometry[0]
            or entry.get("frame_height") != geometry[1]
            or entry["decoded_bytes"] != geometry[2]
            or entry["expected_bytes_for_three_frames"] != geometry[2]
            or entry["entry_offset"] != spec["table_offset"] + entry["sprite_id"] * 8
            or struct.unpack_from("<HHI", table, entry["sprite_id"] * 8)
            != (entry["pattern"], entry["size_code"], entry["sheet_pointer"])
            or not 0x08000000 <= entry["sheet_pointer"] < 0x0E000000
            or (entry["sheet_pointer"] - 0x08000000) % 0x02000000 != entry["sheet_offset"]
            or entry["sheet_offset"] % 4
            or entry["sheet_offset"] + entry["compressed_bytes"] > row["rom_size_bytes"]
        ):
            raise ValueError("Entrada fuera del formato o rango aprobado.")
    context = row["palette_load_context"]
    raw_context = files[context["file"]]
    start = spec["palette_loader_offset"] - context["offset"]
    loader = raw_context[start : start + 96] if start >= 0 else b""
    if (
        digest(raw_context) != context["sha256"]
        or len(loader) != 96
        or digest(loader) != spec["palette_loader_sha256"]
        or loader[:10] != bytes.fromhex("00b50948e02189008022")
    ):
        raise ValueError("El cargador de paletas no coincide con el código revisado.")
    palettes, extras = {}, {}
    for index, role in enumerate(review.PALETTES):
        candidates = [p for p in row["palette_candidates"] if p["role_hint"] == role]
        if len(candidates) != 1:
            raise ValueError("Falta una paleta de la definición.")
        candidate = candidates[0]
        raw = files[candidate["file"]]
        pal = spec["palettes"][role]
        if (
            len(raw) != 32
            or digest(raw) != pal["sha256"]
            or candidate["sha256"] != pal["sha256"]
            or candidate["offset"] != pal["offset"]
            or pal["offset"] != spec["palettes"]["player"]["offset"] + index * 32
        ):
            raise ValueError("Los bytes u offsets de paleta no coinciden con la definición.")
        palettes[role] = pal["sha256"]
        extras["paletas/" + pal["sha256"] + ".bin"] = raw
    for role, position in {"player": 0x28, "fourth": 0x30, "light-rune": 0x44, "sepia": 0x5C}.items():
        if struct.unpack_from("<I", loader, position)[0] != 0x08000000 + spec["palettes"][role]["offset"]:
            raise ValueError("Los literales del cargador no apuntan a las paletas revisadas.")
    vid = spec["variant_id"]
    definition = {
        "format": "arcanacart-standing-map-sprite-layout-1",
        **spec,
        "capacity_confirmed": False,
        "in_game_verified": False,
        "palette_binding": "native-loader-byte-identical-to-reviewed-base",
    }
    name = "definiciones/" + vid + ".json"
    extras[name] = json_bytes(definition)
    extras["evidencias/" + vid + "/tabla.bin"] = table
    extras["evidencias/" + vid + "/cargador-paletas.bin"] = loader
    profile = {
        "variant_id": vid,
        "game": spec["game"],
        "variant": spec["variant"],
        "rom_sha256": spec["rom_sha256"],
        "air_sha256": spec["air_sha256"],
        "rom_size_bytes": row["rom_size_bytes"],
        "first_id": 0,
        "last_id": spec["last_id"],
        "definition": name,
        "definition_sha256": digest(extras[name]),
        "palettes": palettes,
        "palette_offsets": {k: v["offset"] for k, v in spec["palettes"].items()},
        "palette_binding": definition["palette_binding"],
        "in_game_verified": False,
    }
    return profile, entries, extras


def extract_sprites(source: Path, out: Path, definitions: Path = DEFINITIONS) -> dict:
    _destination(out, [source, definitions])
    if source.is_dir() and out.resolve().is_relative_to(source.resolve()):
        raise ValueError("Guarda la extracción fuera de la revisión.")
    registry = _definitions(definitions)
    files, source_info = follow._bundle(source)
    if (
        digest(files.get("revision.json", b"")) != registry["source_report_sha256"]
        or digest(files.get(review.STATE, b"")) != registry["source_state_sha256"]
    ):
        raise ValueError("El paquete no coincide con la ampliación auditada para estas definiciones.")
    report = json.loads(files["revision.json"])
    if (
        report.get("format") != follow.FORMAT
        or report.get("status") != "completed"
        or report.get("counts", {}).get("error") != 0
        or report.get("plan_canonical_sha256") != registry["plan_canonical_sha256"]
    ):
        raise ValueError("La revisión ampliada no corresponde al registro aprobado.")
    rows = {r["variant_id"]: r for r in report["results"]}
    if len(rows) != len(report["results"]) or set(rows) != {d["variant_id"] for d in registry["definitions"]}:
        raise ValueError("Las definiciones no cubren las mismas identidades que el paquete.")
    payloads = {
        "fuentes/revision.json": files["revision.json"],
        "fuentes/estado-revision.json": files[review.STATE],
        "fuentes/definiciones-usadas.json": json_bytes(registry),
    }
    profiles, occurrences, assets, render_sets = [], [], {}, {}
    decoded_cache: dict[str, bytes] = {}
    sheet_pngs, frame_pngs, raw_hashes = set(), set(), set()
    common_palettes = None

    def image(width: int, height: int, rgba: bytes) -> str:
        data = graphics.png(width, height, rgba)
        key = digest(data)
        name = "imagenes/" + key + ".png"
        payloads[name] = data
        assets[key] = {
            "sha256": key,
            "file": name,
            "width": width,
            "height": height,
            "visible": any(rgba[3::4]),
        }
        return key

    for spec in registry["definitions"]:
        profile, entries, extras = _profile(spec, rows[spec["variant_id"]], files)
        payloads.update(extras)
        profiles.append(profile)
        if common_palettes is None:
            common_palettes = profile["palettes"]
        if profile["palettes"] != common_palettes:
            raise ValueError("Estas definiciones requieren las siete paletas comunes revisadas.")
        for entry in entries:
            stored = files[entry["stored_file"]]
            stored_hash = entry["stored_sha256"]
            if digest(stored) != stored_hash or len(stored) != entry["compressed_bytes"]:
                raise ValueError("Una hoja comprimida no coincide con su SHA-256 y tamaño.")
            if stored_hash not in decoded_cache:
                raw, consumed = decompress(stored, max_size=review.MAX_SHEET_BYTES)
                if consumed != len(stored):
                    raise ValueError("La hoja contiene bytes ajenos al flujo LZ10 revisado.")
                decoded_cache[stored_hash] = raw
            raw = decoded_cache[stored_hash]
            raw_hash = digest(raw)
            if len(raw) != entry["decoded_bytes"] or entry.get("air_decoded_sha256", raw_hash) != raw_hash:
                raise ValueError("Los bytes descomprimidos contradicen el tamaño o hash del AIR.")
            width, height, _ = review.SIZE[entry["size_code"]]
            render_id = digest(json_bytes({"raw_sha256": raw_hash, "width": width, "height": height}))
            raw_file = "raw/" + raw_hash + ".4bpp"
            compressed_file = "comprimidos/" + stored_hash + ".lz10"
            payloads[raw_file], payloads[compressed_file] = raw, stored
            raw_hashes.add(raw_hash)
            if render_id not in render_sets:
                renderings = {}
                for role in review.PALETTES:
                    pal_hash = profile["palettes"][role]
                    pal_file = "paletas/" + pal_hash + ".bin"
                    actual_width, actual_height, pixels = graphics.tiles(
                        raw,
                        width_tiles=width // 8,
                        colors=graphics.palette(payloads[pal_file]),
                        transparent_zero=True,
                    )
                    if (actual_width, actual_height) != (width, height * 3):
                        raise ValueError("La geometría no contiene los tres fotogramas revisados.")
                    sheet = image(width, height * 3, pixels)
                    frames = [
                        image(width, height, pixels[i * width * height * 4 : (i + 1) * width * height * 4])
                        for i in range(3)
                    ]
                    sheet_pngs.add(sheet)
                    frame_pngs.update(frames)
                    renderings[role] = {
                        "palette_sha256": pal_hash,
                        "palette_file": pal_file,
                        "sheet": sheet,
                        "frames": frames,
                    }
                render_sets[render_id] = {
                    "render_id": render_id,
                    "raw_sha256": raw_hash,
                    "raw_file": raw_file,
                    "width": width,
                    "height": height,
                    "visible": assets[renderings["player"]["sheet"]]["visible"],
                    "renderings": renderings,
                }
            occurrences.append(
                {
                    "variant_id": spec["variant_id"],
                    "game": spec["game"],
                    "variant": spec["variant"],
                    "sprite_id": entry["sprite_id"],
                    "sprite_id_hex": entry["sprite_id_hex"],
                    "pattern": entry["pattern"],
                    "size_code": entry["size_code"],
                    "width": width,
                    "height": height,
                    "render_id": render_id,
                    "rom_sha256": spec["rom_sha256"],
                    "air_sha256": spec["air_sha256"],
                    "entry_offset": entry["entry_offset"],
                    "source_offset": entry["sheet_offset"],
                    "compressed_bytes": len(stored),
                    "stored_sha256": stored_hash,
                    "compressed_file": compressed_file,
                    "decoded_bytes": len(raw),
                    "raw_sha256": raw_hash,
                    "raw_file": raw_file,
                    "source_sheet_file": entry["stored_file"],
                    "definition": profile["definition"],
                    "definition_sha256": profile["definition_sha256"],
                    "data_origin": "review-packet-lz10",
                    "in_game_verified": False,
                }
            )
    assert common_palettes is not None  # Definitions require at least one validated profile.
    summary = {
        "format": FORMAT,
        "status": "completed",
        "tool_version": __version__,
        "source": source_info,
        "source_report_sha256": registry["source_report_sha256"],
        "source_state_sha256": registry["source_state_sha256"],
        "definitions_canonical_sha256": digest(json_bytes(registry)),
        "roms": len(profiles),
        "bases": sum(p["variant_id"].endswith("-base") for p in profiles),
        "variants": sum(not p["variant_id"].endswith("-base") for p in profiles),
        "sheet_occurrences": len(occurrences),
        "variant_sheet_occurrences": sum(not o["variant_id"].endswith("-base") for o in occurrences),
        "unique_stored_sheets": len(decoded_cache),
        "unique_raw_sheets": len(raw_hashes),
        "render_sets": len(render_sets),
        "visible_render_sets": sum(bool(s["visible"]) for s in render_sets.values()),
        "transparent_render_sets": sum(not s["visible"] for s in render_sets.values()),
        "unique_palettes": len(set(common_palettes.values())),
        "unique_pngs": len(assets),
        "unique_sheet_pngs": len(sheet_pngs),
        "unique_frame_pngs": len(frame_pngs),
        "frames_per_sheet": 3,
        "palette_roles_per_sheet": len(review.PALETTES),
        "png_references": len(occurrences) * len(review.PALETTES) * 4,
        "duplicate_png_copies_avoided": len(occurrences) * len(review.PALETTES) * 4 - len(assets),
        "roms_read": False,
        "rescanned": False,
        "inputs_modified": False,
        "in_game_verified": False,
        "limits": [
            "Only the explicit reviewed ranges; full capacities, game usage and other banks remain unknown.",
            "Seven palettes match the statically reviewed native loader, including conditional palette paths.",
            "Full 16x16, 16x32 or 32x32 frames are preserved; no editor cropping or animation timing is inferred.",
        ],
    }
    catalog = {
        "summary": summary,
        "profiles": profiles,
        "occurrences": occurrences,
        "render_sets": list(render_sets.values()),
        "assets": assets,
        "palette_roles": ROLE_LABELS,
    }
    from arcanacart.map_sprite_gallery import gallery

    payloads.update(
        {
            "resumen.json": json_bytes(summary),
            "catalogo.json": json_bytes(catalog),
            "ocurrencias.csv": _csv(occurrences, list(occurrences[0])),
            "imagenes.csv": _csv(list(assets.values()), ["sha256", "file", "width", "height", "visible"]),
            "index.html": gallery(catalog),
        }
    )
    if (
        len(payloads) >= 100000
        or sum(map(len, payloads.values())) > follow.MAX_PACKET_BYTES
        or any(len(raw) > 32 * 1024 * 1024 for raw in payloads.values())
    ):
        raise ValueError("El catálogo excede el presupuesto de archivos o publicación.")
    _publish(out, payloads, state_name=STATE)
    return summary | {"output": str(out), "gallery": str(out / "index.html")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract")
    extract.add_argument("--review", type=Path, required=True)
    extract.add_argument("--out", type=Path, required=True)
    extract.add_argument("--definitions", type=Path, default=DEFINITIONS)
    extract.add_argument("--zip", type=Path)
    pack = commands.add_parser("pack")
    pack.add_argument("--input", type=Path, required=True)
    pack.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            result = review.pack_variants(args.input, args.out, state_name=STATE)
        else:
            if args.zip:
                check_destination(args.zip)
                if args.zip.resolve().is_relative_to(args.out.resolve()) or (
                    args.review.is_dir() and args.zip.resolve().is_relative_to(args.review.resolve())
                ):
                    raise ValueError("Guarda el ZIP fuera de las carpetas de entrada y salida.")
            result = extract_sprites(args.review, args.out, args.definitions)
            if args.zip:
                result["zip"] = review.pack_variants(args.out, args.zip, state_name=STATE)
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
