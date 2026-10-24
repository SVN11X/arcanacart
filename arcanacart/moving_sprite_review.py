"""Collect bounded moving-sprite tables, LZ10 sheets and AP evidence without a scan."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from arcanacart import __version__
from arcanacart.core.io import check_destination, digest, json_bytes
from arcanacart.icon_variants import DEFAULT_PLAN, _destination, _input, _plan, _publish, pack_variants
from arcanacart.icons import FE7_SHA256, FE8_SHA256, _csv, _json_file, _safe
from arcanacart.map_sprite_review import DECOMP, FEBUILDER
from arcanacart.pipeline import load_rom
from arcanacart.resource_compare import _checked
from feunpack.lz10 import LZError, measure

FORMAT = "arcanacart-moving-map-sprite-review-1"
STATE = "moving-sprites-review-state.json"
PROBE_SLOTS = 255  # Observation budget for native class IDs 1..255, never a capacity claim.
MAX_SHEET_BYTES = 32768
MAX_AP_BYTES = 131072
AP_FALLBACK_BYTES = 16384
MAX_PACKET_BYTES = 256 * 1024 * 1024
PROFILES: dict[str, dict] = {
    "fe7": {"rom_sha256": FE7_SHA256, "pointer_locations": [0x6D574]},
    "fe8": {"rom_sha256": FE8_SHA256, "pointer_locations": [0x79584, 0x79598, 0xBAC2C, 0xBAC40]},
}
SOURCES = [FEBUILDER + name for name in ("ROMFE7U.cs", "ROMFE8U.cs", "ImageUnitMoveIconFrom.cs", "U.cs")]
SOURCES += [
    DECOMP + name
    for name in ("include/unit_icon_data.h", "include/mu.h", "src/mu.c", "src/ap.c", "scripts/apdump.py")
]


def _offset(pointer: int, length: int, size: int, *, alignment: int = 4) -> int:
    if not 0x08000000 <= pointer < 0x0E000000:
        raise ValueError("El puntero no apunta a ROM GBA.")
    offset = (pointer - 0x08000000) % 0x02000000
    if offset % alignment or offset + length > size:
        raise ValueError("Puntero desalineado o fuera de ROM.")
    return offset


def _motion_layout(raw: bytes) -> dict:
    """Bound AP offsets and linear scripts; never execute animation commands or render OAM.

    The ordered native layout has frame offsets before animation offsets. The
    latter has no count: its end is inferred from the earliest referenced data.
    Unsupported layouts remain windows for independent review, not approvals.
    """
    end = min(len(raw), MAX_AP_BYTES)
    extent = 4

    def bounds(pos: int, count: int) -> None:
        nonlocal extent
        if pos < 0 or pos % 2 or pos + count > end:
            raise ValueError("AP: referencia fuera de la ventana acotada.")
        extent = max(extent, pos + count)

    def word(pos: int) -> int:
        bounds(pos, 2)
        return struct.unpack_from("<H", raw, pos)[0]

    frame_table, anim_table = word(0), word(2)
    if not 4 <= frame_table < anim_table or (anim_table - frame_table) % 2:
        raise ValueError("AP: orden de tablas no compatible con el layout nativo revisado.")
    frame_count = (anim_table - frame_table) // 2
    if not 1 <= frame_count <= 512:
        raise ValueError("AP: presupuesto de 512 fotogramas excedido.")
    bounds(frame_table, frame_count * 2)
    targets = [frame_table + word(frame_table + i * 2) for i in range(frame_count)]
    if any(t < anim_table + 2 or t % 2 for t in targets):
        raise ValueError("AP: fotograma superpuesto a las tablas o desalineado.")
    boundary = min(targets)
    animations: list[int] = []
    while anim_table + len(animations) * 2 < boundary:
        if len(animations) >= 64:
            raise ValueError("AP: presupuesto de 64 animaciones excedido.")
        pos = anim_table + len(animations) * 2
        target = anim_table + word(pos)
        if target < pos + 2 or target % 2:
            raise ValueError("AP: offset de animación inválido.")
        animations.append(target)
        boundary = min(boundary, target)
    if not animations or anim_table + len(animations) * 2 != boundary:
        raise ValueError("AP: no se puede acotar la tabla de animaciones.")
    if any(t < boundary for t in targets + animations):
        raise ValueError("AP: datos superpuestos a la tabla de animaciones.")
    scripts = []
    command_count = 0
    for index, target in enumerate(animations):
        commands = []
        position = target
        while True:
            command_count += 1
            if command_count > 4096:
                raise ValueError("AP: presupuesto total de 4096 comandos excedido.")
            ticks, frame = word(position), word(position + 2)
            commands.append([ticks, frame])
            position += 4
            if ticks == 0:
                if frame not in {0, 1, 65535}:
                    raise ValueError("AP: comando terminal desconocido.")
                break
            if frame >= frame_count:
                raise ValueError("AP: índice de fotograma fuera de su tabla.")
        scripts.append({"animation_index": index, "offset": target, "commands": commands})
    frames = []
    for index, target in enumerate(targets):
        position, count = target + 2, word(target)
        rotations = []
        if count & 0x8000:
            rotation_count = count & 0x7FFF
            if rotation_count > 32:
                raise ValueError("AP: presupuesto de 32 transformaciones excedido.")
            bounds(position, rotation_count * 6)
            rotations = [
                list(struct.unpack_from("<3H", raw, position + i * 6)) for i in range(rotation_count)
            ]
            position += rotation_count * 6
            count, position = word(position), position + 2
        if count > 128:
            raise ValueError("AP: presupuesto de 128 objetos por fotograma excedido.")
        bounds(position, count * 8)  # Three OAM halfwords and one source tile per object.
        objects = [list(struct.unpack_from("<3H", raw, position + i * 6)) for i in range(count)]
        tiles = [word(position + count * 6 + i * 2) for i in range(count)]
        frames.append(
            {"frame_index": index, "offset": target, "rotations": rotations, "oam": objects, "tiles": tiles}
        )
    return {
        "format": "arcanacart-bounded-ap-layout-1",
        "status": "native-layout-candidate",
        "captured_bytes": extent,
        "frame_table_offset": frame_table,
        "animation_table_offset": anim_table,
        "animation_count_inference": "earliest-referenced-data-boundary",
        "frame_count": frame_count,
        "animation_count": len(scripts),
        "frames": frames,
        "animations": scripts,
        "executed": False,
        "runtime_appearance_verified": False,
        "allocation_size_confirmed": False,
    }


def _sheet(
    data: bytes, offset: int, record: dict | None, supplied_air: bool
) -> tuple[dict, dict[str, bytes]]:
    try:
        decoded, stored = measure(data, offset, max_size=MAX_SHEET_BYTES)
    except LZError as exc:
        raw = data[offset : offset + 64]
        name = "cabeceras/" + digest(raw) + ".bin"
        return {
            "sheet_status": "unsupported",
            "sheet_issue": str(exc),
            "header_file": name,
            "header_sha256": digest(raw),
        }, {name: raw}
    raw = data[offset : offset + stored]
    name = "hojas-comprimidas/" + digest(raw) + ".lz10"
    meta = {
        "sheet_status": "lz10-measured",
        "stored_file": name,
        "stored_sha256": digest(raw),
        "compressed_bytes": stored,
        "decoded_bytes": decoded,
        "decoded_sha256_recomputed": False,
        "tile_aligned": decoded % 32 == 0,
        "editor_width_hint": 32,
        "editor_height_hint": decoded // 16 if decoded % 16 == 0 else None,
        "preview_geometry_verified": False,
        "air_correlation": "no-existing-candidate" if supplied_air else "not-supplied-for-base",
    }
    if record is not None:
        consistent = record["compression"] == "lz10" and (
            record["compressed_bytes"],
            record["decompressed_bytes"],
        ) == (stored, decoded)
        meta.update(
            air_correlation="metadata-consistent" if consistent else "metadata-mismatch",
            air_decoded_sha256=record["sha256"],
            air_reference_count=len(record["references"]),
        )
    return meta, {name: raw}


def _motion(data: bytes, offset: int) -> tuple[dict, dict[str, bytes]]:
    window = data[offset : offset + MAX_AP_BYTES]
    try:
        layout = _motion_layout(window)
    except ValueError as exc:
        raw = window[:AP_FALLBACK_BYTES]
        name = "ventanas-ap/" + digest(raw) + ".bin"
        return {
            "motion_status": "unparsed-window",
            "motion_issue": str(exc),
            "motion_file": name,
            "motion_sha256": digest(raw),
            "motion_bytes": len(raw),
            "motion_complete": False,
        }, {name: raw}
    raw = window[: layout["captured_bytes"]]
    key = digest(raw)
    name, description = "movimientos/" + key + ".ap.bin", "movimientos/" + key + ".json"
    return {
        "motion_status": layout["status"],
        "motion_file": name,
        "motion_sha256": key,
        "motion_bytes": len(raw),
        "motion_layout_file": description,
        "motion_frame_count": layout["frame_count"],
        "motion_animation_count": layout["animation_count"],
        "motion_complete": False,  # Referenced native data covered; total allocation is not known.
    }, {name: raw, description: json_bytes(layout)}


def _inspect(
    data: bytes, identity: dict, records: list[dict] | None, slots: int
) -> tuple[dict, dict[str, bytes]]:
    payloads: dict[str, bytes] = {}
    pointers: list[dict] = []
    tables: dict[int, list[int]] = {}
    root = "evidencias/" + identity["variant_id"] + "/"
    for location in PROFILES[identity["game"]]["pointer_locations"]:
        pointer = {"location": location, "value": None, "table_offset": None}
        if location + 4 <= len(data):
            start, end = max(0, location - 64), min(len(data), location + 68)
            raw = data[start:end]
            name = root + f"acceso-{location:08x}.bin"
            payloads[name] = raw
            value = struct.unpack_from("<I", data, location)[0]
            pointer.update(value=value, context_offset=start, context_file=name, context_sha256=digest(raw))
            try:
                offset = _offset(value, 8, len(data))
                pointer["table_offset"] = offset
                tables.setdefault(offset, []).append(location)
            except ValueError as exc:
                pointer["issue"] = str(exc)
        else:
            pointer["issue"] = "La ubicación de acceso excede la ROM."
        pointers.append(pointer)
    result = {
        **identity,
        "status": "pending",
        "rom_size_bytes": len(data),
        "access_pointers": pointers,
        "tables": [],
        "probe_slot_limit": slots,
        "entry_bytes": 8,
        "class_indexing_assumption": "native-class-id-minus-one",
        "class_mapping_verified": False,
        "table_capacity_confirmed": False,
        "range_approved": False,
        "extraction_enabled": False,
        "issues": [],
    }
    if len(tables) > 1:
        result["issues"].append("conflicting-access-pointers-all-table-views-retained")
    if any(p["table_offset"] is None for p in pointers):
        result["issues"].append("unusable-access-pointer")
    if not tables:
        result["issues"].append("no-usable-known-table-reference-no-search")
    indexed = {r["offset"]: r for r in records} if records is not None else {}
    sheets, motions = {}, {}
    for offset, locations in tables.items():
        raw = data[offset : offset + slots * 8]
        name = root + f"tabla-{offset:08x}.bin"
        payloads[name] = raw
        view = {
            "table_offset": offset,
            "access_locations": locations,
            "table_window_file": name,
            "table_window_sha256": digest(raw),
            "table_window_bytes": len(raw),
            "slots_observed": len(raw) // 8,
            "observation_complete": len(raw) == slots * 8,
            "entries": [],
            "boundary_hint": None,
        }
        if not view["observation_complete"]:
            result["issues"].append("table-window-truncated-by-rom-bound")
        for index in range(len(raw) // 8):
            position = offset + index * 8
            sheet_pointer, motion_pointer = struct.unpack_from("<2I", raw, index * 8)
            entry = {
                "table_index": index,
                "class_id": index + 1,
                "class_id_hex": f"0x{index + 1:02X}",
                "entry_offset": position,
                "sheet_pointer": sheet_pointer,
                "motion_pointer": motion_pointer,
                "post_boundary_hint": view["boundary_hint"] is not None,
                "status": "candidate",
                "issues": [],
            }
            if sheet_pointer == motion_pointer == 0:
                entry["status"] = "reserved"
                view["boundary_hint"] = view["boundary_hint"] or {
                    "table_index": index,
                    "reason": "zero-record-hint",
                }
            else:
                for kind, pointer, alignment in (("sheet", sheet_pointer, 4), ("motion", motion_pointer, 2)):
                    try:
                        entry[kind + "_offset"] = _offset(pointer, 4, len(data), alignment=alignment)
                    except ValueError:
                        entry["issues"].append("unusable-" + kind + "-pointer")
                if "sheet_offset" in entry:
                    sheet_offset = entry["sheet_offset"]
                    if sheet_offset not in sheets:
                        sheets[sheet_offset], files = _sheet(
                            data, sheet_offset, indexed.get(sheet_offset), records is not None
                        )
                        payloads.update(files)
                    entry.update(sheets[sheet_offset])
                    if entry["sheet_status"] != "lz10-measured":
                        entry["issues"].append("unsupported-sheet")
                    elif not entry["tile_aligned"]:
                        entry["issues"].append("sheet-is-not-tile-aligned")
                    if entry.get("air_correlation") == "metadata-mismatch":
                        entry["issues"].append("air-metadata-mismatch")
                    if sheet_offset in indexed:
                        entry["air_references_this_entry"] = position in indexed[sheet_offset]["references"]
                if entry.get("sheet_status") == "lz10-measured" and "motion_offset" in entry:
                    motion_offset = entry["motion_offset"]
                    if motion_offset not in motions:
                        motions[motion_offset], files = _motion(data, motion_offset)
                        payloads.update(files)
                    entry.update(motions[motion_offset])
                    if entry["motion_status"] != "native-layout-candidate":
                        entry["issues"].append("motion-requires-independent-layout-review")
                if entry["issues"]:
                    entry["status"] = "needs-review"
                    if any(s.startswith("unusable-") for s in entry["issues"]):
                        view["boundary_hint"] = view["boundary_hint"] or {
                            "table_index": index,
                            "reason": "unusable-pointer-hint",
                        }
            view["entries"].append(entry)
        result["tables"].append(view)
    return result, payloads


def _compare(result: dict, base: dict | None, files: dict[str, bytes]) -> None:
    if base is None or base["status"] == "error":
        result["base_comparison"] = {"available": False}
        return
    before = {p["location"]: p for p in base["access_pointers"]}
    contexts = []
    for pointer in result["access_pointers"]:
        reference = before.get(pointer["location"], {})
        if "context_file" in pointer and "context_file" in reference:
            a, b = bytearray(files[pointer["context_file"]]), bytearray(files[reference["context_file"]])
            pos = pointer["location"] - pointer["context_offset"]
            a[pos : pos + 4] = b[pos : pos + 4] = bytes(4)
            contexts.append({"location": pointer["location"], "context_except_literal_identical": a == b})
    # Only table references at the same code location are comparable, even when relocated.
    tables = {location: t for t in base["tables"] for location in t["access_locations"]}
    comparisons = []
    for table in result["tables"]:
        for location in table["access_locations"]:
            reference = tables.get(location)
            if reference is None:
                continue
            by_index = {e["table_index"]: e for e in reference["entries"]}
            comparable = [
                e
                for e in table["entries"]
                if "stored_sha256" in e and "stored_sha256" in by_index.get(e["table_index"], {})
            ]
            comparisons.append(
                {
                    "access_location": location,
                    "table_offset": table["table_offset"],
                    "base_table_offset": reference["table_offset"],
                    "comparable_sheets": len(comparable),
                    "identical_stored_sheets": sum(
                        e["stored_sha256"] == by_index[e["table_index"]]["stored_sha256"] for e in comparable
                    ),
                    "identical_motion_snapshots": sum(
                        "motion_sha256" in e
                        and e["motion_sha256"] == by_index[e["table_index"]].get("motion_sha256")
                        for e in comparable
                    ),
                }
            )
    result["base_comparison"] = {"available": True, "access_contexts": contexts, "table_views": comparisons}


def review_movement(
    datos: Path, out: Path, identities: Path = DEFAULT_PLAN, *, scope: str = "all", slots: int = PROBE_SLOTS
) -> dict:
    if scope not in {"all", "bases"} or type(slots) is not int or not 1 <= slots <= PROBE_SLOTS:
        raise ValueError("Alcance o presupuesto de observación inválido.")
    _safe(datos)
    _safe(identities)
    plan = _plan(identities)
    roster: list[dict] = [
        {
            "variant_id": game + "-base",
            "variant": "usa-base",
            "game": game,
            "rom_sha256": spec["rom_sha256"],
            "rom_relative_path": game + "/" + game + "-usa-base.gba",
        }
        for game, spec in PROFILES.items()
    ]
    if scope == "all":
        roster += plan["variants"]
    paths = [identities] + [
        _input(datos, r[k]) for r in roster for k in ("rom_relative_path", "air_relative_path") if k in r
    ]
    _destination(out, paths)
    if any(out.resolve().is_relative_to(p.resolve()) for p in paths if p.is_dir()):
        raise ValueError("Guarda la revisión fuera de las entradas.")
    payloads = {"identidades-usadas.json": json_bytes(plan), "fuentes.json": json_bytes(SOURCES)}
    results, bases = [], {}
    for identity in roster:
        try:
            data, rom = load_rom(_input(datos, identity["rom_relative_path"]))
            if rom["sha256"] != identity["rom_sha256"]:
                raise ValueError("Los bytes exactos de ROM no coinciden con el registro.")
            records, scan = None, None
            if "air_relative_path" in identity:
                air, air_hash = _json_file(_input(datos, identity["air_relative_path"]), 64 * 1024 * 1024)
                if air_hash != identity["air_sha256"]:
                    raise ValueError("Los bytes exactos del AIR no coinciden; no se normalizan LF/CRLF.")
                records, scan, _ = _checked(air)
                if air["rom"]["sha256"] != rom["sha256"] or air["rom"]["size_bytes"] != len(data):
                    raise ValueError("La identidad y el tamaño de ROM/AIR no corresponden.")
            result, files = _inspect(data, identity, records, slots)
            payloads.update(files)
            result.update(
                rom_bytes_verified=True,
                air_bytes_verified=records is not None,
                air_candidates=len(records) if records is not None else None,
                source_scan_truncated=scan["truncated"] if scan else None,
            )
            if identity["variant_id"].endswith("-base"):
                bases[identity["game"]] = result
            else:
                _compare(result, bases.get(identity["game"]), payloads)
            payloads["candidatas/" + identity["variant_id"] + ".json"] = json_bytes(
                {"format": FORMAT, **result}
            )
        except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
            result = {
                **identity,
                "status": "error",
                "error": str(exc),
                "tables": [],
                "extraction_enabled": False,
            }
            if identity["variant_id"].endswith("-base"):
                bases[identity["game"]] = result
        results.append(result)
        if len(payloads) >= 100000 or sum(map(len, payloads.values())) > MAX_PACKET_BYTES:
            raise ValueError(
                "La evidencia excede el presupuesto del paquete; no se publica una revisión parcial."
            )
    entries = [
        {"variant_id": r["variant_id"], "game": r["game"], "table_offset": t["table_offset"], **e}
        for r in results
        for t in r["tables"]
        for e in t["entries"]
    ]
    summary = {
        "format": FORMAT,
        "status": "completed",
        "tool_version": __version__,
        "scope": scope,
        "roms": len(roster),
        "bases": len(PROFILES),
        "variants": len(roster) - len(PROFILES),
        "counts": {
            "pending": sum(r["status"] == "pending" for r in results),
            "error": sum(r["status"] == "error" for r in results),
            "approved": 0,
        },
        "plan_canonical_sha256": digest(json_bytes(plan)),
        "probe_slot_limit": slots,
        "table_views": sum(len(r["tables"]) for r in results),
        "observed_entries": len(entries),
        "candidate_entries": sum(e["status"] == "candidate" for e in entries),
        "unique_stored_sheets": sum(n.startswith("hojas-comprimidas/") for n in payloads),
        "unique_native_ap_snapshots": sum(n.endswith(".ap.bin") for n in payloads),
        "unique_unparsed_ap_windows": sum(n.startswith("ventanas-ap/") for n in payloads),
        "ready_for_extraction": False,
        "rescanned": False,
        "sheets_decompressed": False,
        "animations_executed": False,
        "pngs_exported": False,
        "inputs_modified": False,
        "limits": [
            "255 observed slots per referenced table is a budget, not a table capacity or an approved class range.",
            "Native class ID = table index + 1 is an assumption until the captured engine context is reviewed.",
            "All distinct known table references and entries after boundary hints are retained; no whole-ROM pointer search runs.",
            "AP offsets and linear commands are bounded, not executed. Native AP table counts are inferred; allocations are not proven.",
            "Unsupported AP layouts retain only an explicitly incomplete window of up to 16 KiB.",
            "AIR decoded hashes are metadata only; no sheet is decompressed and no palette/runtime rendering is approved.",
        ],
        "results": results,
    }
    flat = [
        {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()}
        for row in entries
    ]
    fields = list(dict.fromkeys(k for row in flat for k in row)) or ["variant_id", "game", "class_id"]
    payloads.update({"revision.json": json_bytes(summary), "entradas.csv": _csv(flat, fields)})
    if (
        len(payloads) >= 100000
        or sum(map(len, payloads.values())) > MAX_PACKET_BYTES
        or any(len(b) > 32 * 1024 * 1024 for b in payloads.values())
    ):
        raise ValueError(
            "La evidencia excede el presupuesto de publicación; no se publica un paquete parcial."
        )
    _publish(out, payloads, state_name=STATE)
    return {k: v for k, v in summary.items() if k != "results"} | {
        "output": str(out),
        "report": str(out / "revision.json"),
        "error_examples": [
            {"variant_id": r["variant_id"], "error": r["error"]} for r in results if r["status"] == "error"
        ][:5],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review")
    review.add_argument("--datos", type=Path, required=True)
    review.add_argument("--out", type=Path, required=True)
    review.add_argument("--identities", type=Path, default=DEFAULT_PLAN)
    review.add_argument("--scope", choices=("all", "bases"), default="all")
    review.add_argument("--slots", type=int, default=PROBE_SLOTS)
    review.add_argument("--zip", type=Path)
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
                if args.zip.resolve().is_relative_to(args.out.resolve()):
                    raise ValueError("Guarda el ZIP fuera de la revisión.")
            result = review_movement(
                args.datos, args.out, args.identities, scope=args.scope, slots=args.slots
            )
            if args.zip:
                result["zip"] = pack_variants(args.out, args.zip, state_name=STATE)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get("counts", {}).get("error") else 0
    except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc), "rescanned": False}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
