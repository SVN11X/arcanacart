"""Offline consolidated icon gallery with filters correlated by origin."""

from __future__ import annotations

import base64
import hashlib
import json

FILTER_SCRIPT = """
function matchingImages(images,game,variant,term,showTransparent){
 term=term.trim().toLowerCase();const result=[];
 const id=/^(?:0x[0-9a-f]+|[0-9]+)$/.test(term)?Number(term):null;
 for(const image of images){
  if(!image.visible&&!showTransparent)continue;
  const origins=image.origins.filter(o=>(!game||o.game===game)&&(!variant||o.variant_id===variant)&&
   (!term||(id!==null?o.icon_id===id:[image.png_sha256,o.variant,o.variant_id,o.icon_id_hex,o.rom_sha256,
    o.air_sha256,o.source_sha256,o.palette_sha256].some(s=>String(s).toLowerCase().includes(term)))));
  if(origins.length)result.push({image,origins});
 }
 return result;
}
"""

SCRIPT = "'use strict';\n" + FILTER_SCRIPT + """
const data=JSON.parse(document.getElementById('catalog-data').textContent);
const game=document.getElementById('game'),variant=document.getElementById('variant');
const search=document.getElementById('search'),transparent=document.getElementById('transparent');
const cards=document.getElementById('cards'),count=document.getElementById('count');
const previous=document.getElementById('previous'),next=document.getElementById('next');
let filtered=[],page=0;const pageSize=64;
function element(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;}
function download(label,path){const node=element('a',label);node.href=path;node.download='';return node;}
function variants(){const old=variant.value;variant.replaceChildren();
 const all=element('option','Todas las variantes');all.value='';variant.append(all);
 for(const r of data.variants.filter(r=>!game.value||r.game===game.value)){
  const option=element('option',r.game.toUpperCase()+' · '+r.variant);option.value=r.variant_id;variant.append(option);}
 variant.value=data.variants.some(r=>r.variant_id===old&&(!game.value||r.game===game.value))?old:'';
}
function originDetails(origins){
 const details=element('details'),list=element('ol'),status=element('p'),more=element('button','Mostrar más');
 details.append(element('summary',origins.length+(origins.length===1?' procedencia coincidente':' procedencias coincidentes')),list,status,more);
 more.type='button';let cursor=0;
 function append(){const end=Math.min(cursor+100,origins.length);
  for(const o of origins.slice(cursor,end)){
   const item=element('li');item.append(element('p',o.game.toUpperCase()+' · '+o.variant+' · ID '+o.icon_id_hex));
   item.append(download('Raw 4bpp',o.raw_file),download('Paleta RGB555',o.palette_file));
   item.append(element('p','Offset ROM: 0x'+o.source_offset.toString(16).toUpperCase()+
    ' · Paleta: 0x'+o.palette_offset.toString(16).toUpperCase()));
   item.append(element('p','ROM SHA-256: '+o.rom_sha256),element('p','AIR SHA-256: '+o.air_sha256));
   item.append(element('p','Raw SHA-256: '+o.source_sha256),element('p','Paleta SHA-256: '+o.palette_sha256));
   item.append(element('p','Origen PNG: '+o.source_png));list.append(item);
  }
  cursor=end;status.textContent=cursor+' de '+origins.length+' procedencias';more.hidden=cursor>=origins.length;
 }
 details.addEventListener('toggle',()=>{if(details.open&&cursor===0)append();});
 more.addEventListener('click',append);return details;
}
function render(){const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
 page=Math.max(0,Math.min(page,pages-1));cards.replaceChildren();
 for(const row of filtered.slice(page*pageSize,(page+1)*pageSize)){
  const image=row.image,card=element('article'),png=element('img');
  png.src=image.file;png.alt='Icono '+image.png_sha256.slice(0,12);png.loading='lazy';
  card.append(element('h2','PNG '+image.png_sha256.slice(0,12)),png,download('Descargar PNG',image.file));
  card.append(element('p',row.origins.length+' de '+image.origins.length+' apariciones'));
  if(!image.visible)card.append(element('p','Totalmente transparente'));
  card.append(originDetails(row.origins));cards.append(card);
 }
 const appearances=filtered.reduce((sum,row)=>sum+row.origins.length,0);
 count.textContent=filtered.length+(filtered.length===1?' icono · ':' iconos · ')+appearances+
  (appearances===1?' aparición · Página ':' apariciones · Página ')+(page+1)+' de '+pages;
 previous.disabled=page===0;next.disabled=page+1>=pages;
 document.getElementById('empty').hidden=filtered.length!==0;
}
function filter(){page=0;filtered=matchingImages(data.images,game.value,variant.value,search.value,transparent.checked);render();}
game.addEventListener('change',()=>{variants();filter();});variant.addEventListener('change',filter);
search.addEventListener('input',filter);transparent.addEventListener('change',filter);
previous.addEventListener('click',()=>{page--;render();});next.addEventListener('click',()=>{page++;render();});
document.getElementById('reset').addEventListener('click',()=>{
 game.value='';variant.value='';search.value='';transparent.checked=false;variants();filter();});
variants();filter();
"""


