"""Export the explicitly planned portrait ranges of the 43 reviewed variants.

Python 3.10+, the existing ArcanaCart 0.6.2 repository, and its dependencies.
All original AIRs, resource blobs, ROMs and Git files remain read-only.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import html
import importlib
import io
import json
import logging
import os
import re
import struct
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import validacion_retratos as check

RUNNER_VERSION = 2
KINDS = ("portrait", "miniature", "classcard")
SUMMARY_KEYS = {"portrait": "portraits", "miniature": "miniatures", "classcard": "classcards"}


@contextlib.contextmanager
def heartbeat(label: str):
    stop = threading.Event()
    started = time.monotonic()

    def update():
        while not stop.wait(10):
            print(f"  {label}: en curso ({int(time.monotonic() - started)} s).", flush=True)

    worker = threading.Thread(target=update, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=1)


def small_json(path: Path) -> dict:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Archivo auxiliar demasiado grande: " + str(path))
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Se esperaba un objeto JSON: " + str(path))
    return value


def inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Ruta relativa inválida.")
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Una ruta sale de la carpeta prevista: " + relative)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("No se admiten rutas mediante enlaces simbólicos.")
    return path


def plan_text_hash(path: Path) -> str:
    """Hash repository plans/definitions as LF; input AIR/ROM hashes stay exact."""
    return check.digest(path.read_bytes().replace(b"\r\n", b"\n"))


def compatible_version(actual: str, minimum: str) -> bool:
    """Allow patch releases of the same API without changing the saved plan hash."""
    if not all(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", v) for v in (actual, minimum)):
        return False
    current = tuple(map(int, actual.split(".")))
    required = tuple(map(int, minimum.split(".")))
    return current[:2] == required[:2] and current >= required


def read_plan(path: Path) -> tuple[dict, str]:
    plan = small_json(path)
    if plan.get("format") != "arcanacart-bounded-face-batch-1" or plan.get("plan_version") != 1:
        raise ValueError("Formato de planes incompatible.")
    jobs = plan.get("jobs", [])
    if not jobs or len(jobs) > 100:
        raise ValueError("El lote debe contener entre 1 y 100 variantes.")
    ids = set()
    totals = Counter()
    for job in jobs:
        if (
            not re.fullmatch(r"fe[78]-[0-9]{3}", job["id"])
            or job["id"] in ids
            or job["game"] not in plan["bases"]
            or not 1 <= job["last_id"] <= 4095
            or job["first_id"] != 1
            or set(job["expected_counts"]) != set(KINDS)
        ):
            raise ValueError("Entrada de lote inválida o repetida.")
        ids.add(job["id"])
        for value in job["expected_counts"].values():
            if type(value) is not int or not 0 <= value <= job["last_id"]:
                raise ValueError("Conteo previsto inválido.")
        if job["expected_empty_ids"] != sorted(set(job["expected_empty_ids"])) or any(
            type(i) is not int or not 1 <= i <= job["last_id"] for i in job["expected_empty_ids"]
        ):
            raise ValueError("Lista de entradas vacías inválida.")
        for key in ("rom_sha256", "air_sha256", "layout_sha256", "table_bytes_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", job[key]):
                raise ValueError("SHA-256 de plan inválido.")
        layout_file = inside(path.parent, job["layout_file"])
        if plan_text_hash(layout_file) != job["layout_sha256"]:
            raise ValueError("Cambió una definición: " + str(layout_file))
        layout = small_json(layout_file)
        if layout["rom_sha256"] != job["rom_sha256"] or layout["entry_count"] != job["last_id"] + 1:
            raise ValueError("La definición no corresponde al rango planificado.")
        totals.update(job["expected_counts"])
    if dict(totals) != plan["expected_total_counts"] or sum(totals.values()) != plan["expected_total_pngs"]:
        raise ValueError("El total del lote no coincide con sus variantes.")
    return plan, plan_text_hash(path)


def verify_job_inputs(job: dict, layout: dict, api) -> tuple[dict, bytes]:
    air, identity = check.read_air(Path(job["air_path"]))
    if identity["sha256"] != job["air_sha256"]:
        raise ValueError("El AIR cambió desde la comparación; no corresponde a este plan.")
    rom, identity = check.read_file(Path(job["rom_path"]), check.MAX_ROM_BYTES, "Verificando ROM de variante")
    if (
        identity["sha256"] != job["rom_sha256"]
        or air["rom"]["sha256"] != job["rom_sha256"]
        or len(rom) != air["rom"]["size_bytes"]
    ):
        raise ValueError("La ROM no coincide con el SHA-256 y tamaño del AIR y del plan.")
    api.faces.checked_layout(layout, air["rom"])
    pointer = layout["pointer_location"]
    if pointer is None or pointer < 16:
        raise ValueError("Falta el puntero documentado a la tabla.")
    if rom[pointer - 16 : pointer].hex() != job["access_code_hex"]:
        raise ValueError("El código de acceso no coincide con el revisado.")
    actual = check.rom_offset(struct.unpack_from("<I", rom, pointer)[0], rom, 28)
    if actual != layout["table_offset"]:
        raise ValueError("El puntero actual no coincide con la definición.")
    table = rom[actual + 28 : actual + layout["entry_count"] * 28]
    if check.digest(table) != job["table_bytes_sha256"]:
        raise ValueError("Los bytes de la tabla cambiaron desde el diagnóstico.")
    return air, rom


def validate_range(job: dict, layout: dict, rom: bytes, base_rom: bytes, air: dict, api) -> dict:
    probe = check.probe_table(rom, base_rom, air, layout, api)
    errors = list(probe["errors"])
    if not probe.get("access_code_matches_base"):
        errors.append("El código de acceso difiere de la base documentada.")
    if probe.get("inspected_entries") != job["last_id"]:
        errors.append("No se comprobaron todos los IDs previstos.")
    counts = {kind: probe.get("observed_component_counts", {}).get(kind, 0) for kind in KINDS}
    if counts != job["expected_counts"]:
        errors.append("Los componentes válidos no coinciden con los conteos previstos.")
    empty = [row["face_id"] for row in probe["entries"] if row["status"] == "sin_componentes"]
    if empty != job["expected_empty_ids"]:
        errors.append("Las entradas vacías no coinciden con las previstas.")
    for row in probe["entries"]:
        for component in row["components"]:
            if (
                component.get("status") == "estructura_compatible"
                and not component.get("present_in_air")
                and component.get("compression") != "none"
            ):
                errors.append(
                    f"{row['face_id_hex']} {component['kind']}: bloque comprimido ausente del AIR; "
                    "requiere revisión antes de exportar con ArcanaCart 0.6.1."
                )
    probe.update(
        errors=errors,
        range_components_validated=not errors,
        allocated_table_size_confirmed=False,
        expected_empty_ids=empty,
        expected_counts=job["expected_counts"],
        status="rango_validado" if not errors else "requiere_revision",
    )
    # The following bytes remain outside the export and need not enlarge every result ZIP.
    probe.pop("following_bytes_not_validated", None)
    return probe


def assess_result(job: dict, summary: dict) -> tuple[bool, list[str]]:
    problems = []
    counts = {kind: summary.get(SUMMARY_KEYS[kind], 0) for kind in KINDS}
    if counts != job["expected_counts"]:
        problems.append("Los PNG generados no coinciden con los componentes previstos.")
    if summary.get("errors", 1) or summary.get("components_without_real_palette", 1):
        problems.append("Hay errores de componentes o faltan paletas reales.")
    if summary.get("entries_without_observed_graphics") != job["expected_empty_ids"]:
        problems.append("La extracción no conserva las entradas vacías previstas.")
    if (
        not summary.get("rom_bytes_verified")
        or summary.get("rom_sha256") != job["rom_sha256"]
        or summary.get("source_manifest_sha256") != job["air_sha256"]
    ):
        problems.append("Falta la verificación de los archivos de entrada.")
    if summary.get("status") not in ("completed", "partial") or summary.get("rescanned") is not False:
        problems.append("Estado de extracción inesperado.")
    return not problems, problems


def file_hash(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def cached_result(out: Path, job: dict, previous: dict, plan_hash: str) -> dict | None:
    try:
        directory = inside(out, previous["directory"])
        report_path = directory / "resultado.json"
        if file_hash(report_path) != previous["report_sha256"]:
            return None
        report = small_json(report_path)
        if (
            report["status"] != "completed"
            or report["plan_sha256"] != plan_hash
            or report["id"] != job["id"]
            or report["air_sha256"] != job["air_sha256"]
            or report["rom_sha256"] != job["rom_sha256"]
            or report["layout_sha256"] != job["layout_sha256"]
        ):
            return None
        if file_hash(directory / "validacion.json") != report["validation_sha256"]:
            return None
        faces = directory / "galeria"
        if file_hash(faces / "faces-state.json") != report["faces_state_sha256"]:
            return None
        state = small_json(faces / "faces-state.json")
        if state["status"] not in ("completed", "partial") or not state.get("artifacts"):
            return None
        for name, expected in state["artifacts"].items():
            if file_hash(inside(faces, name)) != expected:
                return None
        summary = small_json(faces / "summary.json")
        if not assess_result(job, summary)[0] or summary != report["summary"]:
            return None
        return {
            **previous,
            "inputs_reverified": True,
            "status": "completed",
            "counts": report["actual_counts"],
            "empty_ids": job["expected_empty_ids"],
            "error": "",
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def latest_run(parent: Path, plan_hash: str) -> Path | None:
    if not parent.is_dir():
        return None
    candidates = []
    for path in parent.glob("retratos-variantes-*"):
        if not path.is_dir() or path.is_symlink():
            continue
        state = path / "run-state.json"
        try:
            value = small_json(state)
            if value.get("plan_sha256") == plan_hash and value.get("runner_version") == RUNNER_VERSION:
                candidates.append((state.stat().st_mtime_ns, path))
        except (OSError, ValueError, TypeError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def next_attempt(out: Path, job_id: str) -> Path:
    first = out / job_id
    return first if not first.exists() else out / (job_id + "-r" + uuid.uuid4().hex[:6])


def checkpoint(out: Path, plan: dict, state: dict) -> dict:
    rows, counts = [], Counter()
    completed = 0
    for job in plan["jobs"]:
        record = state["jobs"].get(job["id"], {})
        verified = record.get("inputs_reverified") is True
        status = record.get("status", "pending") if verified else "pending"
        if status == "completed":
            completed += 1
        if verified:
            counts.update(record.get("counts", {}))
        rows.append(
            {
                "Juego": job["game"],
                "Variante": job["variant"],
                "Estado": status,
                "PrimerID": 1,
                "UltimoID": job["last_id"],
                "Retratos": record.get("counts", {}).get("portrait", 0) if verified else 0,
                "Miniaturas": record.get("counts", {}).get("miniature", 0) if verified else 0,
                "Tarjetas": record.get("counts", {}).get("classcard", 0) if verified else 0,
                "PNGEsperados": sum(job["expected_counts"].values()),
                "IDsVaciosPrevistos": len(job["expected_empty_ids"]),
                "Carpeta": record.get("directory", ""),
                "Detalle": record.get("error", ""),
            }
        )
    summary = {
        "format": "arcanacart-bounded-face-batch-result-1",
        "runner_version": RUNNER_VERSION,
        "plan_sha256": state["plan_sha256"],
        "run_status": state["run_status"],
        "output_directory": str(out),
        "found_variants": len(plan["jobs"]),
        "completed_variants": completed,
        "pending_variants": len(plan["jobs"]) - completed,
        "current_variant": state.get("current_variant"),
        "expected_total_pngs": plan["expected_total_pngs"],
        "generated_counts": {kind: counts[kind] for kind in KINDS},
        "generated_component_pngs": sum(counts.values()),
        "allocated_table_sizes_confirmed": False,
        "rescanned": False,
        "inputs_modified": False,
        "git_modified": False,
        "scope": plan["scope"],
        "variants": rows,
    }
    check.atomic_json(out / "run-state.json", state)
    check.atomic_json(out / "resumen.json", summary)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    check.atomic_bytes(out / "resumen.csv", stream.getvalue().encode("utf-8-sig"))
    html_rows = []
    esc = html.escape
    for row in rows:
        folder = row["Carpeta"]
        # A failed/unfinished gallery is deliberately shown as a report, not a successful gallery.
        target = (
            folder + "/galeria/index.html" if row["Estado"] == "completed" else folder + "/resultado.json"
        )
        link = (
            f'<a href="{esc(target, quote=True)}">Abrir</a>'
            if folder and inside(out, target).is_file()
            else "—"
        )
        html_rows.append(
            "<tr>"
            + "".join(
                f"<td>{esc(str(value))}</td>"
                for value in (
                    row["Juego"].upper(),
                    row["Variante"],
                    row["Estado"],
                    row["Retratos"],
                    row["Miniaturas"],
                    row["Tarjetas"],
                    row["IDsVaciosPrevistos"],
                )
            )
            + f"<td>{link}</td></tr>"
        )
    document = f"""<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Retratos de las variantes</title>
