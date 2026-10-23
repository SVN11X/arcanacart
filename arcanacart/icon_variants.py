"""Review hash-bound variant icon windows, then extract only verified definitions."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from arcanacart.core.io import atomic_json, atomic_write, digest, json_bytes, read_bounded, staged_file
from arcanacart.icon_package import _document, _relative
from arcanacart.icons import (
    BUILTIN_LAYOUTS, ICON_BYTES, MAX_ICONS, _csv, _json_file, _pointer, _safe,
    checked_layout, extract_icons,
)
from arcanacart.pipeline import load_rom
from arcanacart.resource_compare import _checked

PLAN_FORMAT = "arcanacart-item-icon-variant-plan-1"
REVIEW_FORMAT = "arcanacart-item-icon-variant-review-1"
DEFAULT_PLAN = Path(__file__).resolve().parents[1] / "scripts/variantes/iconos/variantes.json"
STATE = "variant-icons-state.json"
HASH = re.compile(r"[0-9a-f]{64}")
RANGE_FIELDS = {"first_id", "last_id", "table_offset", "palette_offset", "bank_sha256",
                "palette_sha256", "icon_context_sha256", "palette_context_sha256", "evidence"}


def _hash(value: object) -> bool:
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _plan(path: Path) -> dict:
    value, _ = _json_file(path, 1024 * 1024)
    rows, ranges = value.get("variants"), value.get("reviewed_ranges")
    if value.get("format") != PLAN_FORMAT or not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("Plan de variantes inválido.")
    if not isinstance(ranges, dict):
        raise ValueError("Falta reviewed_ranges en el plan.")
    ids = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("game"), str)
            or row["game"] not in {"fe7", "fe8"}):
            raise ValueError("Juego de variante inválido.")
        vid = row.get("variant_id")
        if not isinstance(vid, str) or re.fullmatch(row["game"] + r"-[0-9]{3}", vid) is None or vid in ids:
            raise ValueError("ID de variante inválido o repetido.")
        ids.add(vid)
        if not isinstance(row.get("variant"), str) or not row["variant"].strip():
            raise ValueError("Falta el nombre de variante.")
        for field in ("rom_sha256", "air_sha256"):
            if not _hash(row.get(field)):
                raise ValueError("Hash de ROM/AIR inválido en el plan.")
        for field in ("rom_relative_path", "air_relative_path"):
            name = _relative(row.get(field))
            if name.split("/", 1)[0] != row["game"]:
                raise ValueError("Ruta de entrada incompatible con el juego.")
    if not set(ranges) <= ids:
        raise ValueError("El plan revisa una variante no registrada.")
    for spec in ranges.values():
        if not isinstance(spec, dict) or set(spec) != RANGE_FIELDS:
            raise ValueError("Evidencia de rango revisado inválida.")
        if (type(spec["first_id"]) is not int or spec["first_id"] != 0
            or type(spec["last_id"]) is not int or not 0 <= spec["last_id"] < MAX_ICONS
            or any(type(spec[k]) is not int or spec[k] < 0 for k in ("table_offset", "palette_offset"))
            or any(not _hash(spec[k]) for k in RANGE_FIELDS if k.endswith("sha256"))
            or not isinstance(spec["evidence"], list) or not 1 <= len(spec["evidence"]) <= 8
            or any(not isinstance(s, str) or not s.strip() or len(s) > 1800 for s in spec["evidence"])):
            raise ValueError("Rango revisado sin hashes, límites o fuentes válidas.")
    return value


def _input(datos: Path, name: str) -> Path:
    path = datos / "resultados" / _relative(name)
    _safe(path)
    return path


def _destination(out: Path, inputs: list[Path]) -> None:
    _safe(out)
    if out.exists():
        raise ValueError("Usa una carpeta de salida nueva; no se reemplazan resultados.")
    if any(p.resolve().is_relative_to(out.resolve()) for p in inputs):
        raise ValueError("La salida contiene una entrada; elige otra carpeta.")


def _bases(datos: Path, games: set[str]) -> dict:
    result = {}
    for spec in BUILTIN_LAYOUTS.values():
        game = spec["game"]
        if game not in games:
            continue
        path = _input(datos, game + "/" + game + "-usa-base.gba")
        data, rom = load_rom(path)
        if rom["sha256"] != spec["rom_sha256"]:
            raise ValueError("No corresponde a la base exacta: " + game)
        result[game] = (data, checked_layout(spec, rom, data))
    if set(result) != games:
        raise ValueError("No existe una base para todos los juegos del plan.")
    return result


def _context(data: bytes, location: int) -> bytes:
    if location < 64 or location + 4 > len(data):
        raise ValueError("No se puede leer el contexto acotado del puntero.")
    return data[location - 64:location + 4]


def _inspect(row: dict, datos: Path, bases: dict, reviewed: dict | None,
             loaded: tuple[bytes, dict] | None = None) -> tuple[dict, dict[str, bytes]]:
    """No scan, decompression or PNG export. Candidate windows are not approvals."""
    rom_path = _input(datos, row["rom_relative_path"])
    air_path = _input(datos, row["air_relative_path"])
    data, rom = loaded if loaded is not None else load_rom(rom_path)
    if rom["sha256"] != row["rom_sha256"]:
        raise ValueError("Los bytes de ROM no coinciden con el hash registrado.")
    air, air_hash = _json_file(air_path, 64 * 1024 * 1024)
    if air_hash != row["air_sha256"]:
        raise ValueError("Los bytes exactos del AIR no coinciden; no se normalizan LF/CRLF.")
    records, scan, _ = _checked(air)
    if air["rom"]["sha256"] != rom["sha256"] or air["rom"]["size_bytes"] != len(data):
        raise ValueError("La identidad y el tamaño del AIR no corresponden a la ROM.")
    base, original = bases[row["game"]]
    count = reviewed["last_id"] + 1 if reviewed else original["icon_count"]
    table = _pointer(data, original["pointer_location"], count * ICON_BYTES)
    palette = _pointer(data, original["palette_pointer_location"], 32)
    # FEBuilder documents FEditorAdv code inside the final original FE7 icon.
    feditor = (row["game"] == "fe7" and table == original["table_offset"]
               and len(data) >= 0xCB51E and data[0xCB51A:0xCB51E] == bytes.fromhex("02494018"))
    if feditor:
        if reviewed and reviewed["last_id"] >= 0xAC:
            raise ValueError("El rango incluye el código FEditorAdv de la última posición FE7.")
        count = min(count, 0xAC)
    spec = {**original, "rom_sha256": rom["sha256"], "table_offset": table,
            "palette_offset": palette, "icon_count": count}
    layout = checked_layout(spec, rom, data)
    bank = data[table:table + count * ICON_BYTES]
    palette_raw = data[palette:palette + 32]
    contexts = {k: _context(data, original[k + "_location"])
                for k in ("pointer", "palette_pointer")}
    masked = {k: raw[:-4] == _context(base, original[k + "_location"])[:-4]
              for k, raw in contexts.items()}
    base_bank = base[original["table_offset"]:original["table_offset"] + count * ICON_BYTES]
    same_bank = count <= original["icon_count"] and bank == base_bank
    same_palette = palette_raw == base[original["palette_offset"]:original["palette_offset"] + 32]
    proof = {"first_id": 0, "last_id": count - 1, "table_offset": table,
             "palette_offset": palette, "bank_sha256": digest(bank), "palette_sha256": digest(palette_raw),
             "icon_context_sha256": digest(contexts["pointer"]),
             "palette_context_sha256": digest(contexts["palette_pointer"])}
    if reviewed:
        if any(reviewed[k] != v for k, v in proof.items()):
            raise ValueError("El rango revisado no coincide con los bytes, punteros o contextos actuales.")
        verified = True
        reason = "explicit-hash-bound-range-review"
        layout["sources"] = layout["sources"] + reviewed["evidence"]
    else:
        verified = same_bank and same_palette and all(masked.values())
        reason = "base-identical-bounded-prefix" if verified else "changed-data-or-access-context-needs-review"
    vid = row["variant_id"]
    folder = "evidencias/" + vid + "/"
    payloads = {folder + "banco-candidato.bin": bank, folder + "paleta.bin": palette_raw,
                folder + "contexto-iconos.bin": contexts["pointer"],
                folder + "contexto-paleta.bin": contexts["palette_pointer"]}
    following = data[table + len(bank):table + len(bank) + 128]
    payloads[folder + "despues-del-rango.bin"] = following
    definition = ("definiciones/" if verified else "candidatas/") + vid + ".json"
    payloads[definition] = json_bytes(layout)
    result = {**row, **proof, "status": "verified" if verified else "pending", "reason": reason,
              "definition_file": definition, "rom_size_bytes": len(data),
              "pointer_location": original["pointer_location"],
              "pointer_value": struct.unpack_from("<I", data, original["pointer_location"])[0],
              "palette_pointer_location": original["palette_pointer_location"],
              "palette_pointer_value": struct.unpack_from("<I", data, original["palette_pointer_location"])[0],
              "icon_count": count, "icon_bytes": ICON_BYTES, "base_bank_identical": same_bank,
              "base_palette_identical": same_palette, "access_context_matches_base": masked,
              "context_bytes_before_pointer": 64, "feditor_final_slot_excluded": bool(feditor),
              "table_relocated": table != original["table_offset"],
              "palette_relocated": palette != original["palette_offset"],
              "air_candidates_inventoried": len(records), "source_scan_truncated": scan["truncated"],
              "evidence_directory": folder, "following_bytes_are_icons": None,
              "table_capacity_confirmed": False, "error": None}
    return result, payloads


def _publish(out: Path, payloads: dict[str, bytes]) -> None:
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    atomic_json(out / STATE, {"status": "running"})
    try:
        for name, raw in sorted(payloads.items()):
            atomic_write(out / _relative(name), raw)
        atomic_json(out / STATE, {"status": "completed", "artifacts": {
            name: digest(raw) for name, raw in sorted(payloads.items())}}, force=True)
    except Exception:
        atomic_json(out / STATE, {"status": "failed"}, force=True)
        raise


def review_variants(datos: Path, out: Path, plan_path: Path = DEFAULT_PLAN) -> dict:
    _safe(datos)
    _safe(plan_path)
    plan = _plan(plan_path)
    inputs = [plan_path] + [_input(datos, r[k]) for r in plan["variants"]
                           for k in ("rom_relative_path", "air_relative_path")]
    _destination(out, inputs)
    bases = _bases(datos, {r["game"] for r in plan["variants"]})
    payloads = {"plan-usado.json": json_bytes(plan)}
    results = []
    for row in plan["variants"]:
        code_window = None
        try:
            loaded = load_rom(_input(datos, row["rom_relative_path"]))
            if loaded[1]["sha256"] != row["rom_sha256"]:
                raise ValueError("Los bytes de ROM no coinciden con el hash registrado.")
            original = bases[row["game"]][1]
            locations = [original[k] for k in ("pointer_location", "palette_pointer_location")]
            begin, end = max(0, min(locations) - 128), max(locations) + 132
            name = "evidencias/" + row["variant_id"] + "/ventana-codigo.bin"
            raw = loaded[0][begin:end]
            payloads[name] = raw
            code_window = {"offset": begin, "size_bytes": len(raw), "sha256": digest(raw), "file": name}
            result, evidence = _inspect(row, datos, bases, plan["reviewed_ranges"].get(row["variant_id"]), loaded)
            payloads.update(evidence)
        except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
            result = {**row, "status": "error", "error": str(exc)}
        result["code_window"] = code_window
        results.append(result)
    counts = {s: sum(r["status"] == s for r in results) for s in ("verified", "pending", "error")}
    report = {"format": REVIEW_FORMAT, "status": "completed", "variants": len(results),
              "counts": counts, "ready_for_full_batch": counts["verified"] == len(results),
              "plan_canonical_sha256": digest(json_bytes(plan)), "results": results,
              "rescanned": False, "icons_exported": False, "inputs_modified": False,
              "scope": "Solo los prefijos verificados; no se confirma capacidad total ni recursos de otros bancos."}
    payloads["revision.json"] = json_bytes(report)
    fields = ["variant_id", "game", "variant", "status", "first_id", "last_id", "table_offset",
              "palette_offset", "reason", "rom_sha256", "air_sha256", "error"]
    payloads["revision.csv"] = _csv(results, fields)
    payloads["LEEME.txt"] = (
        "revision.json y revision.csv distinguen verified, pending y error.\n"
        "Solo definiciones/ habilita la extraccion. candidatas/ NO esta aprobada.\n"
        "Los .bin son evidencia de ventanas acotadas, no ROM completas.\n"
        "Un contexto de 64 bytes no demuestra por si solo que el acceso sea identico.\n"
        "Sin revision explicita, solo se admite un prefijo y paleta identicos a la base,\n"
        "con ambos contextos iguales salvo el valor de sus punteros.\n"
        "No se confirma el final de tablas reubicadas ni se hereda el limite 0xFE.\n"
    ).encode()
    _publish(out, payloads)
    return {k: v for k, v in report.items() if k != "results"} | {"output": str(out)}


def _sealed(source: Path) -> dict[str, bytes]:
    _safe(source)
    if not source.is_dir():
        raise ValueError("No existe la carpeta de revisión/lote.")
    payloads, total, names = {}, 0, set()
    for path in sorted(source.rglob("*")):
        _safe(path)
        if path.is_dir():
            continue
        name = _relative(path.relative_to(source).as_posix())
        if name.casefold() in names or len(names) >= 100000:
            raise ValueError("Colisión de nombres o demasiados archivos.")
        names.add(name.casefold())
        raw = read_bounded(path, 32 * 1024 * 1024)
        total += len(raw)
        if total > 256 * 1024 * 1024:
            raise ValueError("El paquete excede 256 MiB.")
        payloads[name] = raw
    state = _document(payloads, STATE)
    if state.get("status") != "completed" or not isinstance(state.get("artifacts"), dict):
        raise ValueError("La revisión/lote no terminó correctamente.")
    if set(state["artifacts"]) != set(payloads) - {STATE}:
        raise ValueError("Hay archivos adicionales o faltan artefactos.")
    for name, sha in state["artifacts"].items():
        if not _hash(sha) or digest(payloads[name]) != sha:
            raise ValueError("SHA-256 incorrecto en " + name)
    return payloads


def pack_variants(source: Path, out: Path) -> dict:
    _safe(out)
    if out.resolve().is_relative_to(source.resolve()):
        raise ValueError("El ZIP debe quedar fuera de la carpeta de entrada.")
    payloads = _sealed(source)
    with staged_file(out) as (stream, _):
        with ZipFile(stream, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name, raw in sorted(payloads.items()):
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system, info.external_attr = 3, 0o100644 << 16
                archive.writestr(info, raw, compress_type=ZIP_DEFLATED, compresslevel=9)
        stream.seek(0)
        with ZipFile(stream) as archive:
            if archive.testzip() is not None:
                raise ValueError("Error CRC en el ZIP generado.")
        stream.seek(0)
        import hashlib
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
        hash_ = hasher.hexdigest()
    return {"status": "completed", "files": len(payloads), "sha256": hash_, "output": str(out),
            "portable_paths": True, "crc_verified": True, "rescanned": False}


def extract_variants(datos: Path, review: Path, out: Path, plan_path: Path = DEFAULT_PLAN,
                     *, only_verified: bool = False) -> dict:
    _safe(datos)
    _safe(plan_path)
    plan = _plan(plan_path)
    saved = _sealed(review)
    report = _document(saved, "revision.json")
    if (report.get("format") != REVIEW_FORMAT or report.get("status") != "completed"
        or report.get("plan_canonical_sha256") != digest(json_bytes(plan))
        or _document(saved, "plan-usado.json") != plan):
        raise ValueError("La revisión no corresponde al plan actual; vuelve a revisar.")
    rows = report.get("results")
    expected = {r["variant_id"] for r in plan["variants"]}
    if (not isinstance(rows, list) or len(rows) != len(expected)
        or any(not isinstance(r, dict) or r.get("status") not in {"verified", "pending", "error"} for r in rows)
        or {r.get("variant_id") for r in rows} != expected):
        raise ValueError("La revisión no contiene exactamente las variantes del plan.")
    chosen = {r["variant_id"]: r for r in rows if r["status"] == "verified"}
    if not chosen or (not only_verified and len(chosen) != len(expected)):
        raise ValueError("Quedan variantes sin verificar. No se inicia un lote parcial sin --only-verified.")
    inputs = [review, plan_path] + [_input(datos, r[k]) for r in plan["variants"]
                                   for k in ("rom_relative_path", "air_relative_path")]
    _destination(out, inputs)
    if out.resolve().is_relative_to(review.resolve()):
        raise ValueError("La salida debe estar separada de la revisión.")
    bases = _bases(datos, {r["game"] for r in plan["variants"]})
    jobs = []
    # Recompute the review from the exact ROM/AIR bytes and the trusted current
    # plan. Editing a status plus its manifest cannot promote a candidate.
    for row in plan["variants"]:
        vid = row["variant_id"]
        if vid not in chosen:
            continue
        current, evidence = _inspect(row, datos, bases, plan["reviewed_ranges"].get(vid))
        definition = "definiciones/" + vid + ".json"
        # The additional code_window is evidence captured by review(), not a
        # field returned by the single-variant inspector.
        previous = {k: v for k, v in chosen[vid].items() if k != "code_window"}
        if (current["status"] != "verified" or previous != current
            or saved.get(definition) != evidence.get(definition)):
            raise ValueError("La definición o evidencia no coincide con los bytes actuales: " + vid)
        jobs.append((row, saved[definition]))
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    atomic_json(out / STATE, {"status": "running"})
    results, occurrences = [], []
    try:
        for row, definition_raw in jobs:
            vid = row["variant_id"]
            definition_path = out / "definiciones" / (vid + ".json")
            atomic_write(definition_path, definition_raw)
            result = extract_icons(_input(datos, row["rom_relative_path"]), out / vid,
                                   source=_input(datos, row["air_relative_path"]),
                                   definition=definition_path)
            results.append({"variant_id": vid, "variant": row["variant"], **result})
            catalog = json.loads(read_bounded(out / vid / "catalog.json", 16 * 1024 * 1024))
            for icon in catalog["icons"]:
                origin = {"variant_id": vid, "variant": row["variant"], **icon}
                for key in ("file", "raw_file", "palette_file"):
                    origin[key] = vid + "/" + origin[key]
                occurrences.append(origin)
        summary = {"format": "arcanacart-item-icon-variant-batch-1", "status": "completed",
                   "expected_variants": len(expected), "processed_variants": len(results),
                   "skipped_variants": sorted(expected - set(chosen)), "partial_selection": only_verified,
                   "icon_occurrences": len(occurrences),
                   "unique_pngs_across_variants": len({r["png_sha256"] for r in occurrences}),
                   "review_report_sha256": digest(saved["revision.json"]),
                   "plan_canonical_sha256": digest(json_bytes(plan)), "results": results,
                   "rescanned": False, "inputs_modified": False}
        atomic_json(out / "resumen.json", summary)
        atomic_write(out / "ocurrencias.csv", _csv(occurrences, list(occurrences[0])))
        atomic_write(out / "galerias.csv", _csv(results, ["variant_id", "game", "variant", "first_id",
                                                        "last_id", "icon_occurrences", "unique_images", "gallery"]))
        artifacts = {p.relative_to(out).as_posix(): digest(read_bounded(p, 32 * 1024 * 1024))
                     for p in sorted(out.rglob("*")) if p.is_file() and p != out / STATE}
        atomic_json(out / STATE, {"status": "completed", "artifacts": artifacts}, force=True)
    except Exception:
        atomic_json(out / STATE, {"status": "failed"}, force=True)
        raise
    return {k: v for k, v in summary.items() if k != "results"} | {"output": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "extract"):
        command = commands.add_parser(name)
        command.add_argument("--datos", type=Path, required=True)
        command.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--zip", type=Path)
        if name == "extract":
            command.add_argument("--review", type=Path, required=True)
            command.add_argument("--only-verified", action="store_true")
    command = commands.add_parser("pack")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            result = pack_variants(args.input, args.out)
        else:
            if args.zip:
                from arcanacart.core.io import check_destination
                check_destination(args.zip)
                if args.zip.resolve().is_relative_to(args.out.resolve()):
                    raise ValueError("Guarda el ZIP fuera de su carpeta de entrada.")
            if args.command == "review":
                result = review_variants(args.datos, args.out, args.plan)
            else:
                result = extract_variants(args.datos, args.review, args.out, args.plan,
                                          only_verified=args.only_verified)
            if args.zip:
                result["zip"] = pack_variants(args.out, args.zip)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "rescanned": False}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
