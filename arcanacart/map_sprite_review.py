"""Collect bounded standing-map-sprite evidence from the two bases and known variants."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from arcanacart.core.io import check_destination, digest, json_bytes
from arcanacart.icon_variants import (
    DEFAULT_PLAN,
    _destination,
    _input,
    _plan,
    _publish,
    pack_variants,
)
from arcanacart.icons import FE7_SHA256, FE8_SHA256, _csv, _json_file, _safe
from arcanacart.pipeline import load_rom
from arcanacart.resource_compare import _checked
from feunpack.lz10 import LZError, measure

FORMAT = "arcanacart-standing-map-sprite-review-1"
STATE = "map-sprites-review-state.json"
FEBUILDER = (
    "https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/"
)
DECOMP = "https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/"
SOURCES = [FEBUILDER + n for n in ("ROMFE7U.cs", "ROMFE8U.cs", "ImageUnitWaitIconFrom.cs")]
SOURCES += [DECOMP + n for n in ("include/unit_icon_data.h", "src/unit_icon_wait_data.c", "src/bmudisp.c")]

# This is a probe budget, NOT a table capacity or an approved extraction range.
PROBE_SLOTS = 128
MAX_SHEET_BYTES = 16384
PROFILES: dict[str, dict] = {
    "fe7": {"rom_sha256": FE7_SHA256, "pointer_locations": [0x24DA0], "palette_offset": 0x194594},
    "fe8": {
        "rom_sha256": FE8_SHA256,
        "pointer_locations": [0x26730, 0x267B0, 0x26838, 0x26C88, 0x28064, 0x27F74],
        "palette_offset": 0x59EE20,
    },
}
SIZE = {0: (16, 16, 384), 1: (16, 32, 768), 2: (32, 32, 1536)}
PALETTES = ("player", "enemy", "npc", "gray", "fourth", "light-rune", "sepia")


def _rom_offset(value: int, data: bytes, length: int) -> int:
    if not 0x08000000 <= value < 0x0E000000:
        raise ValueError("El puntero no apunta a una ventana ROM GBA.")
    offset = (value - 0x08000000) % 0x02000000
    if offset % 4 or offset + length > len(data):
        raise ValueError("Puntero sin alineación de cuatro bytes o fuera de ROM.")
    return offset


def _entries(
    data: bytes,
    offset: int,
    records: list[dict] | None,
    root: str,
    *,
    first_id: int = 0,
    slot_limit: int = PROBE_SLOTS,
    stop_on_boundary: bool = True,
) -> tuple[list[dict], dict | None, dict[str, bytes]]:
    """Measure only an explicit table interval; support continuing without replaying its prefix."""
    if (
        type(first_id) is not int
        or type(slot_limit) is not int
        or not 0 <= first_id < slot_limit <= 256
        or offset < 0
        or offset > len(data)
        or offset % 4
    ):
        raise ValueError("Intervalo de tabla fuera del presupuesto de revisión.")
    entries: list[dict] = []
    boundary = None
    payloads: dict[str, bytes] = {}
    indexed = {r["offset"]: r for r in records} if records is not None else {}
    for sprite_id in range(first_id, min(slot_limit, (len(data) - offset) // 8)):
        position = offset + sprite_id * 8
        pattern, size_code, pointer = struct.unpack_from("<HHI", data, position)
        entry = {
            "sprite_id": sprite_id,
            "sprite_id_hex": f"0x{sprite_id:02X}",
            "entry_offset": position,
            "pattern": pattern,
            "size_code": size_code,
            "sheet_pointer": pointer,
            "status": "candidate",
            "issues": [],
        }
        if boundary is not None:
            entry["post_boundary_hint"] = True
        if pointer == 0:
            entry["status"] = "reserved"
            entries.append(entry)
            if sprite_id and pattern == size_code == 0:
                if boundary is None:
                    boundary = {"sprite_id": sprite_id, "reason": "zero-record-heuristic"}
                if stop_on_boundary:
                    break
            continue
        try:
            sheet_offset = _rom_offset(pointer, data, 4)
        except ValueError:
            # FEBuilder's list heuristic stops at an invalid non-null pointer.
            # This is not proof of a table end; the full probe window is retained.
            if boundary is None:
                boundary = {"sprite_id": sprite_id, "reason": "invalid-pointer-heuristic"}
            entry["status"] = "boundary-hint"
            entries.append(entry)
            if stop_on_boundary:
                break
            continue
        entry["sheet_offset"] = sheet_offset
        dimensions = SIZE.get(size_code)
        if dimensions:
            entry.update(
                frame_width=dimensions[0],
                frame_height=dimensions[1],
                expected_bytes_for_three_frames=dimensions[2],
            )
        else:
            entry["issues"].append("unknown-size-code")
        try:
            decoded_bytes, stored_bytes = measure(data, sheet_offset, max_size=MAX_SHEET_BYTES)
        except LZError as exc:
            entry["status"] = "unsupported-sheet"
            entry["issues"].append(str(exc))
            raw = data[sheet_offset : sheet_offset + 64]
            name = root + f"cabecera-no-compatible-{sprite_id:02x}.bin"
            payloads[name] = raw
            entry.update(header_file=name, header_sha256=digest(raw))
        else:
            stored = data[sheet_offset : sheet_offset + stored_bytes]
            name = "hojas-comprimidas/" + digest(stored) + ".lz10"
            payloads[name] = stored
            entry.update(
                compressed_bytes=stored_bytes,
                decoded_bytes=decoded_bytes,
                stored_file=name,
                stored_sha256=digest(stored),
                decoded_sha256_recomputed=False,
            )
            if dimensions and decoded_bytes != dimensions[2]:
                entry["issues"].append("nonstandard-three-frame-size")
            record = indexed.get(sheet_offset)
            if record is not None:
                consistent = (
                    record["compression"] == "lz10"
                    and record["compressed_bytes"] == stored_bytes
                    and record["decompressed_bytes"] == decoded_bytes
                )
                entry.update(
                    air_correlation="metadata-consistent" if consistent else "metadata-mismatch",
                    air_decoded_sha256=record["sha256"],
                    air_reference_count=len(record["references"]),
                )
                if not consistent:
                    entry["issues"].append("air-metadata-mismatch")
            else:
                entry["air_correlation"] = (
                    "no-existing-candidate" if records is not None else "not-supplied-for-base"
                )
        entries.append(entry)
    return entries, boundary, payloads


def _inspect(data: bytes, identity: dict, records: list[dict] | None) -> tuple[dict, dict[str, bytes]]:
    """Read known pointers and at most 128 table slots; never scan or decompress."""
    profile = PROFILES[identity["game"]]
    root = "evidencias/" + identity["variant_id"] + "/"
    payloads: dict[str, bytes] = {}
    pointers = []
    for location in profile["pointer_locations"]:
        item = {"location": location, "value": None, "table_offset": None}
        if location >= 64 and location + 4 <= len(data):
            context = data[location - 64 : location + 4]
            name = root + f"contexto-{location:08x}.bin"
            payloads[name] = context
            item.update(
                value=struct.unpack_from("<I", data, location)[0],
                context_file=name,
                context_sha256=digest(context),
            )
            try:
                item["table_offset"] = _rom_offset(item["value"], data, 8)
            except ValueError as exc:
                item["issue"] = str(exc)
        else:
            item["issue"] = "La ubicación de acceso excede la ROM."
        pointers.append(item)
    offset = pointers[0]["table_offset"]
    result = {
        **identity,
        "status": "pending",
        "rom_size_bytes": len(data),
        "access_pointers": pointers,
        "table_offset": offset,
        "probe_slot_limit": PROBE_SLOTS,
        "entry_bytes": 8,
        "entries": [],
        "boundary_hint": None,
        "palette_candidates": [],
        "issues": [],
        "table_capacity_confirmed": False,
        "range_approved": False,
        "extraction_enabled": False,
    }
    valid_offsets = {p["table_offset"] for p in pointers if p["table_offset"] is not None}
    if len(valid_offsets) > 1:
        result["issues"].append("conflicting-access-pointers")
    if any(p["table_offset"] is None for p in pointers):
        result["issues"].append("unusable-access-pointer")

    # Fixed palette addresses are reference candidates. Runtime use or relocation
    # in modified engines is explicitly NOT inferred from these addresses.
    for i, role in enumerate(PALETTES):
        start = profile["palette_offset"] + i * 32
        palette = {"role_hint": role, "offset": start, "runtime_use_verified": False}
        if start + 32 <= len(data):
            raw = data[start : start + 32]
            name = root + "paleta-referencia-" + role + ".bin"
            payloads[name] = raw
            palette.update(file=name, sha256=digest(raw))
        else:
            palette["issue"] = "reference-palette-outside-rom"
        result["palette_candidates"].append(palette)

    if offset is None:
        result["issues"].append("canonical-pointer-unusable-no-fallback")
        return result, payloads
    window = data[offset : min(offset + PROBE_SLOTS * 8, len(data))]
    name = root + "tabla-ventana.bin"
    payloads[name] = window
    result.update(table_window_file=name, table_window_sha256=digest(window), table_window_bytes=len(window))
    entries, boundary, sheets = _entries(data, offset, records, root)
    result.update(entries=entries, boundary_hint=boundary)
    payloads.update(sheets)
    if result["boundary_hint"] is None:
        result["issues"].append("probe-budget-or-rom-bound-reached")
    result["candidate_sheets"] = sum("stored_file" in e for e in result["entries"])
    result["slots_observed"] = len(result["entries"])
    return result, payloads


def _compare(result: dict, base: dict | None, payloads: dict[str, bytes]) -> None:
    if base is None or base["status"] == "error":
        result["base_comparison"] = {"available": False}
        return
    by_id = {e["sprite_id"]: e for e in base["entries"]}
    comparable = [
        e
        for e in result["entries"]
        if "stored_sha256" in e and "stored_sha256" in by_id.get(e["sprite_id"], {})
    ]
    identical = sum(
        e["stored_sha256"] == by_id[e["sprite_id"]]["stored_sha256"]
        and e["size_code"] == by_id[e["sprite_id"]]["size_code"]
        and e["pattern"] == by_id[e["sprite_id"]]["pattern"]
        for e in comparable
    )
    contexts = []
    for current, reference in zip(result["access_pointers"], base["access_pointers"], strict=False):
        if "context_file" in current and "context_file" in reference:
            contexts.append(
                {
                    "location": current["location"],
                    "code_before_literal_identical": payloads[current["context_file"]][:-4]
                    == payloads[reference["context_file"]][:-4],
                }
            )
    result["base_comparison"] = {
        "available": True,
        "comparable_slots": len(comparable),
        "identical_stored_sheets_and_flags": identical,
        "different_stored_sheets_or_flags": len(comparable) - identical,
        "access_contexts": contexts,
        "palette_reference_bytes_identical": [
            r.get("sha256") == b.get("sha256") and "sha256" in r
            for r, b in zip(result["palette_candidates"], base["palette_candidates"], strict=False)
        ],
    }


def review_maps(datos: Path, out: Path, identities: Path = DEFAULT_PLAN, *, scope: str = "all") -> dict:
    if scope not in {"all", "bases"}:
        raise ValueError("El alcance debe ser all o bases.")
    _safe(datos)
    _safe(identities)
    plan = _plan(identities)
    roster: list[dict] = [
        {
            "variant_id": game + "-base",
            "game": game,
            "variant": "usa-base",
            "rom_sha256": spec["rom_sha256"],
            "rom_relative_path": game + "/" + game + "-usa-base.gba",
        }
        for game, spec in PROFILES.items()
    ]
    if scope == "all":
        roster += plan["variants"]
    paths = [identities] + [
        _input(datos, row[k])
        for row in roster
        for k in ("rom_relative_path", "air_relative_path")
        if k in row
    ]
    _destination(out, paths)
    payloads = {"identidades-usadas.json": json_bytes(plan), "fuentes.json": json_bytes(SOURCES)}
    results = []
    bases = {}
    for identity in roster:
        try:
            data, rom = load_rom(_input(datos, identity["rom_relative_path"]))
            if rom["sha256"] != identity["rom_sha256"]:
                raise ValueError("Los bytes exactos de ROM no coinciden con la identidad registrada.")
            records, truncated = None, None
            if "air_relative_path" in identity:
                air, air_hash = _json_file(_input(datos, identity["air_relative_path"]), 64 * 1024 * 1024)
                if air_hash != identity["air_sha256"]:
                    raise ValueError("Los bytes exactos del AIR no coinciden; no se normalizan LF/CRLF.")
                records, scan, _ = _checked(air)
                truncated = scan["truncated"]
                if air["rom"]["sha256"] != rom["sha256"] or air["rom"]["size_bytes"] != len(data):
                    raise ValueError("El AIR no corresponde a la identidad y tamaño de esta ROM.")
            result, evidence = _inspect(data, identity, records)
            payloads.update(evidence)
            result.update(
                rom_bytes_verified=True,
                air_bytes_verified=records is not None,
                air_candidates=len(records) if records is not None else None,
                source_scan_truncated=truncated,
            )
            if identity["variant_id"].endswith("-base"):
                bases[identity["game"]] = result
            else:
                _compare(result, bases.get(identity["game"]), payloads)
            payloads["candidatas/" + identity["variant_id"] + ".json"] = json_bytes(
                {"format": "arcanacart-standing-map-sprite-candidate-1", **result}
            )
        except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
            result = {
                **identity,
                "status": "error",
                "error": str(exc),
                "entries": [],
                "extraction_enabled": False,
            }
            if identity["variant_id"].endswith("-base"):
                bases[identity["game"]] = result
        results.append(result)
    counts = {
        "pending": sum(r["status"] == "pending" for r in results),
        "error": sum(r["status"] == "error" for r in results),
        "approved": 0,
    }
    summary = {
        "format": FORMAT,
        "status": "completed",
        "scope": scope,
        "roms": len(roster),
        "bases": len(PROFILES),
        "variants": len(roster) - len(PROFILES),
        "counts": counts,
        "plan_canonical_sha256": digest(json_bytes(plan)),
        "probe_slot_limit": PROBE_SLOTS,
        "unique_stored_sheets": sum(n.startswith("hojas-comprimidas/") for n in payloads),
        "ready_for_extraction": False,
        "rescanned": False,
        "sheets_decompressed": False,
        "pngs_exported": False,
        "inputs_modified": False,
        "limits": [
            "128 slots is a probe budget, not a proven table capacity or approved ID range.",
            "An early zero/invalid record is only a boundary hint; the raw window remains available.",
            "Default palette bytes do not prove runtime palette use in a modified engine.",
            "LZ10 is measured only at table-referenced offsets; decoded hashes are AIR metadata only.",
            "No class/item naming, movement sprites, game timing or in-game appearance is confirmed.",
        ],
        "results": results,
    }
    flat = [
        {"variant_id": r["variant_id"], "game": r["game"], **entry} for r in results for entry in r["entries"]
    ]
    flat = [
        {k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()}
        for row in flat
    ]
    fields = list(dict.fromkeys(k for row in flat for k in row)) or ["variant_id", "game", "sprite_id"]
    payloads.update({"revision.json": json_bytes(summary), "entradas.csv": _csv(flat, fields)})
    if len(payloads) >= 100000 or sum(map(len, payloads.values())) > 256 * 1024 * 1024:
        raise ValueError("La evidencia excede el presupuesto de publicación.")
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
                    raise ValueError("Guarda el ZIP fuera de la carpeta de revisión.")
            result = review_maps(args.datos, args.out, args.identities, scope=args.scope)
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
