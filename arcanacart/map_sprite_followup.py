"""Extend the audited FE8 prefixes and collect bounded palette-loading context."""

from __future__ import annotations

import argparse
import io
import json
import stat
import sys
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from arcanacart import map_sprite_review as mr
from arcanacart.core.io import check_destination, digest, json_bytes, read_bounded
from arcanacart.icon_package import _relative
from arcanacart.icon_variants import _destination, _input, _plan, _publish, _sealed, _verify_snapshot
from arcanacart.icons import _csv, _json_file, _safe
from arcanacart.pipeline import load_rom
from arcanacart.resource_compare import _checked

FORMAT = "arcanacart-standing-map-sprite-review-2"
AUDITED_REPORT_SHA256 = "fd75e5af3e8eca514e048ef397ff3d11cea85f667ac0da324a1900c805fcae2d"
AUDITED_STATE_SHA256 = "8b9292d3bcb28310c0eb7dccbec9fea38686221349e480fe1de756baec3fac13"
PREVIOUS = "revision-anterior/"
MAX_PACKET_BYTES = 256 * 1024 * 1024
EXTENDED_SLOTS = 256
CONTEXT_BEFORE = 512
CONTEXT_AFTER = 512


def _bundle(source: Path) -> tuple[dict[str, bytes], dict]:
    _safe(source)
    if source.is_dir():
        return _sealed(source, state_name=mr.STATE), {"kind": "directory", "zip_sha256": None}
    if source.suffix.lower() != ".zip":
        raise ValueError("Indica el ZIP o la carpeta de la revisión inicial auditada.")
    raw = read_bounded(source, MAX_PACKET_BYTES, 4)
    with ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 100000 or sum(i.file_size for i in entries) > MAX_PACKET_BYTES:
            raise ValueError("El ZIP excede el presupuesto de revisión.")
        names = set()
        for entry in entries:
            name = _relative(entry.filename)
            if (
                entry.is_dir()
                or name.casefold() in names
                or entry.flag_bits & 1
                or stat.S_ISLNK(entry.external_attr >> 16)
                or entry.file_size > 32 * 1024 * 1024
                or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            ):
                raise ValueError("ZIP con rutas repetidas, enlaces o entradas no compatibles.")
            names.add(name.casefold())
        files = {entry.filename: archive.read(entry) for entry in entries}
    return _verify_snapshot(files, state_name=mr.STATE), {"kind": "zip", "zip_sha256": digest(raw)}


def _audited(files: dict[str, bytes], plan: dict) -> dict:
    if (
        digest(files.get("revision.json", b"")) != AUDITED_REPORT_SHA256
        or digest(files.get(mr.STATE, b"")) != AUDITED_STATE_SHA256
    ):
        raise ValueError(
            "La entrada no coincide con la revisión inicial auditada; conserva ese paquete exacto."
        )
    report = json.loads(files["revision.json"])
    if (
        report.get("format") != mr.FORMAT
        or report.get("scope") != "all"
        or report.get("status") != "completed"
        or report.get("counts", {}).get("error") != 0
        or report.get("plan_canonical_sha256") != digest(json_bytes(plan))
        or json.loads(files["identidades-usadas.json"]) != plan
    ):
        raise ValueError("La revisión y el registro actual no corresponden a las mismas identidades.")
    expected = {r["variant_id"]: r for r in plan["variants"]}
    expected.update(
        {
            game + "-base": {
                "variant_id": game + "-base",
                "game": game,
                "variant": "usa-base",
                "rom_sha256": spec["rom_sha256"],
                "rom_relative_path": game + "/" + game + "-usa-base.gba",
            }
            for game, spec in mr.PROFILES.items()
        }
    )
    results = report.get("results", [])
    if len(results) != len(expected) or {r["variant_id"] for r in results} != set(expected):
        raise ValueError("El paquete no conserva todas las identidades del registro y sus bases.")
    for row in results:
        if row.get("status") != "pending" or any(
            row.get(k) != v for k, v in expected[row["variant_id"]].items()
        ):
            raise ValueError("Identidad incoherente dentro del informe auditado.")
    return report


def _rebase(value: Any, paths: set[str]) -> Any:
    if isinstance(value, str):
        return PREVIOUS + value if value in paths else value
    if isinstance(value, list):
        return [_rebase(item, paths) for item in value]
    if isinstance(value, dict):
        return {key: _rebase(item, paths) for key, item in value.items()}
    return value


