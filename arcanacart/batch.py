"""Fire Emblem workspace: canonical input copies, independent UPS variants and reports."""

from __future__ import annotations

import copy
import html
import re
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile

from arcanacart import __version__
from arcanacart.compare import binary_compare, semantic_compare
from arcanacart.compression import ScanLimits
from arcanacart.core.io import (
    atomic_json,
    atomic_write,
    check_destination,
    digest,
    json_bytes,
    read_json,
    workspace_lock,
)
from arcanacart.patchsets import catalog_patchset, copy_verified, file_hash, read_patch
from arcanacart.pipeline import load_rom, pipeline
from feunpack.archives import inspect_zip
from feunpack.gba import header_info, read_rom
from feunpack.ups import patch_file

DEFAULT_INPUTS = {
    "fe7_rom": "private/inputs/roms/fe7-usa-base.zip",
    "fe8_rom": "private/inputs/roms/fe8-usa-base.zip",
    "fe7_mods": "private/inputs/mods/fe7-remastered-patches.zip",
    "fe8_mods": "private/inputs/mods/fe8-sacred-trilogy-patches.zip",
}
DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": "1.0",
    "inputs": DEFAULT_INPUTS,
    "prepared": "private/prepared/fire-emblem",
    "workspace": "workspace/fire-emblem",
    "selection": {
        "fe7": ["fe7-usa-remastered-x-qol-final-paladin-special-20251026t165125"],
        "fe8": ["fe8-usa-sacred-trilogy-2.1.3-full"],
    },
    "allow_unknown_bases": False,
    "scan": True,
    "scan_limits": asdict(ScanLimits()),
    "compare": True,
    "tables": {},
}
Progress = Callable[[str], None]


def local_path(root: Path, relative: str, area: str | None = None) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Las rutas de configuración deben ser relativas, con separador /.")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", relative):
        raise ValueError("La configuración no puede salir de la carpeta del proyecto.")
    if area is not None and (not path.parts or path.parts[0] != area):
        raise ValueError(f"La ruta debe comenzar por {area}/.")
    target = root / path
    for item in (target, *target.parents):
        if item.is_symlink():
            raise ValueError("Ruta de workspace mediante symlink no permitida.")
        if item == root:
            break
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Ruta fuera de la carpeta del proyecto.")
    return target