def gallery(catalog: dict) -> bytes:
    summary = catalog["summary"]
    embedded = json.dumps({"images": catalog["images"], "variants": catalog["variants"]},
                          ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    text = f'''<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'sha256-{script_hash}'; base-uri 'none'; form-action 'none'">
<title>ArcanaCart · Catálogo de iconos</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f4fa;color:#18263c;font:16px/1.5 system-ui}}
main{{max-width:1400px;margin:auto;padding:24px}}h1{{margin-bottom:8px}}h2{{font:15px monospace;overflow-wrap:anywhere}}
nav,.filters{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:24px 0}}
label{{display:grid;gap:6px}}input,select,button{{font:inherit;padding:10px;border:1px solid #65758c;border-radius:6px}}
select{{max-width:340px}}input[type=search]{{width:280px;max-width:100%}}
.check{{display:flex;align-items:center;gap:8px}}input[type=checkbox]{{width:22px;height:22px}}
a{{color:#204d9b}}button,summary{{cursor:pointer}}:focus-visible{{outline:3px solid #315fa8;outline-offset:3px}}
#cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px}}
article{{background:white;border:1px solid #cbd4e2;border-radius:10px;padding:18px;min-width:0}}
article img{{display:block;width:112px;height:112px;image-rendering:pixelated;margin:12px 0;
background:repeating-conic-gradient(#e0e5ef 0% 25%,#f6f7fa 0% 50%) 0/16px 16px}}
details{{margin-top:16px}}details li{{margin-bottom:20px}}details p{{font:12px/1.5 monospace;overflow-wrap:anywhere}}
details a{{display:block;margin:6px 0}}ol{{padding-left:24px}}[hidden]{{display:none!important}}
@media(max-width:600px){{main{{padding:16px}}.filters label,.filters select{{width:100%;max-width:100%}}}}
</style></head><body><main><p>ARCANACART</p><h1>Catálogo de iconos</h1>
<p>{summary['unique_images']} imágenes únicas · {summary['icon_occurrences']} apariciones · {summary['variants']} variantes</p>
<p>Un PNG puede aparecer con distintos IDs. Cada procedencia conserva su variante, raw, paleta, offsets y hashes.</p>
<nav aria-label="Archivos del catálogo"><a href="imagenes.csv" download>Imágenes CSV</a>
<a href="ocurrencias.csv" download>Procedencias CSV</a><a href="catalogo.json" download>Catálogo JSON</a>
<a href="resumen.json">Resumen y límites</a></nav>
<section class="filters" aria-label="Filtros"><label>Juego<select id="game">
<option value="">Todos los juegos</option><option value="fe7">FE7</option><option value="fe8">FE8</option></select></label>
<label>Variante<select id="variant"></select></label><label>Buscar ID, variante o hash
<input id="search" type="search" maxlength="256" placeholder="0x01, fe8-001, SHA-256…"></label>
<label class="check"><input id="transparent" type="checkbox">Mostrar transparentes</label>
<button id="reset" type="button">Restablecer</button></section>
<p id="count" role="status" aria-live="polite"></p><p id="empty" hidden>Sin coincidencias.</p>
<section id="cards" aria-label="Iconos únicos"></section><nav aria-label="Páginas">
<button id="previous" type="button">Anterior</button><button id="next" type="button">Siguiente</button></nav>
<p>Los rangos exportados no confirman la totalidad de recursos ni la capacidad completa de las tablas.</p>
<noscript>Activa JavaScript para filtrar la galería. Los CSV y JSON conservan todas las procedencias.</noscript>
</main><script id="catalog-data" type="application/json">{embedded}</script><script>{SCRIPT}</script></body></html>'''
    return text.encode("utf-8")