<style>body{{font:16px system-ui;max-width:1400px;margin:2rem auto;padding:0 1rem;color:#172033;background:#fafbff}}
table{{border-collapse:collapse;width:100%;background:white}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #ccd2df}}
th{{background:#edf0f8}}a{{color:#1b48a0}}.scroll{{overflow:auto}}td:nth-child(2){{min-width:20rem;overflow-wrap:anywhere}}
small{{color:#46516a}}</style><h1>Retratos de las variantes</h1>
<p><strong>{completed}/{len(rows)} variantes completadas en el rango previsto.</strong>
{sum(counts.values()):,} PNG de componentes generados; {plan["expected_total_pngs"]:,} esperados.</p>
<p>FE7: IDs 0x001–0x0E4. FE8: IDs 0x001–0x0FE. Las entradas vacías previstas se conservan.
Los totales incluyen componentes repetidos entre variantes.</p>
<p><a href="resumen.csv">Resumen CSV</a> · <a href="resumen.json">Resultado detallado</a></p>
<div class="scroll"><table><caption>Galerías por variante</caption><thead><tr>
<th scope="col">Juego</th><th scope="col">Variante</th><th scope="col">Estado</th><th scope="col">Retratos</th>
<th scope="col">Miniaturas</th><th scope="col">Tarjetas</th><th scope="col">IDs vacíos</th><th scope="col">Galería</th>
</tr></thead><tbody>{"".join(html_rows)}</tbody></table></div>
<p><small>{esc(plan["scope"])}</small></p></html>"""
    check.atomic_bytes(out / "index.html", document.encode("utf-8"))
    return summary


def save_archive(out: Path, state: dict, interrupted: bool) -> Path:
    suffix = "-interrumpido-" if interrupted else "-resultado-"
    destination = out.with_name(
        out.name + suffix + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6] + ".zip"
    )
    temporary = destination.with_name("." + destination.name + ".tmp")
    names = {"run-state.json", "resumen.json", "resumen.csv", "index.html", "LEEME.txt", "planes-usados.json"}
    for record in state["jobs"].values():
        directory = inside(out, record["directory"])
        if directory.is_dir():
            names.update(
                path.relative_to(out).as_posix()
                for path in directory.rglob("*")
                if path.is_file() and not any(part.startswith(".") for part in path.relative_to(out).parts)
            )
    try:
        with ZipFile(temporary, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for name in sorted(names):
                source = inside(out, name)
                if source.is_file():
                    archive.write(source, name)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def run(
    repo: Path,
    plan_path: Path,
    out: Path | None = None,
    *,
    resume: bool = False,
    output_parent: Path | None = None,
    api=None,
) -> tuple[int, Path]:
    plan, plan_hash = read_plan(plan_path)
    api = api or check.load_api(repo)
    api.faces = importlib.import_module("arcanacart.faces")
    if not compatible_version(api.version, plan["required_tool_version"]):
        raise ValueError(
            "Este lote requiere una versión compatible con ArcanaCart " + plan["required_tool_version"] + "."
        )
    base_roms = {}
    for game, base in plan["bases"].items():
        print("Verificando base " + game.upper() + "...", flush=True)
        raw, identity = check.read_file(Path(base["rom_path"]), check.MAX_ROM_BYTES, "Verificando ROM base")
        if identity["sha256"] != base["rom_sha256"]:
            raise ValueError("La base " + game + " no coincide con el SHA-256 documentado.")
        base_roms[game] = raw
    parent = (output_parent or Path(plan["default_output_parent"])).resolve()
    if out is None and resume:
        out = latest_run(parent, plan_hash)
    out = (
        out
        or parent
        / ("retratos-variantes-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    ).resolve()
    state = {
        "format": "arcanacart-bounded-face-checkpoint-1",
        "runner_version": RUNNER_VERSION,
        "plan_sha256": plan_hash,
        "run_status": "running",
        "current_variant": None,
        "jobs": {},
    }
    if out.exists():
        if not resume or not out.is_dir():
            raise ValueError("La salida existe. Usa --resume-latest o elige otra carpeta.")
        old = small_json(out / "run-state.json")
        if old.get("plan_sha256") != plan_hash or old.get("runner_version") != RUNNER_VERSION:
            raise ValueError("La salida anterior corresponde a otro plan.")
        state["jobs"] = {key: {**value, "inputs_reverified": False} for key, value in old["jobs"].items()}
    else:
        out.mkdir(parents=True, exist_ok=False)
    for job in plan["jobs"]:
        for source in (
            Path(job["air_path"]),
            Path(job["rom_path"]),
            Path(job["air_path"]).parent / "resources",
        ):
            if out.is_relative_to(source.resolve()) or source.resolve().is_relative_to(out):
                raise ValueError("La salida debe estar separada de los archivos de entrada.")
    print(
        f"ArcanaCart {api.version}; {len(plan['jobs'])} variantes; {plan['expected_total_pngs']} PNG previstos.",
        flush=True,
    )
    print("Salida: " + str(out), flush=True)
    print("Se validan y exportan rangos explícitos; no se ejecuta el escáner.", flush=True)
    interrupted = False
    with api.faces.workspace_lock(out):
        check.atomic_json(out / "planes-usados.json", plan)
        check.atomic_bytes(
            out / "LEEME.txt",
            (
                "Abre index.html. Los originales se leen sin modificarlos. El ZIP contiene las galerías e informes "
                "de los intentos activos; los intentos anteriores permanecen en disco.\n"
                "Los totales cuentan PNG de componentes, incluidos los repetidos entre variantes. "
                "Las entradas vacías previstas no son fallos.\n"
                "El estado del lote valida el rango previsto; summary.json de ArcanaCart se conserva intacto "
                "y puede decir partial si la tabla contiene entradas vacías conocidas.\n"
                + plan["scope"]
                + "\n"
            ).encode("utf-8"),
        )
        checkpoint(out, plan, state)
        try:
            for number, job in enumerate(plan["jobs"], 1):
                key = job["id"]
                state["current_variant"] = key
                checkpoint(out, plan, state)
                print(f"[{number}/{len(plan['jobs'])}] {job['game']} / {job['variant']}", flush=True)
                directory = None
                try:
                    layout_file = inside(plan_path.parent, job["layout_file"])
                    layout = small_json(layout_file)
                    air, rom = verify_job_inputs(job, layout, api)
                    previous = state["jobs"].get(key)
                    cached = cached_result(out, job, previous, plan_hash) if previous else None
                    if cached:
                        state["jobs"][key] = cached
                        print(
                            "  Recuperado: entradas y archivos exportados verificados; no se repite.",
                            flush=True,
                        )
                        del air, rom
                        checkpoint(out, plan, state)
                        continue
                    directory = next_attempt(out, key)
                    directory.mkdir(parents=True, exist_ok=False)
                    state["jobs"][key] = {
                        "directory": directory.relative_to(out).as_posix(),
                        "status": "running",
                        "inputs_reverified": True,
                    }
                    checkpoint(out, plan, state)
                    print(f"  Comprobando IDs 1..{job['last_id']}, datos y paletas...", flush=True)
                    probe = validate_range(job, layout, rom, base_roms[job["game"]], air, api)
                    check.atomic_json(directory / "validacion.json", probe)
                    if not probe["range_components_validated"]:
                        raise ValueError("; ".join(probe["errors"][:8]))
                    del air, rom
                    print(f"  Exportando con ArcanaCart {api.version}...", flush=True)
                    with heartbeat("Exportación de " + key):
                        api.faces.reconstruct_faces(
                            Path(job["air_path"]),
                            directory / "galeria",
                            rom_path=Path(job["rom_path"]),
                            definition=layout_file,
                        )
                    summary = small_json(directory / "galeria/summary.json")
                    completed, problems = assess_result(job, summary)
                    counts = {kind: summary[SUMMARY_KEYS[kind]] for kind in KINDS}
                    report = {
                        "format": "arcanacart-bounded-face-result-1",
                        "id": key,
                        "variant": job["variant"],
                        "status": "completed" if completed else "requires_review",
                        "plan_sha256": plan_hash,
                        "air_sha256": job["air_sha256"],
                        "rom_sha256": job["rom_sha256"],
                        "layout_sha256": job["layout_sha256"],
                        "validation_sha256": file_hash(directory / "validacion.json"),
                        "faces_state_sha256": file_hash(directory / "galeria/faces-state.json"),
                        "expected_counts": job["expected_counts"],
                        "actual_counts": counts,
                        "expected_empty_ids": job["expected_empty_ids"],
                        "problems": problems,
                        "scope": plan["scope"],
                        "summary": summary,
                    }
                    check.atomic_json(directory / "resultado.json", report)
                    state["jobs"][key].update(
                        status=report["status"],
                        counts=counts,
                        report_sha256=file_hash(directory / "resultado.json"),
                        error="; ".join(problems),
                    )
                    print(
                        f"  {report['status']}: retratos {counts['portrait']}; miniaturas {counts['miniature']}; "
                        f"tarjetas {counts['classcard']}; IDs vacíos previstos {len(job['expected_empty_ids'])}.",
                        flush=True,
                    )
                except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
                    if directory is None:
                        directory = next_attempt(out, key)
                        directory.mkdir(parents=True, exist_ok=False)
                    error = str(exc)
                    report = {"id": key, "status": "error", "error": error, "plan_sha256": plan_hash}
                    check.atomic_json(directory / "resultado.json", report)
                    state["jobs"][key] = {
                        "directory": directory.relative_to(out).as_posix(),
                        "status": "error",
                        "inputs_reverified": True,
                        "error": error,
                        "report_sha256": file_hash(directory / "resultado.json"),
                    }
                    print("  ERROR: " + error, flush=True)
                finally:
                    checkpoint(out, plan, state)
            state["current_variant"] = None
            state["run_status"] = (
                "completed"
                if all(
                    r.get("status") == "completed" and r.get("inputs_reverified")
                    for r in state["jobs"].values()
                )
                and len(state["jobs"]) == len(plan["jobs"])
                else "requires_review"
            )
        except KeyboardInterrupt:
            interrupted = True
            state["run_status"] = "interrupted"
            print(
                "\nInterrumpido. Se conservan los resultados terminados y se prepara un ZIP parcial.",
                flush=True,
            )
        summary = checkpoint(out, plan, state)
        print("Preparando ZIP de resultados...", flush=True)
        with heartbeat("Empaquetado del ZIP"):
            archive = save_archive(out, state, interrupted)
    print(
        f"Variantes completadas: {summary['completed_variants']}/{len(plan['jobs'])}; "
        f"PNG de componentes: {summary['generated_component_pngs']}.",
        flush=True,
    )
    print("Galería: " + str(out / "index.html"), flush=True)
    print("ZIP: " + str(archive), flush=True)
    return (130 if interrupted else (0 if state["run_status"] == "completed" else 2)), archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--plan", type=Path, default=Path(__file__).resolve().with_name("planes.json"))
    parser.add_argument("--out", type=Path, help="Carpeta de resultados explícita.")
    parser.add_argument("--output-parent", type=Path, help="Carpeta donde buscar/crear el lote.")
    parser.add_argument("--resume-latest", action="store_true")
    parser.add_argument("--abrir", action="store_true", help="Abrir el índice del lote al terminar.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        code, archive = run(
            args.repo.resolve(),
            args.plan.resolve(),
            args.out,
            resume=args.resume_latest,
            output_parent=args.output_parent,
        )
        if args.abrir:
            with ZipFile(archive) as z:
                out = Path(json.loads(z.read("resumen.json"))["output_directory"])
            if out and (out / "index.html").is_file():
                if os.name == "nt":
                    os.startfile(out / "index.html")
                else:
                    import webbrowser

                    webbrowser.open((out / "index.html").as_uri())
        return code
    except KeyboardInterrupt:
        print(
            "\nInterrumpido. Los resultados anteriores siguen en disco; vuelve a usar --resume-latest.",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
