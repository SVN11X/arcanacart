"""Standalone, paginated gallery with an offline recipe editor."""

from __future__ import annotations

import base64
import hashlib
import html
import json
from string import Template

SCRIPT = r"""
'use strict';
const payload=JSON.parse(document.getElementById('payload').textContent);
const rows=payload.rows, recipes=payload.recipes, pageSize=48;
const $=id=>document.getElementById(id);
let page=0, selected=null, filtered=rows;
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;}
function filter(){
 const query=$('search').value.toLowerCase().trim(),status=$('status').value;
 filtered=rows.filter(r=>(!status||recipes.resources[r.sha256].review===status)&&
  [r.sha256,...r.offsets.map(n=>'0x'+n.toString(16)),...r.offsets,...(r.hypotheses||[]),r.base_match===false?'sin coincidencia':'',r.recipe.mode].join(' ').toLowerCase().includes(query));
 page=0; draw();
}
function draw(){
 $('cards').replaceChildren();
 for(const row of filtered.slice(page*pageSize,(page+1)*pageSize)){
  const card=node('article'),button=node('button',row.sha256.slice(0,16)+'…','hash');
  button.addEventListener('click',()=>edit(row));card.append(button);
  if(row.png){
   const pages=row.pages&&row.pages.length?row.pages:[{png:row.png,width:row.width,height:row.height}];
   const img=node('img');img.loading='lazy';card.append(img);
   const a=node('a','Descargar PNG');a.download='';card.append(a);
   const info=node('p');card.append(info);
   function show(i){const p=pages[i];img.src=p.png;img.alt='Interpretación '+row.recipe.mode+' del bloque '+row.sha256+', página '+(i+1)+' de '+pages.length;a.href=p.png;info.textContent='Página '+(i+1)+' de '+pages.length+' · '+p.width+' × '+p.height+(p.first_tile!==undefined?' · tiles '+p.first_tile+'–'+(p.first_tile+p.tile_count-1):'');}
   if(pages.length>1){const label=node('label','Página de este bloque');const select=node('select');select.setAttribute('aria-label','Página del bloque '+row.sha256);pages.forEach((p,i)=>select.append(new Option(String(i+1)+' de '+pages.length,String(i))));select.addEventListener('change',()=>show(Number(select.value)));label.append(select);card.append(label);}
   show(0);
  }
  else card.append(node('div',row.preview_error||row.error||'Sin previsualización','placeholder'));
  card.append(node('p',row.size_bytes+' bytes · '+row.offsets.length+' ubicación(es)'));
  card.append(node('p',row.offsets.slice(0,4).map(n=>'0x'+n.toString(16).toUpperCase()).join(', ')));
  card.append(node('p',(row.hypotheses||[]).join(' / ')||'Tipo pendiente'));
  card.append(node('p',row.colors==='grayscale-placeholder'?'Paleta de diagnóstico en gris':row.colors==='rgb555'?'Paleta RGB555: '+(row.recipe.palette_sha256||'bloque interpretado como paleta'):'Paleta sin asignar'));
  card.append(node('p','Revisión: '+recipes.resources[row.sha256].review,'badge'));
  if(row.base_match!==null)card.append(node('p',row.base_match?'Contenido observado en base':'Sin coincidencia observada en base'));
  $('cards').append(card);
 }
 $('position').textContent=filtered.length+' bloques · página '+(page+1)+' de '+Math.max(1,Math.ceil(filtered.length/pageSize));
 $('previous').disabled=page===0;$('next').disabled=(page+1)*pageSize>=filtered.length;
}
function edit(row){
 selected=row.sha256;const r=recipes.resources[selected];
 $('editor').hidden=false;$('selected').textContent=selected;
 for(const key of ['mode','bpp','width_tiles','height_tiles','palette_offset','map_layout','review','note'])$(key).value=r[key];
 for(const key of ['palette_sha256','tiles_sha256']){
  const select=$(key);select.replaceChildren();select.append(new Option('Ninguno', ''));
  const choices=key==='palette_sha256'?[...rows,...payload.externalPalettes]:rows;
  for(const candidate of choices){if(key==='palette_sha256'&&!(candidate.hypotheses||[]).includes('rgb555-palette')&&!candidate.external&&candidate.sha256!==r[key])continue;
   select.append(new Option(candidate.sha256.slice(0,20)+' · '+candidate.size_bytes+' B',candidate.sha256));}
  select.value=r[key]||'';
 }
 $('transparent_zero').checked=r.transparent_zero;$('evidence').value=r.evidence.join('\n');
 $('trace').textContent=JSON.stringify(row,null,2);$('mode').focus();$('editor').scrollIntoView({behavior:'smooth'});
}
$('apply').addEventListener('click',()=>{
 if(!selected)return;
 for(const [key,min,max] of [['width_tiles',1,128],['height_tiles',1,128],['palette_offset',0,511]]){
  const value=Number($(key).value);if(!Number.isInteger(value)||value<min||value>max){$('notice').textContent='Revisa el valor de '+key+': debe ser un entero entre '+min+' y '+max+'.';return;}
 }
 const evidence=$('evidence').value.split('\n').map(s=>s.trim()).filter(Boolean);
 if($('review').value==='accepted'&&(!evidence.length||$('mode').value==='unknown')){
  $('notice').textContent='Para aceptar se necesita una interpretación y al menos una evidencia.';return;
 }
 const r=recipes.resources[selected];
 for(const key of ['mode','map_layout','review','note'])r[key]=$(key).value;
 for(const key of ['bpp','width_tiles','height_tiles','palette_offset'])r[key]=Number($(key).value);
 for(const key of ['palette_sha256','tiles_sha256'])r[key]=$(key).value||null;
 r.evidence=evidence;r.transparent_zero=$('transparent_zero').checked;
 $('notice').textContent='Ajustes guardados en esta pestaña. Descarga las recetas y vuelve a ejecutar interpret en otra carpeta para generar los PNG con estos ajustes.';draw();
});
$('download').addEventListener('click',()=>{
 const url=URL.createObjectURL(new Blob([JSON.stringify(recipes,null,2)],{type:'application/json'}));
 const a=node('a');a.href=url;a.download='recipes-revisadas.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
});
$('search').addEventListener('input',filter);$('status').addEventListener('change',filter);
$('previous').addEventListener('click',()=>{page--;draw();});$('next').addEventListener('click',()=>{page++;draw();});draw();
"""


