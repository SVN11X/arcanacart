"""Interpret existing decoded blobs without rescanning or modifying their AIR."""

from __future__ import annotations

import csv
import io
import math
import struct
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from arcanacart import __version__, graphics
from arcanacart.core.io import (
    atomic_json,
    atomic_write,
    digest,
    json_bytes,
    read_bounded,
    read_json,
    workspace_lock,
)
from arcanacart.resource_compare import _checked, compare_resources
from arcanacart.schemas import validate

MODES = {"unknown", "data", "tiles", "palette", "bg-map", "fe-map"}
RECIPE_KEYS = {
    "mode",
    "bpp",
    "width_tiles",
    "height_tiles",
    "palette_sha256",
    "palette_offset",
    "tiles_sha256",
    "transparent_zero",
    "map_layout",
    "review",
    "evidence",
    "note",
}


def inspect_blob(raw: bytes) -> dict:
    """Every hypothesis is intentionally non-exclusive and unconfirmed."""
    if not raw:
        raise ValueError("Bloque vacío.")
    counts = Counter(raw)
    hypotheses = []
    size = len(raw)
    if size % 32 == 0:
        hypotheses.append("tiles4")
    if size % 64 == 0:
        hypotheses.append("tiles8")
    if size in (32, 64, 128, 256, 512, 1024):
        words = [v[0] for v in struct.iter_unpack("<H", raw)]
        if all(value < 0x8000 for value in words):
            hypotheses.append("rgb555-palette")
    if size in (2048, 4096, 8192):
        hypotheses.append("text-bg-map-u16")
    if size >= 4 and raw[0] and raw[1] and size == 2 + raw[0] * raw[1] * 2:
        hypotheses.append("fe-map-dimensions-u16")
    return {
        "hypotheses": hypotheses,
        "uniform_byte": raw[0] if len(counts) == 1 else None,
        "distinct_bytes": len(counts),
        "entropy_bits_per_byte": round(-sum((n / size) * math.log2(n / size) for n in counts.values()), 5),
        "validation": "inferred",
        "limitations": "Longitud y distribución compatibles; no prueban tipo ni uso. Un bloque uniforme puede ser válido.",
    }


def default_recipe(raw: bytes) -> dict:
    hints = inspect_blob(raw)
    mode = "unknown"
    if hints["uniform_byte"] is None:
        if "rgb555-palette" in hints["hypotheses"]:
            mode = "palette"
        elif "tiles4" in hints["hypotheses"]:
            mode = "tiles"
    return {
        "mode": mode,
        "bpp": 4,
        "width_tiles": 16,
        "height_tiles": 32,
        "palette_sha256": None,
        "palette_offset": 0,
        "tiles_sha256": None,
        "transparent_zero": False,
        "map_layout": "linear",
        "review": "unreviewed",
        "evidence": [],
        "note": "",
    }