def validate_config(config: dict, root: Path) -> None:
    if (
        not isinstance(config, dict)
        or set(config) != set(DEFAULT_CONFIG)
        or config["schema_version"] != "1.0"
    ):
        raise ValueError("Configuración de lote inválida; genera una con batch --init.")
    if not isinstance(config["inputs"], dict) or set(config["inputs"]) != set(DEFAULT_INPUTS):
        raise ValueError("Deben definirse las cuatro entradas fe7_rom, fe8_rom, fe7_mods, fe8_mods.")
    inputs = [local_path(root, path, "private") for path in config["inputs"].values()]
    if len(set(inputs)) != 4:
        raise ValueError("Las cuatro entradas deben tener rutas distintas.")
    local_path(root, config["prepared"], "private")
    local_path(root, config["workspace"], "workspace")
    for key in ["allow_unknown_bases", "scan", "compare"]:
        if type(config[key]) is not bool:
            raise ValueError(f"{key} debe ser true o false.")
    if not isinstance(config["selection"], dict) or set(config["selection"]) != {"fe7", "fe8"}:
        raise ValueError("Selección de juegos incompleta.")
    for values in config["selection"].values():
        if not isinstance(values, list) or len(values) > 4096 or len(values) != len(set(map(str, values))):
            raise ValueError("Lista de variantes inválida o duplicada.")
        if any(not isinstance(v, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", v) for v in values):
            raise ValueError("Los IDs seleccionados deben copiarse del catálogo generado.")
    if not isinstance(config["scan_limits"], dict) or set(config["scan_limits"]) != set(asdict(ScanLimits())):
        raise ValueError("Límites de escaneo inválidos.")
    if any(type(v) is not int for v in config["scan_limits"].values()):
        raise ValueError("Los límites deben ser enteros.")
    ScanLimits(**config["scan_limits"])
    if not isinstance(config["tables"], dict) or len(config["tables"]) > 4098:
        raise ValueError("Mapa de definiciones de tablas inválido.")
    for key, value in config["tables"].items():
        if not isinstance(key, str):
            raise ValueError("Clave de tablas inválida.")
        local_path(root, value, "private")


def init_workspace(root: Path, config_path: Path, *, dry_run: bool = False) -> dict:
    root = root.resolve()
    if not config_path.resolve().is_relative_to(root):
        raise ValueError("El archivo de configuración debe estar dentro del proyecto.")
    check_destination(config_path, force=True)
    config = read_json(config_path) if config_path.exists() else copy.deepcopy(DEFAULT_CONFIG)
    validate_config(config, root)
    if not dry_run:
        directories = [local_path(root, config["prepared"]), local_path(root, config["workspace"])]
        directories += [local_path(root, name).parent for name in config["inputs"].values()]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not config_path.exists():
            atomic_json(config_path, config)
    return {
        "status": "planned" if dry_run else "completed",
        "config": str(config_path),
        "input_names": config["inputs"],
        "default_selection": config["selection"],
        "dry_run": dry_run,
    }


def import_inputs(root: Path, sources: dict[str, Path], *, dry_run: bool = False) -> dict:
    root = root.resolve()
    if not sources or set(sources) - DEFAULT_INPUTS.keys():
        raise ValueError("Indica al menos una entrada conocida para importar.")
    plan: list[dict[str, Any]] = []
    # Preflight every source before publishing any canonical copy.
    for role, source in sources.items():
        target = local_path(root, DEFAULT_INPUTS[role], "private")
        if source.suffix.lower() != ".zip":
            raise ValueError("Importa los ZIP originales; no los TXT code2text.")
        if role.endswith("_rom"):
            info = inspect_zip(source)
            expected = role[:3] + "-us"
            if (info.get("reference") or {}).get("profile") != expected:
                raise ValueError(f"{role}: SHA-1 no coincide con la base USA esperada.")
            fingerprint = file_hash(source)
        else:
            catalog = catalog_patchset(source, role[:3])
            fingerprint = catalog["archive_sha256"]
        if source.resolve() == target.resolve():
            # Already canonical; validation above still runs.
            cached = True
        elif target.exists():
            if file_hash(source) != file_hash(target):
                raise ValueError(f"{target.name} ya existe con otro contenido; no se reemplaza.")
            cached = True
        else:
            cached = False
        plan.append(
            {
                "role": role,
                "source_name": source.name,
                "destination": DEFAULT_INPUTS[role],
                "content_sha256": fingerprint,
                "already_present": cached,
            }
        )
    if not dry_run:
        folder = root / "private/inputs"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with workspace_lock(folder):
            for record in plan:
                source = sources[record["role"]]
                target = local_path(root, record["destination"], "private")
                if source.resolve() != target.resolve():
                    copy_verified(source, target)
            # Preserve each import event instead of replacing a history file.
            event_id = digest(json_bytes(plan))[:16]
            event = folder / "imports" / (event_id + ".json")
            if not event.exists():
                atomic_json(event, {"format": "arcanacart-import-1", "entries": plan})
    return {"status": "planned" if dry_run else "completed", "dry_run": dry_run, "entries": plan}


def select_variants(catalog: dict, values: list[str], all_variants: bool = False) -> list[dict]:
    if all_variants:
        return list(catalog["entries"])
    by_id = {entry["id"]: entry for entry in catalog["entries"]}
    missing = set(values) - by_id.keys()
    if missing:
        raise ValueError(
            "Variante no encontrada: "
            + ", ".join(sorted(missing))
            + ". Revisa catalog.json y edita selection en la configuración."
        )
    return [by_id[value] for value in values]


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _save_verified(path: Path, data: bytes) -> None:
    if path.exists():
        check_destination(path, force=True)
        if file_hash(path) != digest(data):
            raise ValueError(f"Salida existente con contenido diferente: {path.name}.")
    else:
        atomic_write(path, data)


def _tables(root: Path, config: dict, key: str) -> dict | None:
    relative = config["tables"].get(key)
    return read_json(local_path(root, relative, "private")) if relative else None


def _analysis_path(
    root: Path, config: dict, game: str, identity: str, rom_hash: str, tables: dict | None
) -> Path:
    options = [__version__, rom_hash, config["scan"], config["scan_limits"], tables]
    namespace = digest(json_bytes(options))[:12]
    return local_path(root, config["workspace"], "workspace") / game / (identity + "--" + namespace)


def _reused_patch(
    out: Path, base_hash: str, patch_hash: str, target_crc: str, target_size: int
) -> dict | None:
    if not out.exists():
        return None
    check_destination(out, force=True)
    sidecar = out.with_name(out.name + ".patch.json")
    check_destination(sidecar, force=True)
    if not sidecar.is_file():
        raise ValueError("ROM modificada existente sin manifiesto de parche; no se sobrescribe.")
    meta = read_json(sidecar)
    info = header_info(read_rom(out))
    if (
        not isinstance(meta, dict)
        or meta.get("base_sha256") != base_hash
        or meta.get("patch_sha256") != patch_hash
        or meta.get("target_sha256") != info["sha256"]
        or info["crc32"] != target_crc
        or info["size_bytes"] != target_size
    ):
        raise ValueError("ROM modificada o manifiesto no coinciden con este trabajo. Usa una salida nueva.")
    return meta


def _render_index(result: dict) -> str:
    rows = []
    for job in result["jobs"]:
        report = job.get("report")
        link = '<a href="' + html.escape(report, quote=True) + '">Informe</a>' if report else ""
        rows.append(
            "<tr><td>"
            + html.escape(job["id"])
            + "</td><td>"
            + html.escape(job["status"])
            + "</td><td>"
            + link
            + "</td><td>"
            + html.escape(job.get("error", ""))
            + "</td></tr>"
        )
    return (
        '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>ArcanaCart — Fire Emblem</title><style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem;background:#f4f7fb;color:#172b3a}"
        "table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;border-bottom:1px solid #ccc;padding:.6rem;overflow-wrap:anywhere}"
        "a{color:#075cb4}code{overflow-wrap:anywhere}</style><h1>ArcanaCart — Fire Emblem</h1><p>Estado: <strong>"
        + html.escape(result["status"])
        + "</strong>. Cada mod parte de su ROM base; CRC verificado. Los informes distinguen límites y campos pendientes.</p>"
        "<p>completed describe el flujo ejecutado; no significa extracción completa de personajes, mapas o eventos.</p>"
        '<p><a href="catalog.json">Catálogo de versiones</a> · <a href="batch-report.json">Registro JSON</a></p>'
        "<table><thead><tr><th>Trabajo</th><th>Estado</th><th>Resultado</th><th>Diagnóstico</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></html>"
    )


def run_batch(
    root: Path,
    config_path: Path,
    *,
    game: str = "all",
    all_variants: bool = False,
    dry_run: bool = False,
    catalog_only: bool = False,
    resume: bool = False,
    no_scan: bool = False,
    progress: Progress | None = None,
) -> dict:
    root = root.resolve()
    if game not in {"all", "fe7", "fe8"}:
        raise ValueError("Juego desconocido; usa all, fe7 o fe8.")
    config = copy.deepcopy(DEFAULT_CONFIG) if dry_run and not config_path.exists() else read_json(config_path)
    validate_config(config, root)
    if no_scan:
        config = {**config, "scan": False}
    workspace = local_path(root, config["workspace"], "workspace")
    result: dict[str, Any] = {
        "format": "arcanacart-batch-1",
        "tool_version": __version__,
        "status": "planned" if dry_run else "running",
        "dry_run": dry_run,
        "config_sha256": digest(json_bytes(config)),
        "jobs": [],
        "catalogs": [],
        "limits": {"scan": config["scan_limits"], "patchset_max_bytes": 2 * 1024**3},
        "limitations": [
            "Ghidra no se ejecuta en este lote.",
            "Extracción semántica requiere tables por variante.",
        ],
    }

    def notify(message: str) -> None:
        if progress:
            progress(message)

    def save() -> None:
        if dry_run:
            return
        atomic_json(
            workspace / "catalog.json",
            {"format": "arcanacart-catalogs-1", "catalogs": result["catalogs"]},
            force=True,
        )
        atomic_json(workspace / "batch-report.json", result, force=True)
        atomic_write(workspace / "index.html", _render_index(result).encode("utf-8"), force=True)

    def analyze_job(game_id: str, identity: str, source: Path, rom_hash: str) -> dict:
        tables = _tables(root, config, identity)
        dest = _analysis_path(root, config, game_id, identity, rom_hash, tables)
        notify(identity + ": analizando ROM e informes…")
        state = pipeline(
            source,
            dest,
            profile=game_id + "-us" if tables is not None else "auto",
            tables=tables,
            limits=ScanLimits(**config["scan_limits"]),
            scan=config["scan"],
            resume=resume,
        )
        return {
            "status": state["status"],
            "report": _relative(dest / "report.html", workspace),
            "air": _relative(dest / "air.json", workspace),
            "cache_hit": state["cache_hit"],
            "resource_count": state["resource_count"],
            "entity_count": state["entity_count"],
            "scan_truncated": state["scan_truncated"],
            "warnings": state["warnings"],
        }

    def execute() -> None:
        for game_id in ["fe7", "fe8"] if game == "all" else [game]:
            base_job: dict[str, Any] = {
                "id": game_id + "-base",
                "game": game_id,
                "kind": "base",
                "status": "running",
            }
            if not catalog_only:
                result["jobs"].append(base_job)
                try:
                    notify(game_id + ": verificando y preparando base USA…")
                    source = local_path(root, config["inputs"][game_id + "_rom"], "private")
                    base_data, info = load_rom(source)
                    if not info["gba_fixed_0x96"] or not info["header_checksum_valid"]:
                        raise ValueError("Cabecera base inválida.")
                    if (info.get("reference") or {}).get("profile") != game_id + "-us" and not config[
                        "allow_unknown_bases"
                    ]:
                        raise ValueError("La base no coincide con el SHA-1 USA esperado.")
                    expected_code = "AE7E" if game_id == "fe7" else "BE8E"
                    if info["game_code"] != expected_code:
                        raise ValueError("La cabecera corresponde a otro juego; revisa la entrada.")
                    prepared = (
                        local_path(root, config["prepared"], "private")
                        / game_id
                        / "bases"
                        / info["sha256"][:12]
                        / (game_id + "-usa-base.gba")
                    )
                    base_job.update(
                        rom_sha256=info["sha256"],
                        verification=info["verification"],
                        prepared=_relative(prepared, root),
                    )
                    if dry_run:
                        base_job["status"] = "planned"
                    else:
                        _save_verified(prepared, base_data)
                        base_job.update(analyze_job(game_id, game_id + "-base", prepared, info["sha256"]))
                    save()
                except (OSError, ValueError, BadZipFile, NotImplementedError) as exc:
                    base_job.update(status="failed", error=str(exc))
                    notify(game_id + ": base fallida; " + str(exc))
                    save()
            package_job: dict[str, Any] = {
                "id": game_id + "-mod-package",
                "game": game_id,
                "kind": "catalog",
                "status": "running",
            }
            try:
                notify(game_id + ": catalogando ZIP de mods…")
                pack = local_path(root, config["inputs"][game_id + "_mods"], "private")
                catalog = catalog_patchset(pack, game_id)
                result["catalogs"].append(catalog)
                if catalog_only:
                    result["jobs"].append(
                        {
                            **package_job,
                            "status": "planned" if dry_run else "completed",
                            "variants": catalog["count"],
                        }
                    )
                    save()
                    continue
                selected = select_variants(catalog, config["selection"][game_id], all_variants)
            except (OSError, ValueError, BadZipFile, NotImplementedError) as exc:
                result["jobs"].append({**package_job, "status": "failed", "error": str(exc)})
                save()
                continue
            for record in selected:
                job: dict[str, Any] = {
                    "id": record["id"],
                    "game": game_id,
                    "kind": "mod",
                    "member": record["member"],
                    "status": "running",
                }
                result["jobs"].append(job)
                if base_job["status"] not in {"completed", "partial", "planned"}:
                    job.update(status="blocked", error="No hay una ROM base válida para este juego.")
                    save()
                    continue
                try:
                    notify(record["id"] + ": verificando UPS y CRC de base…")
                    patch, metadata = read_patch(pack, catalog, record)
                    patch_hash = digest(patch)
                    if metadata["source_size"] != len(base_data) or metadata["source_crc32"] != info["crc32"]:
                        raise ValueError(
                            "El UPS requiere otra base: origen CRC32="
                            + metadata["source_crc32"]
                            + "; base actual="
                            + info["crc32"]
                            + ". No se encadenan parches automáticamente."
                        )
                    job.update(
                        patch_sha256=patch_hash,
                        source_crc32=metadata["source_crc32"],
                        target_crc32=metadata["target_crc32"],
                        target_size=metadata["target_size"],
                    )
                    if dry_run:
                        job.update(
                            status="planned", validation="patch-crc-and-base-crc; output-not-yet-applied"
                        )
                        continue
                    directory = local_path(root, config["prepared"], "private") / game_id
                    patch_path = directory / "patches" / (record["id"] + "--" + patch_hash[:12] + ".ups")
                    _save_verified(patch_path, patch)
                    output = directory / "roms" / (record["id"] + "--" + patch_hash[:12] + ".gba")
                    reused = _reused_patch(
                        output, info["sha256"], patch_hash, metadata["target_crc32"], metadata["target_size"]
                    )
                    if reused is not None and not resume:
                        raise ValueError("Esta variante ya está preparada; utiliza --resume.")
                    patch_result = reused or patch_file(prepared, patch_path, output, direction="forward")
                    job.update(
                        prepared=_relative(output, root),
                        patch_reused=reused is not None,
                        rom_sha256=patch_result["target_sha256"],
                    )
                    job.update(analyze_job(game_id, record["id"], output, patch_result["target_sha256"]))
                    if config["compare"]:
                        destination = workspace / Path(job["report"]).parent
                        changed = binary_compare(base_data, read_rom(output))
                        atomic_json(destination / "binary-diff.json", changed, force=resume)
                        job["binary_diff"] = _relative(destination / "binary-diff.json", workspace)
                        job["changed_bytes"] = changed["changed_bytes"]
                        if (
                            _tables(root, config, game_id + "-base") is not None
                            and _tables(root, config, record["id"]) is not None
                        ):
                            base_air = workspace / Path(base_job["air"])
                            diff = semantic_compare(read_json(base_air), read_json(workspace / job["air"]))
                            atomic_json(destination / "semantic-diff.json", diff, force=resume)
                            job["semantic_diff"] = _relative(destination / "semantic-diff.json", workspace)
                except (OSError, ValueError, BadZipFile, NotImplementedError) as exc:
                    job.update(status="failed", error=str(exc))
                    notify(record["id"] + ": falló; " + str(exc))
                save()

    def finalize() -> None:
        failures = sum(j["status"] in {"failed", "blocked", "partial"} for j in result["jobs"])
        result.update(
            status="partial" if failures else "planned" if dry_run else "completed",
            failed_or_partial_jobs=failures,
            job_count=len(result["jobs"]),
        )
        save()

    if dry_run:
        execute()
        finalize()
    else:
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        with workspace_lock(workspace):
            marker = workspace / "batch-report.json"
            check_destination(marker, force=True)
            if marker.exists():
                previous = read_json(marker)
                if not isinstance(previous, dict) or previous.get("format") != "arcanacart-batch-1":
                    raise ValueError("La carpeta contiene un informe ajeno; usa otro workspace.")
            elif (workspace / "index.html").exists() or (workspace / "catalog.json").exists():
                raise ValueError(
                    "La carpeta contiene salidas ajenas sin registro ArcanaCart; no se sobrescriben."
                )
            execute()
            finalize()
    return result