def render_gallery(summary: dict, rows: list[dict], recipes: dict) -> str:
    summary = {"generated_png_files": summary["generated_previews"], **summary}
    token = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    payload = (
        json.dumps(
            {
                "rows": rows,
                "recipes": recipes,
                "externalPalettes": [{**p, "external": True} for p in summary.get("external_palettes", [])],
            },
            ensure_ascii=True,
        )
        .replace("<", "\\u003c")
        .replace("&", "\\u0026")
    )
    template = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file: data:; style-src 'unsafe-inline'; script-src 'sha256-$token'; base-uri 'none'; form-action 'none'">
<title>ArcanaCart · Recursos</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#101420;color:#eef0f6;font:16px/1.5 system-ui}main{max-width:1480px;margin:auto;padding:32px}
h1{font-size:2.5rem;letter-spacing:-.05em;margin:0}h2{margin-top:0}.eyebrow{color:#c2adff;letter-spacing:.14em;font-size:.8rem}.muted{color:#b7bfd0}.stats{display:flex;gap:14px;flex-wrap:wrap;margin:28px 0}.stats div{background:#1c2233;padding:16px 22px;border-radius:12px}.stats strong{font-size:1.7rem;display:block;color:#cfbfff}
nav,.filters{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:24px 0}button,input,select,textarea{font:inherit;border:1px solid #57617a;border-radius:7px;padding:10px;background:#252d42;color:#fff}button,a{cursor:pointer}button:disabled{opacity:.4}a{color:#d4c2ff}input[type=search]{flex:1;min-width:220px}button:hover{background:#39435c}:focus-visible{outline:3px solid #d7c5ff;outline-offset:3px}
#cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(265px,1fr));gap:18px}article{border:1px solid #3c4355;border-radius:12px;padding:16px;background:#1a2030;min-width:0}article p{font-size:.85rem;overflow-wrap:anywhere;margin:.55rem 0}.hash{width:100%;text-align:left;background:transparent;border:0;padding:0 0 12px;color:#d9ceff}article img{width:100%;height:180px;object-fit:contain;image-rendering:pixelated;background:repeating-conic-gradient(#323644 0% 25%,#252a39 0% 50%) 0/16px 16px;display:block;margin-bottom:10px}.placeholder{height:180px;padding:18px;border:1px dashed #586078;display:flex;align-items:center;overflow:auto;font-size:.8rem}.badge{color:#bfe6cf}
#editor{padding:24px;border:1px solid #a28acb;border-radius:14px;margin-top:30px}#selected{overflow-wrap:anywhere;font-family:monospace}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}label{display:grid;gap:6px}textarea{width:100%;min-height:90px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}#notice{color:#f7d89e}details{margin-top:20px}@media(max-width:600px){main{padding:18px}h1{font-size:2rem}}
</style></head><body><main><p class="eyebrow">ARCANACART / INVESTIGACIÓN LOCAL</p><h1>Explorador de recursos</h1>
<p class="muted">Hipótesis, paletas y evidencia para revisar los bloques ya extraídos.</p>
<div class="stats">$stats</div>
<p>Las cifras corresponden a esta ejecución; los ajustes del editor requieren regeneración. Un PNG demuestra que una interpretación se pudo renderizar. El tipo y uso en el juego requieren evidencia. Los grises son colores de diagnóstico. Un mapa FE con metatiles requiere su propia definición.</p>
<p><a href="catalog.json">Catálogo JSON</a> · <a href="catalog.csv">Catálogo CSV</a> · <a href="summary.json">Resumen</a> · <a href="recipes.json">Recetas iniciales</a></p>
<div class="filters"><label for="search">Buscar</label><input id="search" type="search" placeholder="Hash, offset hexadecimal, hipótesis…"><label for="status">Revisión</label><select id="status"><option value="">Todas</option><option value="unreviewed">Pendientes</option><option value="accepted">Aceptadas</option><option value="rejected">Descartadas</option></select></div>
<nav aria-label="Páginas"><button id="previous">Anterior</button><span id="position" aria-live="polite"></span><button id="next">Siguiente</button><button id="download">Descargar recetas revisadas</button></nav>
<div id="cards"></div><noscript>Activa JavaScript para la galería o abre el catálogo CSV/JSON. No se realizan conexiones de red.</noscript>
<section id="editor" hidden><h2>Interpretación manual</h2><p id="selected"></p><p>Los ajustes se exportan a JSON. Para aplicarlos a las imágenes, ejecuta <code>interpret --recipes</code> en una salida nueva. Guarda las recetas antes de cerrar esta pestaña.</p>
<div class="form-grid">
<label>Interpretación<select id="mode"><option value="unknown">Pendiente</option><option value="tiles">Tiles</option><option value="palette">Paleta RGB555</option><option value="bg-map">Mapa BG de texto</option><option value="fe-map">Mapa FE (sin render de metatiles)</option><option value="data">Otros datos</option></select></label>
<label>Profundidad<select id="bpp"><option value="4">4 bpp</option><option value="8">8 bpp</option></select></label>
<label>Ancho en tiles<input id="width_tiles" type="number" min="1" max="128"></label><label>Alto del mapa en tiles<input id="height_tiles" type="number" min="1" max="128"></label>
<label>Bloque de paleta<select id="palette_sha256"></select></label><label>Primer color (solo tiles)<input id="palette_offset" type="number" min="0" max="511"></label>
<label>Tileset para mapa BG<select id="tiles_sha256"></select></label><label>Distribución del mapa<select id="map_layout"><option value="linear">Filas lineales</option><option value="screenblocks">Screenblocks GBA 32×32</option></select></label>
<label>Estado<select id="review"><option value="unreviewed">Pendiente</option><option value="accepted">Aceptada con evidencia</option><option value="rejected">Descartada por revisión</option></select></label>
<label><span>Índice cero transparente</span><input id="transparent_zero" type="checkbox"></label>
</div><label>Evidencia (una por línea)<textarea id="evidence" maxlength="2000"></textarea></label><label>Nota<textarea id="note" maxlength="2000"></textarea></label>
<button id="apply">Guardar ajustes en esta pestaña</button><p id="notice" role="status"></p><details><summary>Trazabilidad y configuración usada en el PNG actual</summary><pre id="trace"></pre></details></section>
<details><summary>Alcance del procesamiento</summary><pre>$summary</pre></details>
</main><script type="application/json" id="payload">$payload</script><script>$script</script></body></html>"""
    stats = "".join(
        f"<div><strong>{summary[key]:,}</strong>{label}</div>"
        for key, label in (
            ("candidates", "candidatos"),
            ("unique_blobs", "bloques únicos"),
            ("generated_previews", "bloques con vista"),
            ("generated_png_files", "archivos PNG"),
            ("identified_by_user_review", "aceptados con evidencia"),
            ("pending_interpretation", "pendientes"),
        )
    )
    return Template(template).substitute(
        token=token,
        stats=stats,
        summary=html.escape(json.dumps(summary, ensure_ascii=False, indent=2)),
        payload=payload,
        script=SCRIPT,
    )