def check_recipes(
    config: dict | None, rom_hash: str, hashes: set[str], palette_hashes: set[str] | None = None
) -> dict:
    if config is None:
        return {}
    if (
        not isinstance(config, dict)
        or set(config) != {"format", "rom_sha256", "resources"}
        or config["format"] != "arcanacart-recipes-1"
        or config["rom_sha256"] != rom_hash
        or not isinstance(config["resources"], dict)
    ):
        raise ValueError("Las recetas deben estar ligadas al SHA-256 de esta ROM (arcanacart-recipes-1).")
    for hash_, recipe in config["resources"].items():
        if hash_ not in hashes or not isinstance(recipe, dict) or set(recipe) - RECIPE_KEYS:
            raise ValueError("Receta desconocida, bloque ausente o campos de receta inválidos.")
        if (
            not isinstance(recipe.get("mode", "unknown"), str)
            or not isinstance(recipe.get("review", "unreviewed"), str)
            or recipe.get("mode", "unknown") not in MODES
            or recipe.get("review", "unreviewed") not in {"unreviewed", "accepted", "rejected"}
        ):
            raise ValueError("Interpretación o estado de revisión inválido.")
        for field, low, high in (
            ("bpp", 4, 8),
            ("width_tiles", 1, 128),
            ("height_tiles", 1, 128),
            ("palette_offset", 0, 511),
        ):
            value = recipe.get(field, low)
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Valor de receta fuera de rango: " + field)
        if recipe.get("bpp", 4) not in (4, 8):
            raise ValueError("bpp debe ser 4 u 8.")
        for field in ("palette_sha256", "tiles_sha256"):
            available = hashes | (palette_hashes or set()) if field == "palette_sha256" else hashes
            if recipe.get(field) is not None and (
                not isinstance(recipe[field], str) or recipe[field] not in available
            ):
                raise ValueError("La paleta o tileset debe pertenecer al mismo manifiesto.")
        if (
            type(recipe.get("transparent_zero", False)) is not bool
            or not isinstance(recipe.get("map_layout", "linear"), str)
            or recipe.get("map_layout", "linear") not in {"linear", "screenblocks"}
        ):
            raise ValueError("Transparencia o distribución de mapa inválida.")
        evidence = recipe.get("evidence", [])
        if (
            not isinstance(recipe.get("note", ""), str)
            or len(recipe.get("note", "")) > 2000
            or not isinstance(evidence, list)
            or len(evidence) > 32
            or any(not isinstance(x, str) or not x.strip() or len(x) > 2000 for x in evidence)
        ):
            raise ValueError("Evidencia o nota de receta inválida.")
        if recipe.get("review") == "accepted" and (
            not evidence or recipe.get("mode", "unknown") == "unknown"
        ):
            raise ValueError("Aceptar una interpretación requiere modo y evidencia explícita.")
    return config["resources"]


class BlobReader:
    def __init__(
        self, root: Path, sizes: dict[str, int], byte_budget: int, external: dict[str, Path] | None = None
    ):
        self.root, self.sizes, self.budget, self.used = root, sizes, byte_budget, 0
        self.external = external or {}

    def read(self, hash_: str) -> bytes:
        size = self.sizes[hash_]
        if size > 2_097_152:
            raise ValueError("Bloque superior al límite de lectura de 2 MiB.")
        if self.used + size > self.budget:
            raise ValueError("Presupuesto de lectura agotado; aumenta --byte-budget.")
        path = self.external.get(hash_, self.root / (hash_ + ".bin"))
        if path.is_symlink():
            raise ValueError("El bloque no puede ser un enlace simbólico.")
        self.used += size
        raw = read_bounded(path, size, size)
        if digest(raw) != hash_:
            raise ValueError("El contenido del bloque no coincide con el hash del manifiesto.")
        return raw


