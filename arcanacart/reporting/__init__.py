"""Standalone reports with escaped input, real denominators and stated limits."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from arcanacart.core.io import atomic_write, digest, json_bytes
from arcanacart.exporters import target_compatibility
from arcanacart.schemas import validate


def resource_metrics(document: dict, review: dict | None = None) -> dict:
    hashes = {r["sha256"] for r in document["resources"]}
    result = {
        "scanner_progress_percent": document["scan"].get("search_progress_percent"),
        "candidates": len(document["resources"]),
        "unique_blobs": len(hashes),
        "identified_by_user_review": 0,
        "pending_interpretation": len(hashes),
        "generated_previews": 0,
        "generated_png_files": 0,
        "note": "El avance del escáner, las hipótesis y los recursos identificados son métricas distintas.",
    }
    if review is not None:
        if isinstance(review, dict) and review.get("candidate_inventory_sha256") != digest(
            json_bytes(document["resources"])
        ):
            raise ValueError(
                "El inventario de candidatos cambió; se necesita una interpretación de estos resultados."
            )
        if (
            not isinstance(review, dict)
            or review.get("format") != "arcanacart-interpretation-1"
            or review.get("rom_sha256") != document["rom"]["sha256"]
            or review.get("candidates") != len(document["resources"])
            or review.get("unique_blobs") != len(hashes)
        ):
            raise ValueError("El resumen de interpretación no corresponde a estos resultados y ROM.")
        for key in (
            "identified_by_user_review",
            "pending_interpretation",
            "generated_previews",
            "rejected_by_user",
        ):
            value = review.get(key)
            if type(value) is not int or not 0 <= value <= len(hashes):
                raise ValueError("Métricas de interpretación inválidas.")
            result[key] = value
        png_files = review.get("generated_png_files", result["generated_previews"])
        if type(png_files) is not int or not result["generated_previews"] <= png_files <= 100_000_000:
            raise ValueError("Número de archivos PNG inválido.")
        result["generated_png_files"] = png_files
        if result["identified_by_user_review"] + result["pending_interpretation"] + result[
            "rejected_by_user"
        ] != len(hashes):
            raise ValueError("Los estados de interpretación no suman el total de bloques únicos.")
    return result


def summary(document: dict, review: dict | None = None) -> dict:
    validate(document)
    return {
        "identification": document["rom"],
        "profile": document["profile"],
        "entities_by_type": dict(Counter(e["kind"] for e in document["entities"])),
        "resources": len(document["resources"]),
        "resource_interpretation": resource_metrics(document, review),
        "scan": document["scan"],
        "extractors": document["extractors"],
        "coverage": document["coverage"],
        "stages": document["stages"],
        "errors": document["errors"],
        "warnings": document["warnings"],
        "disassembly": document.get("coverage", {}).get(
            "disassembly",
            {
                "identified_functions": None,
                "exported_functions": None,
                "failed_functions": None,
                "reason": "No se ejecutó Ghidra. No hay denominador para cobertura de funciones.",
            },
        ),
        "compatibility": target_compatibility(document),
    }


def overview(document: dict) -> list[str]:
    """Keep execution, header-search progress and semantic classification distinct."""
    scan = document["scan"]
    status = (
        "parcial"
        if document["errors"]
        or scan.get("truncated")
        or any(s["status"] in {"partial", "failed"} for s in document["stages"])
        else "finalizado"
    )
    lines = [f"Estado de las etapas solicitadas: {status}."]
    if scan:
        methods = scan.get("methods")
        if methods:
            lines.append("Formatos buscados: " + ", ".join(methods) + ".")
            omitted = [name for name in ("lz10", "rle") if name not in methods]
            if omitted:
                lines.append("Formatos fuera de este barrido: " + ", ".join(omitted) + ".")
        else:
            lines.append("Este informe anterior no registra los formatos seleccionados.")
        progress = scan.get("search_progress_percent")
        if progress is None:
            start = scan.get("excluded_header_bytes", 0)
            positions = range(start, max(start, document["rom"]["size_bytes"] - 3), scan.get("step", 1))
            checked = max(0, (scan.get("scanned_through_offset", start) - start) // scan.get("step", 1) + 1)
            progress = min(100.0, 100.0 * checked / len(positions)) if positions else 100.0
        lines.append(
            f"Avance de búsqueda lineal de cabeceras: {progress:.3f} % (paso {scan.get('step', 1)})."
        )
        if scan.get("referenced_header_targets"):
            lines.append(
                "Cabeceras priorizadas por referencias: "
                f"{scan['referenced_header_targets_checked']} de {scan['referenced_header_targets']}. "
                "Se revisan antes del recorrido lineal; las referencias son heurísticas."
            )
        if scan.get("truncated"):
            lines.append(
                "El escaneo se interrumpió; no demuestra ausencia de recursos en el resto de la ROM."
            )
    else:
        lines.append("Búsqueda de recursos: omitida.")
    coverage = document["coverage"]
    classified = coverage.get("classified_bytes", 0)
    total = document["rom"]["size_bytes"]
    percent = 100.0 * classified / total if total else 0.0
    lines.append(f"Bytes clasificados: {classified:,} de {total:,} ({percent:.5f} %).")
    lines.append(
        "Esa cifra une rangos de cabeceras, tablas y candidatos; los candidatos siguen siendo "
        "heurísticos y sus rangos pueden solaparse. No mide comprensión del juego."
    )
    table_stage: dict = next((s for s in document["stages"] if s["name"] == "tables"), {})
    if table_stage.get("status") == "skipped":
        lines.append(
            "Tablas de personajes/clases/objetos: omitidas; se necesita una definición ligada a esta ROM."
        )
    lines.append("Revisar cabeceras no equivale a identificar gráficos, mapas, eventos ni código fuente.")
    return lines


def render(document: dict, format: str = "markdown", *, review: dict | None = None) -> str:
    report = summary(document, review)
    explanations = overview(document)
    metrics = report["resource_interpretation"]
    explanations.append(
        f"Candidatos: {metrics['candidates']}; bloques únicos: {metrics['unique_blobs']}; "
        f"bloques con vista: {metrics['generated_previews']}; archivos PNG: {metrics['generated_png_files']}; "
        f"aceptados por revisión con evidencia: "
        f"{metrics['identified_by_user_review']}; pendientes de interpretar: {metrics['pending_interpretation']}."
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if format == "html":
        rows = "".join(
            "<tr><td>"
            + html.escape(e["kind"])
            + "</td><td>"
            + html.escape(e["key"])
            + "</td><td>"
            + html.escape(str(e["offset"]))
            + "</td><td>"
            + html.escape(e["validation"])
            + "</td></tr>"
            for e in document["entities"]
        )
        return (
            '<!doctype html><html lang="es"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            "<title>ArcanaCart — Informe local</title><style>"
            "body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem;color:#152635;background:#fafcff}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3f8;padding:1rem}"
            "td,th{padding:.45rem;border-bottom:1px solid #ccc;text-align:left}table{border-collapse:collapse;width:100%}"
            "</style><main><h1>ArcanaCart — Informe local</h1>"
            "<p>Validación estructural y referencias heurísticas no equivalen a reconstrucción completa.</p>"
            + "<h2>Estado del análisis</h2>"
            + "".join("<p>" + html.escape(line) + "</p>" for line in explanations)
            + "<h2>Entidades</h2><table><thead><tr><th>Tipo</th><th>ID lógico</th><th>Offset</th><th>Validación</th>"
            "</tr></thead><tbody>"
            + rows
            + "</tbody></table><h2>Evidencias y cobertura</h2><pre>"
            + html.escape(serialized)
            + "</pre></main></html>"
        )
    if format != "markdown":
        raise ValueError("Formato de informe inválido.")
    # Longer dynamic fences keep untrusted backticks inside the JSON block.
    fence = "`" * max(3, max((len(s) for s in __import__("re").findall(r"`+", serialized)), default=0) + 1)
    return (
        "# ArcanaCart — Informe local\n\n"
        + (
            "Las cifras corresponden a bytes y registros efectivamente analizados. "
            "Los rangos se unen para evitar contar solapamientos dos veces. "
            "La ausencia de un parser deja su categoría desconocida.\n\n"
        )
        + "\n\n".join(explanations)
        + "\n\n"
        + fence
        + "json\n"
        + serialized
        + "\n"
        + fence
        + "\n"
    )


def write_report(
    document: dict, out: Path, *, format: str = "markdown", force: bool = False, review: dict | None = None
) -> None:
    atomic_write(out, render(document, format, review=review).encode("utf-8"), force=force)
