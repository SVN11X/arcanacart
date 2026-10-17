"""Standalone reports with escaped input, real denominators and stated limits."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from arcanacart.core.io import atomic_write
from arcanacart.exporters import target_compatibility
from arcanacart.schemas import validate


def summary(document: dict) -> dict:
    validate(document)
    return {
        "identification": document["rom"],
        "profile": document["profile"],
        "entities_by_type": dict(Counter(e["kind"] for e in document["entities"])),
        "resources": len(document["resources"]),
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
    status = "parcial" if document["errors"] or scan.get("truncated") else "finalizado"
    lines = [f"Estado de las etapas solicitadas: {status}."]
    if scan:
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
    table_stage: dict = next((s for s in document["stages"] if s["name"] == "tables"), {})
    if table_stage.get("status") == "skipped":
        lines.append(
            "Tablas de personajes/clases/objetos: omitidas; se necesita una definición ligada a esta ROM."
        )
    lines.append("Revisar cabeceras no equivale a identificar gráficos, mapas, eventos ni código fuente.")
    return lines


def render(document: dict, format: str = "markdown") -> str:
    report = summary(document)
    explanations = overview(document)
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


def write_report(document: dict, out: Path, *, format: str = "markdown", force: bool = False) -> None:
    atomic_write(out, render(document, format).encode("utf-8"), force=force)