def _eligible(row: dict, files: dict[str, bytes]) -> bool:
    selected = row["game"] == "fe8" and not row["variant_id"].endswith("-base")
    if not selected:
        return False
    context = files[row["access_pointers"][0]["context_file"]]
    # Observed Thumb: MOVS r4,#255; ANDS r4,r7; LSLS r4,r4,#3; ADDS r0,r5,#4.
    if (
        context[22:30] != bytes.fromhex("ff243c40e400281d")
        or row["boundary_hint"] is not None
        or row.get("probe_slot_limit") != mr.PROBE_SLOTS
        or [e["sprite_id"] for e in row["entries"]] != list(range(mr.PROBE_SLOTS))
        or any(e.get("status") != "candidate" or "stored_file" not in e for e in row["entries"])
    ):
        raise ValueError(
            "La variante no respalda continuar el prefijo de 128 entradas con índice de ocho bits."
        )
    return True


def extend_review(source: Path, datos: Path, out: Path, identities: Path = mr.DEFAULT_PLAN) -> dict:
    _safe(datos)
    _safe(identities)
    plan = _plan(identities)
    files, source_info = _bundle(source)
    report = _audited(files, plan)
    results = report["results"]
    selected = {r["variant_id"] for r in results if _eligible(r, files)}
    inputs = [source, identities] + [
        _input(datos, row[k])
        for row in results
        for k in ("rom_relative_path", "air_relative_path")
        if k in row and (k != "air_relative_path" or row["variant_id"] in selected)
    ]
    _destination(out, inputs)
    if source.is_dir() and out.resolve().is_relative_to(source.resolve()):
        raise ValueError("Guarda la ampliación fuera de la revisión anterior.")
    # Every byte of the earlier packet remains available in its own namespace.
    payloads = {PREVIOUS + name: raw for name, raw in files.items()}
    known_paths = set(files)
    updated = []
    for original in results:
        row = _rebase(original, known_paths)
        evidence: dict[str, bytes] = {}
        try:
            data, rom = load_rom(_input(datos, original["rom_relative_path"]))
            if rom["sha256"] != original["rom_sha256"] or len(data) != original["rom_size_bytes"]:
                raise ValueError("Los bytes exactos de ROM no coinciden con la revisión auditada.")
            for pointer in original["access_pointers"]:
                location = pointer["location"]
                if data[location - 64 : location + 4] != files[pointer["context_file"]]:
                    raise ValueError("El contexto de acceso difiere de la evidencia anterior.")
            offset = original["table_offset"]
            window = files[original["table_window_file"]]
            if data[offset : offset + len(window)] != window:
                raise ValueError("La ventana de tabla anterior ha cambiado.")
            for palette in original["palette_candidates"]:
                if data[palette["offset"] : palette["offset"] + 32] != files[palette["file"]]:
                    raise ValueError("La paleta de referencia difiere de la revisión anterior.")
            location = original["access_pointers"][0]["location"]
            start, end = location - CONTEXT_BEFORE, location + CONTEXT_AFTER
            if start < 0 or end > len(data):
                raise ValueError("No se puede recoger el contexto acotado de carga de paletas.")
            name = "evidencias-ampliadas/" + row["variant_id"] + "/contexto-carga-paletas.bin"
            evidence[name] = data[start:end]
            row["palette_load_context"] = {
                "file": name,
                "offset": start,
                "size_bytes": end - start,
                "sha256": digest(evidence[name]),
                "runtime_use_verified": False,
            }
            row["tail_extension"] = {"required": row["variant_id"] in selected, "performed": False}
            if row["variant_id"] in selected:
                air, air_hash = _json_file(_input(datos, original["air_relative_path"]), 64 * 1024 * 1024)
                if air_hash != original["air_sha256"]:
                    raise ValueError("Los bytes exactos del AIR han cambiado; no se normalizan LF/CRLF.")
                records, scan, _ = _checked(air)
                if air["rom"]["sha256"] != rom["sha256"] or air["rom"]["size_bytes"] != len(data):
                    raise ValueError("El AIR no corresponde a la ROM actual.")
                root = "evidencias-ampliadas/" + row["variant_id"] + "/"
                tail, boundary, sheets = mr._entries(
                    data,
                    offset,
                    records,
                    root,
                    first_id=mr.PROBE_SLOTS,
                    slot_limit=EXTENDED_SLOTS,
                    stop_on_boundary=False,
                )
                for entry in tail:
                    name = entry.get("stored_file")
                    if name in files:
                        if sheets[name] != files[name]:
                            raise ValueError("Una hoja comprimida contradice su hash anterior.")
                        entry["stored_file"] = PREVIOUS + name
                evidence.update({n: raw for n, raw in sheets.items() if n not in files})
                name = root + "tabla-ventana.bin"
                evidence[name] = data[offset : min(offset + EXTENDED_SLOTS * 8, len(data))]
                row.update(
                    table_window_file=name,
                    table_window_sha256=digest(evidence[name]),
                    table_window_bytes=len(evidence[name]),
                    probe_slot_limit=EXTENDED_SLOTS,
                    entries=row["entries"] + tail,
                    boundary_hint=boundary,
                    source_scan_truncated=scan["truncated"],
                )
                row["issues"] = [
                    issue for issue in row["issues"] if issue != "probe-budget-or-rom-bound-reached"
                ]
                if boundary is None:
                    row["issues"].append("probe-budget-or-rom-bound-reached")
                row.update(
                    slots_observed=len(row["entries"]),
                    candidate_sheets=sum("stored_file" in e for e in row["entries"]),
                )
                row["tail_extension"].update(
                    performed=True,
                    first_id=mr.PROBE_SLOTS,
                    last_probe_id=EXTENDED_SLOTS - 1,
                    additional_entries=len(tail),
                    air_bytes_verified=True,
                    continued_after_boundary_hint=boundary is not None,
                )
            row["rom_bytes_verified"] = True
            row["followup_rom_bytes_verified"] = True
            payloads.update(evidence)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row = _rebase(original, known_paths)
            row.update(
                status="error", error=str(exc), extraction_enabled=False, followup_rom_bytes_verified=False
            )
        updated.append(row)
        payloads["candidatas/" + row["variant_id"] + ".json"] = json_bytes(
            {"format": "arcanacart-standing-map-sprite-candidate-2", **row}
        )
    counts = {
        "pending": sum(r["status"] == "pending" for r in updated),
        "error": sum(r["status"] == "error" for r in updated),
        "approved": 0,
    }
    summary = {
        "format": FORMAT,
        "status": "completed",
        "scope": "all",
        "roms": len(updated),
        "bases": report["bases"],
        "variants": report["variants"],
        "counts": counts,
        "source": source_info,
        "source_report_sha256": digest(files["revision.json"]),
        "source_state_sha256": digest(files[mr.STATE]),
        "source_files_preserved": len(files),
        "plan_canonical_sha256": digest(json_bytes(plan)),
        "selected_tail_extensions": len(selected),
        "completed_tail_extensions": sum(
            r.get("tail_extension", {}).get("performed", False) for r in updated
        ),
        "palette_contexts_collected": sum("palette_load_context" in r for r in updated),
        "old_entries_remeasured": 0,
        "old_prefixes_reused": len(updated),
        "additional_unique_stored_sheets": sum(n.startswith("hojas-comprimidas/") for n in payloads),
        "unique_stored_sheets": sum(n.endswith(".lz10") for n in payloads),
        "ready_for_extraction": False,
        "rescanned": False,
        "sheets_decompressed": False,
        "pngs_exported": False,
        "inputs_modified": False,
        "limits": report["limits"]
        + [
            "Only FE8 variants with the audited 8-bit index continue through IDs 128..255.",
            "256 is an observation bound; a zero/invalid record remains only a boundary hint.",
            "The tail continues past boundary hints; later entries are explicitly marked post_boundary_hint.",
            "The new palette code window is evidence for independent review, not automatic palette approval.",
        ],
        "results": updated,
    }
    flat = [
        {"variant_id": r["variant_id"], "game": r["game"], **entry} for r in updated for entry in r["entries"]
    ]
    flat = [
        {k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()}
        for row in flat
    ]
    fields = list(dict.fromkeys(k for row in flat for k in row))
    payloads.update({"revision.json": json_bytes(summary), "entradas.csv": _csv(flat, fields)})
    if (
        len(payloads) >= 100000
        or sum(map(len, payloads.values())) > MAX_PACKET_BYTES
        or any(len(raw) > 32 * 1024 * 1024 for raw in payloads.values())
    ):
        raise ValueError("La evidencia ampliada excede el presupuesto de publicación.")
    _publish(out, payloads, state_name=mr.STATE)
    return {k: v for k, v in summary.items() if k != "results"} | {
        "output": str(out),
        "report": str(out / "revision.json"),
        "error_examples": [
            {"variant_id": r["variant_id"], "error": r["error"]} for r in updated if r["status"] == "error"
        ][:5],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extend = commands.add_parser("extend")
    extend.add_argument("--review", type=Path, required=True)
    extend.add_argument("--datos", type=Path, required=True)
    extend.add_argument("--out", type=Path, required=True)
    extend.add_argument("--identities", type=Path, default=mr.DEFAULT_PLAN)
    extend.add_argument("--zip", type=Path)
    pack = commands.add_parser("pack")
    pack.add_argument("--input", type=Path, required=True)
    pack.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            result = mr.pack_variants(args.input, args.out, state_name=mr.STATE)
        else:
            if args.zip:
                check_destination(args.zip)
                if args.zip.resolve().is_relative_to(args.out.resolve()) or (
                    args.review.is_dir() and args.zip.resolve().is_relative_to(args.review.resolve())
                ):
                    raise ValueError("Guarda el ZIP fuera de las carpetas de revisión.")
            result = extend_review(args.review, args.datos, args.out, args.identities)
            if args.zip:
                result["zip"] = mr.pack_variants(args.out, args.zip, state_name=mr.STATE)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get("counts", {}).get("error") else 0
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc), "rescanned": False}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
