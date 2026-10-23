"""Repair only the oversized tile previews in an existing interpretation bundle."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import uuid4

from arcanacart import __version__
from arcanacart.core.io import (
    atomic_json,
    atomic_write,
    check_destination,
    digest,
    json_bytes,
    read_bounded,
    read_json,
    workspace_lock,
)
from arcanacart.interpret import (
    BlobReader,
    bundle_payloads,
    check_recipes,
    png_count,
    preview_plan,
    save_preview,
)
from arcanacart.resource_compare import _checked, _hash
from arcanacart.schemas import validate

METADATA = (
    "catalog.json",
    "summary.json",
    "recipes.json",
    "catalog.csv",
    "index.html",
    "report.md",
    "interpret-state.json",
)
LIMIT_ERROR = "La imagen supera el límite de 1048576 píxeles."
READ_LIMIT = 128 * 1024 * 1024
JOURNAL = "preview-repair.json"


def _safe_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("La reparación no admite rutas mediante enlaces simbólicos.")


def _rollback(review: Path, journal: dict) -> None:
    """Restore an interrupted transaction only if every live file is still ours."""
    if (
        journal.get("format") != "arcanacart-preview-repair-1"
        or not isinstance(journal.get("transaction"), str)
        or re.fullmatch(r"repairs/[0-9a-f]{32}", journal["transaction"]) is None
        or not isinstance(journal.get("before"), dict)
        or not isinstance(journal.get("after"), dict)
        or not isinstance(journal.get("created"), dict)
        or set(journal["before"]) != set(METADATA)
        or set(journal["after"]) != set(METADATA)
    ):
        raise ValueError("Diario de reparación inválido; se conservan todos los archivos.")
    for name, hash_ in journal["created"].items():
        if re.fullmatch(r"png/[0-9a-f]{64}-p[0-9]{4}\.png", name) is None or not _hash(hash_):
            raise ValueError("Página o hash inválido en el diario de reparación.")
    before = {}
    for name in METADATA:
        old_hash, new_hash = journal["before"][name], journal["after"][name]
        if not _hash(old_hash) or not _hash(new_hash):
            raise ValueError("Hash de metadatos inválido en el diario de reparación.")
        backup = review / journal["transaction"] / "before" / name
        _safe_path(backup)
        content = read_bounded(backup, READ_LIMIT)
        if digest(content) != old_hash:
            raise ValueError("El respaldo de reparación cambió; se conserva el estado actual.")
        before[name] = content
        target = review / name
        _safe_path(target)
        if target.exists() and digest(read_bounded(target, READ_LIMIT)) not in {old_hash, new_hash}:
            raise ValueError("Un archivo cambió después de la reparación; no se revierte automáticamente.")
    for name, hash_ in journal["created"].items():
        path = review / name
        _safe_path(path)
        if path.exists() and digest(read_bounded(path, READ_LIMIT)) != hash_:
            raise ValueError("Una página nueva cambió; no se revierte automáticamente.")
    for name, content in before.items():
        atomic_write(review / name, content, force=True)
    for name in journal["created"]:
        (review / name).unlink(missing_ok=True)
    atomic_json(review / JOURNAL, {**journal, "status": "rolled-back"}, force=True)


def _load_bundle(source: Path, review: Path) -> tuple[dict, list[dict], dict, dict[str, bytes]]:
    before = {name: read_bounded(review / name, READ_LIMIT) for name in METADATA}
    state = read_json(review / "interpret-state.json", READ_LIMIT)
    if not isinstance(state, dict) or not isinstance(state.get("artifacts"), dict):
        raise ValueError("Falta el inventario de integridad de la interpretación original.")
    for name in METADATA[:-1]:
        if digest(before[name]) != state["artifacts"].get(name):
            raise ValueError(f"{name} cambió desde la interpretación; se conserva sin reparar.")
    summary = read_json(review / "summary.json", READ_LIMIT)
    catalog = read_json(review / "catalog.json", READ_LIMIT)
    template = read_json(review / "recipes.json", READ_LIMIT)
    document = read_json(source, 64 * 1024 * 1024)
    records, _, _ = _checked(document)
    if "schema_version" in document:
        validate(document)
    if (
        not isinstance(summary, dict)
        or summary.get("format") != "arcanacart-interpretation-1"
        or summary.get("status") not in {"completed", "partial"}
        or state.get("status") != summary["status"]
        or summary.get("rom_sha256") != document["rom"]["sha256"]
        or summary.get("candidate_inventory_sha256") != digest(json_bytes(records))
        or summary.get("source_manifest_sha256") != digest(read_bounded(source, 64 * 1024 * 1024))
        or not isinstance(catalog, dict)
        or catalog.get("summary") != summary
        or not isinstance(catalog.get("resources"), list)
    ):
        raise ValueError("El catálogo, el estado y el AIR no corresponden al mismo análisis.")
    rows = catalog["resources"]
    sizes = {r["sha256"]: r["decompressed_bytes"] for r in records}
    palette_hashes = {p["sha256"] for p in summary.get("external_palettes", [])}
    recipes = check_recipes(template, document["rom"]["sha256"], set(sizes), palette_hashes)
    if len(rows) != len(sizes) or set(recipes) != set(sizes):
        raise ValueError("El catálogo o las recetas no cubren el inventario original.")
    seen = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("sha256"), str)
            or row["sha256"] not in sizes
            or row["sha256"] in seen
            or row.get("size_bytes") != sizes[row["sha256"]]
            or row.get("recipe") != recipes[row["sha256"]]
            or row.get("preview_status")
            not in {"generated", "not-requested", "error", "limit-skipped", "pixel-budget-skipped"}
            or row.get("blob_status") not in {"verified", "error", "unread"}
        ):
            raise ValueError("Fila del catálogo incompatible con el inventario y las recetas.")
        seen.add(row["sha256"])
    for key in ("bytes_read", "rendered_pixels", "generated_previews"):
        if type(summary.get(key)) is not int or summary[key] < 0:
            raise ValueError("Contadores originales inválidos.")
    return summary, rows, state, before


def _eligible(row: dict) -> bool:
    return (
        row["preview_status"] == "error"
        and row.get("preview_error") == LIMIT_ERROR
        and row["blob_status"] == "verified"
        and row["recipe"]["mode"] == "tiles"
        and row["recipe"]["review"] != "rejected"
        and len(preview_plan(row["size_bytes"], row["recipe"])) > 1
    )


def _updated_summary(summary: dict, rows: list[dict], repair: dict) -> dict:
    accepted = sum(
        r["recipe"]["review"] == "accepted"
        and r["blob_status"] == "verified"
        and r["preview_status"] != "error"
        for r in rows
    )
    rejected = sum(r["recipe"]["review"] == "rejected" for r in rows)
    errors = sum(r["blob_status"] == "error" or r["preview_status"] == "error" for r in rows)
    skipped = sum(r["preview_status"] in {"limit-skipped", "pixel-budget-skipped"} for r in rows)
    partial = (
        errors
        or skipped
        or summary["source_scan"]["truncated"]
        or (summary.get("comparison") or {}).get("status") == "partial"
    )
    return {
        **summary,
        "tool_version": __version__,
        "status": "partial" if partial else "completed",
        "verified_blobs": sum(r["blob_status"] == "verified" for r in rows),
        "identified_by_user_review": accepted,
        "rejected_by_user": rejected,
        "pending_interpretation": len(rows) - accepted - rejected,
        "generated_previews": sum(r["preview_status"] == "generated" for r in rows),
        "generated_png_files": sum(png_count(r) for r in rows),
        "skipped_previews": skipped,
        "errors": errors,
        "bytes_read": summary["bytes_read"] + repair["bytes_read"],
        "rendered_pixels": summary["rendered_pixels"] + repair["rendered_pixels"],
        "repair": repair,
        "rescanned": False,
    }


def repair_previews(
    source: Path,
    review: Path,
    *,
    resources: Path | None = None,
    max_previews: int = 20_000,
    byte_budget: int = 512 * 1024 * 1024,
    pixel_budget: int = 512 * 1024 * 1024,
    dry_run: bool = False,
) -> dict:
    """Budgets cover new work only; successful previews and manual recipes stay intact."""
    if (
        not 0 <= max_previews <= 100_000
        or not 1 <= byte_budget <= 8 * 1024**3
        or not 1 <= pixel_budget <= 1024**3
    ):
        raise ValueError("Límites de reparación inválidos.")
    root = resources or (source.parent / "resources")
    for path in (source, review, root, *(review / name for name in (*METADATA, JOURNAL))):
        _safe_path(path)
    if not review.is_dir() or not root.is_dir():
        raise ValueError("La reparación requiere la galería existente y sus bloques originales.")
    if review.resolve().is_relative_to(root.resolve()) or source.resolve().is_relative_to(review.resolve()):
        raise ValueError("La galería debe estar separada del AIR y de sus bloques.")
    with workspace_lock(review):
        if (review / JOURNAL).exists():
            previous = read_json(review / JOURNAL, READ_LIMIT)
            if not isinstance(previous, dict):
                raise ValueError("Diario de reparación inválido.")
            if previous.get("status") == "committing":
                if dry_run:
                    raise ValueError(
                        "Hay una reparación interrumpida; ejecuta sin --dry-run para recuperarla."
                    )
                _rollback(review, previous)
        summary, rows, state, before = _load_bundle(source, review)
        eligible = [row for row in rows if _eligible(row)]
        repair = {
            "eligible_blobs": len(eligible),
            "attempted_blobs": 0,
            "repaired_blobs": 0,
            "new_png_files": 0,
            "bytes_read": 0,
            "rendered_pixels": 0,
            "deferred_blobs": 0,
            "retained_previews": summary["generated_previews"],
            "verification_scope": "SHA-256 de AIR, metadatos y bloques reparados; PNG anteriores conservados sin releer.",
        }
        result = {**summary, "output": str(review), "gallery": str(review / "index.html"), "repair": repair}
        if dry_run:
            plans = [preview_plan(r["size_bytes"], r["recipe"]) for r in eligible]
            return {
                **result,
                "status": "planned",
                "planned_png_files": sum(len(plan) for plan in plans),
                "planned_pixels": sum(p["width"] * p["height"] for plan in plans for p in plan),
                "planned_blob_bytes": sum(r["size_bytes"] for r in eligible),
            }
        if not eligible:
            return result
        transaction = "repairs/" + uuid4().hex
        repair["backup"] = str(review / transaction / "before")
        staged = review / transaction / "after"
        sizes = {r["sha256"]: r["size_bytes"] for r in rows}
        external = {}
        for item in summary.get("external_palettes", []):
            if not _hash(item.get("sha256")) or type(item.get("size_bytes")) is not int:
                raise ValueError("Referencia de paleta externa inválida.")
            hash_ = item["sha256"]
            sizes[hash_] = item["size_bytes"]
            external[hash_] = review / "palettes" / (hash_ + ".bin")
            _safe_path(external[hash_])
        reader = BlobReader(root, sizes, byte_budget, external)
        for number, row in enumerate(eligible, 1):
            logging.info("Reparando bloque %d/%d: %s", number, len(eligible), row["sha256"][:16])
            plan = preview_plan(row["size_bytes"], row["recipe"])
            pixels = sum(p["width"] * p["height"] for p in plan)
            if (
                repair["new_png_files"] + len(plan) > max_previews
                or repair["rendered_pixels"] + pixels > pixel_budget
            ):
                row["repair_error"] = (
                    "Presupuesto de PNG o píxeles insuficiente para todas las páginas del bloque."
                )
                repair["deferred_blobs"] += 1
                continue
            repair["attempted_blobs"] += 1
            try:
                raw = reader.read(row["sha256"])
                pages = save_preview(row, raw, reader, staged)
                repair["repaired_blobs"] += 1
                repair["new_png_files"] += len(pages)
                repair["rendered_pixels"] += pixels
            except (OSError, ValueError) as exc:
                row["repair_error"] = str(exc)
        repair["bytes_read"] = reader.used
        updated = _updated_summary(summary, rows, repair)
        template = {
            "format": "arcanacart-recipes-1",
            "rom_sha256": summary["rom_sha256"],
            "resources": {r["sha256"]: r["recipe"] for r in rows},
        }
        after = bundle_payloads(updated, rows, template)
        created = {}
        for row in eligible:
            if row["preview_status"] == "generated":
                for page in row["pages"]:
                    name = page["png"]
                    check_destination(review / name)
                    created[name] = digest(read_bounded(staged / name, READ_LIMIT))
        artifacts = {**state["artifacts"], **created, **{n: digest(b) for n, b in after.items()}}
        after["interpret-state.json"] = json_bytes({"status": updated["status"], "artifacts": artifacts})
        for name, content in before.items():
            atomic_write(review / transaction / "before" / name, content)
        for name, content in after.items():
            atomic_write(staged / name, content)
        for name, content in before.items():
            if read_bounded(review / name, READ_LIMIT) != content:
                raise ValueError(
                    "Los metadatos cambiaron durante la reparación; no se publica la actualización."
                )
        if digest(read_bounded(source, 64 * 1024 * 1024)) != summary["source_manifest_sha256"]:
            raise ValueError("El AIR cambió durante la reparación; no se publica la actualización.")
        journal = {
            "format": "arcanacart-preview-repair-1",
            "status": "committing",
            "transaction": transaction,
            "before": {n: digest(b) for n, b in before.items()},
            "after": {n: digest(b) for n, b in after.items()},
            "created": created,
        }
        atomic_json(review / JOURNAL, journal, force=True)
        try:
            for name in created:
                atomic_write(review / name, read_bounded(staged / name, READ_LIMIT))
            for name in METADATA:
                atomic_write(review / name, after[name], force=True)
            atomic_json(review / JOURNAL, {**journal, "status": "completed"}, force=True)
        except BaseException:
            _rollback(review, journal)
            raise
        return {**updated, "output": str(review), "gallery": str(review / "index.html")}
