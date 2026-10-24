"""Self-contained local item-icon gallery; no external scripts, fonts or requests."""

from __future__ import annotations

import base64
import hashlib
import html
import json

SCRIPT = """
'use strict';
const rows=JSON.parse(document.getElementById('icon-data').textContent);
const cards=document.getElementById('cards'),q=document.getElementById('search');
const transparent=document.getElementById('transparent'),label=document.getElementById('count');
const previous=document.getElementById('previous'),next=document.getElementById('next');
let page=0,filtered=[];const pageSize=64;
function element(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
function render(){cards.replaceChildren();const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
 page=Math.max(0,Math.min(page,pages-1));
 for(const r of filtered.slice(page*pageSize,(page+1)*pageSize)){
  const card=element('article'),img=element('img');img.src=r.file;img.alt='Icono '+r.icon_id_hex;img.loading='lazy';
  card.append(element('h2',r.icon_id_hex),img);
  if(!r.visible)card.append(element('p','Totalmente transparente'));
  for(const [name,path] of [['PNG',r.file],['Raw 4bpp',r.raw_file],['Paleta RGB555',r.palette_file]]){
   const a=element('a',name);a.href=path;a.download='';card.append(a);}
  const details=element('details');details.append(element('summary','Procedencia'));
  details.append(element('p','ROM 0x'+r.source_offset.toString(16).toUpperCase()+' · 128 bytes'));
  details.append(element('p','SHA-256 raw: '+r.source_sha256),element('p','SHA-256 PNG: '+r.png_sha256));
  card.append(details);cards.append(card);
 }
 label.textContent=filtered.length+' IDs coincidentes · Página '+(page+1)+' de '+pages;
 previous.disabled=page===0;next.disabled=page+1>=pages;
 document.getElementById('empty').hidden=filtered.length!==0;
}
function filter(){page=0;const term=q.value.trim().toLowerCase();filtered=rows.filter(r=>
 (r.visible||transparent.checked)&&(!term||[r.icon_id_hex,String(r.icon_id),r.source_sha256,r.png_sha256]
 .some(s=>s.toLowerCase().includes(term))));render();}
q.addEventListener('input',filter);transparent.addEventListener('change',filter);
previous.addEventListener('click',()=>{page--;render();});next.addEventListener('click',()=>{page++;render();});
document.getElementById('reset').addEventListener('click',()=>{q.value='';transparent.checked=false;filter();});
filter();
"""


def gallery(summary: dict, rows: list[dict]) -> bytes:
    embedded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    game = html.escape(summary["game"].upper())
    text = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'sha256-{script_hash}'; base-uri 'none'; form-action 'none'">
<title>ArcanaCart · Iconos {game}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f4fa;color:#18263c;font:16px/1.5 system-ui}}
main{{max-width:1300px;margin:auto;padding:24px}}h1{{margin-bottom:4px}}h2{{font-size:1.1rem}}
.filters,nav{{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:24px 0}}
label{{display:flex;gap:8px;align-items:center}}input,button{{font:inherit;padding:10px;border:1px solid #65758c;border-radius:6px}}
button{{cursor:pointer}}input[type=checkbox]{{width:22px;height:22px}}input[type=search]{{max-width:100%;width:280px}}
a{{color:#204d9b}}:focus-visible{{outline:3px solid #315fa8;outline-offset:3px}}
#cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}}
article{{background:white;padding:18px;border:1px solid #cbd4e2;border-radius:10px;min-width:0}}
article img{{display:block;width:112px;height:112px;image-rendering:pixelated;margin-bottom:14px;
background:repeating-conic-gradient(#e0e5ef 0% 25%,#f6f7fa 0% 50%) 0/16px 16px}}
article a{{display:block;margin:6px 0}}details{{margin-top:14px}}summary{{cursor:pointer}}
details p{{overflow-wrap:anywhere;font:12px/1.5 monospace}}[hidden]{{display:none!important}}
@media(max-width:500px){{main{{padding:16px}}.filters label:first-child{{display:grid;width:100%}}}}
</style></head><body><main>
<p>ARCANACART / {game}</p><h1>Iconos de objetos y armas</h1>
<p>{summary["icon_occurrences"]} IDs · {summary["unique_images"]} PNG únicos · 16 × 16 píxeles</p>
<p>Los IDs identifican posiciones del banco de iconos. No son nombres ni IDs de objetos.</p>
<p><a href="icons.csv" download>Índice CSV</a> · <a href="catalog.json" download>Catálogo JSON</a> ·
<a href="summary.json">Resumen y límites</a> · <a href="definition.json" download>Definición utilizada</a></p>
<section class="filters" aria-label="Filtros"><label>Buscar ID o hash
<input id="search" type="search" placeholder="0x01, 12, SHA-256…"></label>
<label><input id="transparent" type="checkbox">Mostrar transparentes</label>
<button id="reset" type="button">Restablecer</button></section>
<p id="count" role="status" aria-live="polite"></p><p id="empty" hidden>Sin coincidencias.</p>
<section id="cards" aria-label="Iconos"></section><nav aria-label="Páginas">
<button id="previous" type="button">Anterior</button><button id="next" type="button">Siguiente</button></nav>
<noscript>Activa JavaScript para la galería. El CSV y el JSON conservan todos los IDs.</noscript>
</main><script id="icon-data" type="application/json">{embedded}</script><script>{SCRIPT}</script></body></html>
"""
    return text.encode("utf-8")
