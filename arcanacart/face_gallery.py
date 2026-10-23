"""Offline gallery of reconstructed face-table components with source traces."""

from __future__ import annotations

import base64
import hashlib
import html
import json

SCRIPT = r"""
'use strict';
const search=document.getElementById('search'),kind=document.getElementById('kind');
const cards=[...document.querySelectorAll('article')],count=document.getElementById('count');
function filter(){let n=0;const q=search.value.trim().toLowerCase();for(const card of cards){const show=(!kind.value||card.dataset.kind===kind.value)&&card.dataset.search.includes(q);card.hidden=!show;if(show)n++;}count.textContent=n+' componentes';}
search.addEventListener('input',filter);kind.addEventListener('change',filter);filter();
"""
LABELS = {"portrait": "Retrato", "miniature": "Miniatura", "classcard": "Tarjeta de clase"}


def render_face_gallery(summary: dict, rows: list[dict]) -> str:
    token = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    cards = []
    for row in rows:
        title = f"{LABELS[row['kind']]} · ID {row['face_id_hex']} ({row['face_id']})"
        trace = html.escape(json.dumps(row, ensure_ascii=False, indent=2))
        search = html.escape(
            f"{row['face_id_hex']} {row['face_id']} {row['source_sha256']} {row['source_offset']:#x}"
            if row["source_offset"] is not None
            else title.lower(),
            quote=True,
        ).lower()
        if row.get("png"):
            name = html.escape(row["png"], quote=True)
            picture = f'<a href="{name}" download><img src="{name}" alt="{html.escape(title, quote=True)}" loading="lazy"></a>'
            picture += (
                f'<p><a href="{name}" download>Descargar PNG · {row["width"]} × {row["height"]}</a></p>'
            )
        else:
            picture = '<p class="error">' + html.escape(row.get("error", "Sin imagen")) + "</p>"
        colors = (
            "Paleta RGB555 leída de la ROM verificada"
            if row["colors"] == "rgb555-rom"
            else "Gris de diagnóstico · falta la paleta original"
        )
        offset = f"0x{row['source_offset']:06X}" if row["source_offset"] is not None else "Sin offset"
        cards.append(
            f'<article data-kind="{row["kind"]}" data-search="{search}"><h2>{html.escape(title)}</h2>'
            + picture
            + f'<p class="muted">{colors}</p><p>Bloque: <code>{offset}</code></p>'
            + f'<p class="hash">SHA-256: {html.escape(row["source_sha256"] or "Sin bloque")}</p>'
            + f"<details><summary>Identificación y trazabilidad</summary><pre>{trace}</pre></details></article>"
        )
    stats = "".join(
        f"<div><strong>{summary[key]:,}</strong>{label}</div>"
        for key, label in (
            ("portraits", "retratos"),
            ("miniatures", "miniaturas"),
            ("classcards", "tarjetas de clase"),
            ("unique_classified_blobs", "bloques únicos vinculados"),
            ("resolved_palettes", "paletas reales"),
        )
    )
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src 'self' file:; "
        f"style-src 'unsafe-inline'; script-src 'sha256-{token}'; base-uri 'none'; form-action 'none'\">"
        "<title>ArcanaCart · Retratos reconstruidos</title><style>"
        ":root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#101522;color:#eef2fb;font:16px/1.5 system-ui}"
        "main{max-width:1500px;margin:auto;padding:32px}h1{font-size:2.5rem;margin:0;letter-spacing:-.04em}h2{font-size:1rem;margin-top:0}"
        "a{color:#d4c6ff}.muted{color:#b4bfd1}.error{color:#ffc0a5}.stats{display:flex;gap:14px;flex-wrap:wrap;margin:24px 0}"
        ".stats div{padding:16px;background:#20283b;border-radius:10px}.stats strong{display:block;font-size:1.8rem;color:#c9b6ff}"
        ".filters{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:28px 0}input,select{font:inherit;padding:10px;background:#263048;color:inherit;border:1px solid #64708b;border-radius:6px}"
        "input{min-width:240px}#cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:18px}"
        "article{background:#1b2334;border:1px solid #424f6a;border-radius:12px;padding:18px;min-width:0}article[hidden]{display:none}"
        "article img{display:block;width:100%;height:200px;object-fit:contain;image-rendering:pixelated;background:repeating-conic-gradient(#343c4d 0% 25%,#293143 0% 50%) 0/16px 16px}"
        ".hash{font:12px/1.5 monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}details{margin-top:16px}"
        ":focus-visible{outline:3px solid #dbcbff;outline-offset:3px}@media(max-width:600px){main{padding:18px}h1{font-size:2rem}}"
        '</style></head><body><main><p class="muted">ARCANACART / EXTRACCIÓN ORGANIZADA</p>'
        "<h1>Retratos reconstruidos</h1><p>Componentes vinculados a una tabla documentada y exportados por ID.</p>"
        '<div class="stats">' + stats + "</div>"
        "<p>Las imágenes en gris muestran índices, con contraste ajeno a los colores originales. Los nombres de personajes y las animaciones de boca/ojos quedan pendientes. Los ID pueden compartir el mismo bloque. Esta clasificación no cambia tus revisiones manuales anteriores.</p>"
        '<p><a href="catalog.csv">Catálogo CSV</a> · <a href="catalog.json">Catálogo JSON</a> · <a href="summary.json">Resumen</a></p>'
        '<div class="filters"><label>Buscar ID, hash u offset <input id="search" type="search" placeholder="0x016, hash, offset…"></label>'
        '<label>Tipo <select id="kind"><option value="">Todos</option><option value="portrait">Retratos</option>'
        '<option value="miniature">Miniaturas</option><option value="classcard">Tarjetas de clase</option></select></label>'
        '<span id="count" role="status"></span></div><section id="cards">' + "".join(cards) + "</section>"
        "<details><summary>Alcance y resultados</summary><pre>"
        + html.escape(json.dumps(summary, ensure_ascii=False, indent=2))
        + "</pre></details></main><script>"
        + SCRIPT
        + "</script></body></html>"
    )