def preview_plan(size: int, recipe: dict) -> list[dict]:
    """Calculate PNG count and padded pixels before any rendering allocation."""
    if recipe["review"] == "rejected" or recipe["mode"] in {"unknown", "data", "fe-map"}:
        return []
    if recipe["mode"] == "tiles":
        return graphics.tile_page_plan(size, bpp=recipe["bpp"], width_tiles=recipe["width_tiles"])
    if recipe["mode"] == "palette":
        if not 2 <= size <= 1024 or size % 2:
            raise ValueError("Paleta RGB555 requiere 2..1024 bytes y longitud par.")
        columns = min(16, size // 2)
        return [{"width": columns * 12, "height": ((size // 2 + columns - 1) // columns) * 12}]
    return [{"width": recipe["width_tiles"] * 8, "height": recipe["height_tiles"] * 8}]


def render_pages(raw: bytes, recipe: dict, reader: BlobReader) -> Iterator[tuple[dict, bytes]]:
    mode = recipe["mode"]
    if recipe["review"] == "rejected" or mode in {"unknown", "data", "fe-map"}:
        return
    if mode == "palette":
        width, height, pixels = graphics.swatches(raw)
        yield {"width": width, "height": height}, pixels
        return
    colors = graphics.palette(reader.read(recipe["palette_sha256"])) if recipe["palette_sha256"] else None
    if mode == "bg-map":
        if not recipe["tiles_sha256"]:
            raise ValueError("El mapa requiere tiles_sha256 explícito; no se adivina un tileset.")
        if recipe["palette_offset"]:
            raise ValueError("BG usa los bancos de sus entradas; palette_offset debe ser 0.")
        width, height, pixels = graphics.bg_map(
            raw,
            reader.read(recipe["tiles_sha256"]),
            width_tiles=recipe["width_tiles"],
            height_tiles=recipe["height_tiles"],
            bpp=recipe["bpp"],
            colors=colors,
            transparent_zero=recipe["transparent_zero"],
            layout=recipe["map_layout"],
        )
        yield {"width": width, "height": height}, pixels
        return
    for page in preview_plan(len(raw), recipe):
        start = page["byte_offset"]
        width, height, pixels = graphics.tiles(
            raw[start : start + page["size_bytes"]],
            bpp=recipe["bpp"],
            width_tiles=recipe["width_tiles"],
            colors=colors,
            palette_offset=recipe["palette_offset"],
            transparent_zero=recipe["transparent_zero"],
        )
        assert (width, height) == (page["width"], page["height"])
        yield page, pixels


def save_preview(row: dict, raw: bytes, reader: BlobReader, out: Path) -> list[dict]:
    """Publish a whole resource or remove its newly written pages on failure."""
    plan = preview_plan(len(raw), row["recipe"])
    pages = []
    written = []
    try:
        for number, (page, pixels) in enumerate(render_pages(raw, row["recipe"], reader), 1):
            suffix = f"-p{number:04d}" if len(plan) > 1 else ""
            name = "png/" + row["sha256"] + suffix + ".png"
            atomic_write(out / name, graphics.png(page["width"], page["height"], pixels))
            written.append(out / name)
            pages.append({**page, "png": name})
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    if pages:
        row.update(
            png=pages[0]["png"],
            width=pages[0]["width"],
            height=pages[0]["height"],
            pages=pages,
            preview_status="generated",
            colors="grayscale-placeholder"
            if row["recipe"]["mode"] != "palette" and not row["recipe"]["palette_sha256"]
            else "rgb555",
        )
        row.pop("preview_error", None)
        row.pop("repair_error", None)
    return pages


def png_count(row: dict) -> int:
    if row["preview_status"] != "generated":
        return 0
    return len(row["pages"]) if row.get("pages") else int(bool(row.get("png")))


def bundle_payloads(summary: dict, rows: list[dict], template: dict) -> dict[str, bytes]:
    from arcanacart.gallery import render_gallery

    return {
        "catalog.json": json_bytes({"summary": summary, "resources": rows}),
        "recipes.json": json_bytes(template),
        "summary.json": json_bytes(summary),
        "catalog.csv": _csv(rows),
        "index.html": render_gallery(summary, rows, template).encode("utf-8"),
        "report.md": (
            "# Interpretación de recursos\n\n```json\n" + json_bytes(summary).decode() + "```\n"
        ).encode(),
    }


def _csv(rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "sha256",
            "offsets",
            "bytes",
            "base_match",
            "hypotheses",
            "review",
            "mode",
            "blob_status",
            "preview_status",
            "png",
            "png_count",
            "png_pages",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["sha256"],
                ";".join(str(n) for n in row["offsets"]),
                row["size_bytes"],
                row["base_match"],
                ";".join(row.get("hypotheses", [])),
                row["recipe"]["review"],
                row["recipe"]["mode"],
                row["blob_status"],
                row["preview_status"],
                row.get("png", ""),
                png_count(row),
                ";".join(page["png"] for page in row.get("pages", [])),
            ]
        )
    return stream.getvalue().encode("utf-8-sig")


def interpret(
    source: Path,
    out: Path,
    *,
    resources: Path | None = None,
    recipes: Path | None = None,
    palettes: list[Path] | None = None,
    base: Path | None = None,
    max_previews: int = 500,
    byte_budget: int = 512 * 1024 * 1024,
    pixel_budget: int = 64 * 1024 * 1024,
    dry_run: bool = False,
) -> dict:
    if (
        not 0 <= max_previews <= 100_000
        or not 1 <= byte_budget <= 8 * 1024**3
        or not 1 <= pixel_budget <= 1024**3
    ):
        raise ValueError("Límites de interpretación inválidos.")
    document = read_json(source, 64 * 1024 * 1024)
    records, scan, _ = _checked(document)
    if "schema_version" in document:
        validate(document)
    root = resources or (
        source.parent / "resources" if (source.parent / "resources").is_dir() else source.parent
    )
    for path in (out, *out.parents, root):
        if path.is_symlink():
            raise ValueError("No se permiten directorios mediante symlink.")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(
            "Usa una carpeta de interpretación nueva y vacía; se conservan los resultados anteriores."
        )
    if source.resolve().is_relative_to(out.resolve()) or out.resolve().is_relative_to(root.resolve()):
        raise ValueError("La salida debe estar separada del manifiesto y de los bloques originales.")
    sizes = {r["sha256"]: r["decompressed_bytes"] for r in records}
    if len(palettes or []) > 32:
        raise ValueError("Se admiten hasta 32 paletas externas por trabajo.")
    external, palette_sizes, palette_metadata, palette_bytes = {}, {}, [], {}
    for path in palettes or []:
        raw_palette = read_bounded(path, 1024, 2)
        graphics.palette(raw_palette)
        hash_ = digest(raw_palette)
        external[hash_] = path
        palette_sizes[hash_] = len(raw_palette)
        palette_bytes[hash_] = raw_palette
        palette_metadata.append({"sha256": hash_, "name": path.name, "size_bytes": len(raw_palette)})
    if sum(palette_sizes.values()) > byte_budget:
        raise ValueError("Las paletas externas superan el presupuesto de lectura.")
    overrides = check_recipes(
        read_json(recipes) if recipes else None, document["rom"]["sha256"], set(sizes), set(external)
    )
    comparison = compare_resources(read_json(base, 64 * 1024 * 1024), document) if base else None
    matches = {r["sha256"]: r["coincide_base"] for r in comparison[1]} if comparison else {}
    if dry_run:
        return {
            "status": "planned",
            "unique_blobs": len(sizes),
            "candidates": len(records),
            "rescanned": False,
            "output": str(out),
        }
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(record["sha256"], []).append(record)
    reader = BlobReader(root, {**sizes, **palette_sizes}, byte_budget, external)
    reader.used = sum(palette_sizes.values())
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    with workspace_lock(out):
        atomic_json(out / "interpret-state.json", {"status": "running"})
        try:
            for hash_, raw_palette in palette_bytes.items():
                atomic_write(out / "palettes" / (hash_ + ".bin"), raw_palette)
            rows, generated, generated_png, used_pixels = [], 0, 0, 0
            for hash_, occurrences in grouped.items():
                recipe = {**default_recipe(b"\0"), **overrides.get(hash_, {})}
                row = {
                    "sha256": hash_,
                    "size_bytes": sizes[hash_],
                    "offsets": [r["offset"] for r in occurrences],
                    "reference_count": sum(len(r["references"]) for r in occurrences),
                    "compression": sorted({r["compression"] for r in occurrences}),
                    "base_match": matches.get(hash_),
                    "blob_status": "unread",
                    "preview_status": "not-requested",
                    "recipe": recipe,
                }
                rows.append(row)
                try:
                    raw = reader.read(hash_)
                    row.update(inspect_blob(raw))
                    recipe = {**default_recipe(raw), **overrides.get(hash_, {})}
                    row.update(recipe=recipe, blob_status="verified")
                except (OSError, ValueError) as exc:
                    row.update(blob_status="error", error=str(exc))
                    continue
                if recipe["review"] == "rejected" or recipe["mode"] in {"unknown", "data", "fe-map"}:
                    continue
                try:
                    plan = preview_plan(len(raw), recipe)
                    estimated = sum(p["width"] * p["height"] for p in plan)
                    if generated_png + len(plan) > max_previews:
                        row["preview_status"] = "limit-skipped"
                        continue
                    if used_pixels + estimated > pixel_budget:
                        row["preview_status"] = "pixel-budget-skipped"
                        continue
                    pages = save_preview(row, raw, reader, out)
                    if pages:
                        generated += 1
                        generated_png += len(pages)
                        used_pixels += estimated
                except (OSError, ValueError) as exc:
                    row.update(preview_status="error", preview_error=str(exc))
            accepted = sum(
                r["recipe"]["review"] == "accepted"
                and r["blob_status"] == "verified"
                and r["preview_status"] != "error"
                for r in rows
            )
            rejected = sum(r["recipe"]["review"] == "rejected" for r in rows)
            errors = sum(r["blob_status"] == "error" or r["preview_status"] == "error" for r in rows)
            skipped = sum(r["preview_status"] in {"limit-skipped", "pixel-budget-skipped"} for r in rows)
            summary = {
                "format": "arcanacart-interpretation-1",
                "tool_version": __version__,
                "rom_sha256": document["rom"]["sha256"],
                "candidate_inventory_sha256": digest(json_bytes(records)),
                "source_manifest_sha256": digest(read_bounded(source, 64 * 1024 * 1024)),
                "source_scan": scan,
                "candidates": len(records),
                "unique_blobs": len(rows),
                "verified_blobs": sum(r["blob_status"] == "verified" for r in rows),
                "identified_by_user_review": accepted,
                "rejected_by_user": rejected,
                "pending_interpretation": len(rows) - accepted - rejected,
                "generated_previews": generated,
                "generated_png_files": generated_png,
                "preview_limit_unit": "png-files",
                "skipped_previews": skipped,
                "errors": errors,
                "bytes_read": reader.used,
                "rendered_pixels": used_pixels,
                "rescanned": False,
                "comparison": comparison[0] if comparison else None,
                "external_palettes": palette_metadata,
                "status": "partial"
                if errors
                or skipped
                or scan["truncated"]
                or (comparison and comparison[0]["status"] == "partial")
                else "completed",
                "limitations": [
                    "completed describe el trabajo solicitado; no identifica automáticamente todos los recursos.",
                    "Los PNG muestran una interpretación; no confirman el uso del recurso en el juego.",
                    "Gris es una paleta de diagnóstico; la paleta real debe seleccionarse explícitamente.",
                    "Sin coincidencia en la base no confirma un recurso nuevo. Los mapas FE usan metatiles y no son mapas BG.",
                    "identified_by_user_review cuenta decisiones documentadas del usuario, no confirmación automática.",
                ],
            }
            template = {
                "format": "arcanacart-recipes-1",
                "rom_sha256": document["rom"]["sha256"],
                "resources": {r["sha256"]: r["recipe"] for r in rows},
            }
            for name, content in bundle_payloads(summary, rows, template).items():
                atomic_write(out / name, content)
            artifacts: dict[str, str] = {}
            for path in sorted(out.rglob("*")):
                if path.is_file() and path.name not in {".arcanacart.lock", "interpret-state.json"}:
                    artifacts[path.relative_to(out).as_posix()] = digest(
                        read_bounded(path, 128 * 1024 * 1024)
                    )
            atomic_json(
                out / "interpret-state.json",
                {"status": summary["status"], "artifacts": artifacts},
                force=True,
            )
            return {**summary, "output": str(out), "gallery": str(out / "index.html")}
        except Exception as exc:
            atomic_json(out / "interpret-state.json", {"status": "failed", "error": str(exc)}, force=True)
            raise
