"""Local gallery of movement tile sheets with all class/table origins and AP links."""

from __future__ import annotations

import base64
import hashlib
import json

SCRIPT = r"""'use strict';
function matchingResources(data,game,variant,term,transparent){
 term=term.trim().toLowerCase();const id=/^(?:0x[0-9a-f]+|[0-9]+)$/.test(term)?Number(term):null,groups=new Map();
 for(const o of data.occurrences){
  if((game&&o.game!==game)||(variant&&o.variant_id!==variant))continue;
  if(term&&(id!==null?o.class_id!==id:![o.variant_id,o.variant,o.raw_sha256,o.ap_sha256,o.stored_sha256,o.rom_sha256,o.air_sha256].some(v=>String(v||'').toLowerCase().includes(term))))continue;
  if(!groups.has(o.resource_id))groups.set(o.resource_id,[]);groups.get(o.resource_id).push(o);
 }
 return data.resources.filter(r=>groups.has(r.resource_id)&&(transparent||data.previews[r.raw_sha256].visible)).map(resource=>({resource,origins:groups.get(resource.resource_id)}));
}
const data=JSON.parse(document.getElementById('movement-data').textContent),nodes={};
for(const key of ['game','variant','palette','search','transparent','cards','count','previous','next','empty','reset'])nodes[key]=document.getElementById(key);
let selected=[],page=0;const perPage=48;
function element(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function link(text,path){const n=element('a',text);n.href=path;n.download='';return n;}
function variants(){const previous=nodes.variant.value;nodes.variant.replaceChildren();const all=element('option','Todas las ROM');all.value='';nodes.variant.append(all);
 for(const p of data.profiles.filter(p=>!nodes.game.value||p.game===nodes.game.value)){const o=element('option',p.variant_id+' · '+p.variant);o.value=p.variant_id;nodes.variant.append(o);}
 nodes.variant.value=data.profiles.some(p=>p.variant_id===previous&&(!nodes.game.value||p.game===nodes.game.value))?previous:'';}
function origins(list,resource,rendering){
 const box=element('details'),items=element('ol'),status=element('p'),more=element('button','Mostrar más');more.type='button';let cursor=0;
 box.append(element('summary',list.length+' procedencias coincidentes'),items,status,more);
 function append(){const end=Math.min(cursor+100,list.length);
  for(const o of list.slice(cursor,end)){const item=element('li');
   item.append(element('p',o.game.toUpperCase()+' · '+o.variant_id+' · '+o.variant+' · ID '+o.class_id_hex+' · índice '+o.table_index));
   item.append(element('p','Registro: 0x'+o.entry_offset.toString(16)+' · Hoja: 0x'+o.sheet_offset.toString(16)+' · AP: 0x'+o.ap_offset.toString(16)));
   item.append(link('Raw 4bpp',o.raw_file),link('LZ10 original',o.compressed_file),link('AP binario',resource.ap_file),link('AP interpretado',resource.ap_layout_file),link('Definición',o.definition),link('Paleta de referencia',rendering.palette_file));
   for(const key of ['rom_sha256','air_sha256','raw_sha256','stored_sha256','ap_sha256'])item.append(element('p',key+': '+(o[key]||'No suministrado para esta base')));
   items.append(item);}
  cursor=end;status.textContent=cursor+' de '+list.length+' procedencias';more.hidden=cursor>=list.length;}
 box.addEventListener('toggle',()=>{if(box.open&&cursor===0)append();});more.addEventListener('click',append);return box;
}
function render(){const pages=Math.max(1,Math.ceil(selected.length/perPage));page=Math.max(0,Math.min(page,pages-1));nodes.cards.replaceChildren();
 for(const row of selected.slice(page*perPage,(page+1)*perPage)){
  const r=row.resource,p=data.previews[r.raw_sha256],v=p.renderings[nodes.palette.value],asset=data.images[v.png_sha256],card=element('article'),viewport=element('div'),img=element('img');
  viewport.className='sheet';img.src=asset.file;img.alt='Hoja completa de tiles '+p.raw_sha256.slice(0,12);img.loading='lazy';img.width=asset.width*2;img.height=asset.height*2;viewport.append(img);
  card.append(element('h2','Hoja '+p.raw_sha256.slice(0,12)),element('p',p.tile_count+' tiles · '+asset.width+' × '+asset.height+' px · '+p.padding_tiles+' tiles de relleno transparente'),viewport,link('Descargar hoja PNG',asset.file));
  card.append(element('p','Datos AP: '+r.ap_frames+' fotogramas descritos · '+r.ap_animations+' scripts'),link('AP binario',r.ap_file),link('AP interpretado JSON',r.ap_layout_file),origins(row.origins,r,v));nodes.cards.append(card);
 }
 nodes.count.textContent=selected.length+' recursos distintos · '+selected.reduce((n,r)=>n+r.origins.length,0)+' apariciones · Página '+(page+1)+' de '+pages;
 nodes.previous.disabled=page===0;nodes.next.disabled=page+1>=pages;nodes.empty.hidden=selected.length!==0;
}
function filter(){page=0;selected=matchingResources(data,nodes.game.value,nodes.variant.value,nodes.search.value,nodes.transparent.checked);render();}
nodes.game.addEventListener('change',()=>{variants();filter();});nodes.variant.addEventListener('change',filter);nodes.search.addEventListener('input',filter);nodes.transparent.addEventListener('change',filter);nodes.palette.addEventListener('change',render);
nodes.previous.addEventListener('click',()=>{page--;render();});nodes.next.addEventListener('click',()=>{page++;render();});
nodes.reset.addEventListener('click',()=>{nodes.game.value='';nodes.variant.value='';nodes.search.value='';nodes.transparent.checked=false;nodes.palette.value='player';variants();filter();});
for(const [key,label] of Object.entries(data.palette_roles)){const o=element('option',label+' (referencia)');o.value=key;nodes.palette.append(o);}
nodes.palette.value='player';variants();filter();
"""


def gallery(catalog: dict) -> bytes:
    keys = ("profiles", "resources", "previews", "images", "occurrences", "palette_roles")
    payload = json.dumps({k: catalog[k] for k in keys}, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    csp = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    s = catalog["summary"]
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'sha256-{csp}'; base-uri 'none'; form-action 'none'">
<title>ArcanaCart · Recursos de movimiento</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f4f8;color:#1b293c;font:16px/1.5 system-ui}}main{{max-width:1500px;padding:24px;margin:auto}}
h1{{margin-bottom:8px}}h2{{font:15px monospace;overflow-wrap:anywhere}}nav,.filters{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:24px 0}}
label{{display:grid;gap:6px}}select,input,button{{font:inherit;padding:10px;border:1px solid #66788f;border-radius:6px}}select{{max-width:340px}}input[type=search]{{width:280px;max-width:100%}}
.check{{display:flex;align-items:center;gap:8px}}input[type=checkbox]{{width:22px;height:22px}}a{{color:#204f9c}}button,summary{{cursor:pointer}}:focus-visible{{outline:3px solid #315fa8;outline-offset:3px}}
#cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}}article{{background:white;border:1px solid #ccd5e1;border-radius:10px;padding:18px;min-width:0}}
.sheet{{height:256px;overflow:auto;margin:16px 0;background:repeating-conic-gradient(#dde4ef 0% 25%,#f6f8fb 0% 50%) 0/12px 12px}}.sheet img{{display:block;image-rendering:pixelated;margin:auto}}
article>a,details a{{display:block;margin:6px 0}}details{{margin-top:16px}}details p{{font:12px/1.5 monospace;overflow-wrap:anywhere}}details li{{margin-bottom:20px}}ol{{padding-left:24px}}[hidden]{{display:none!important}}
@media(max-width:600px){{main{{padding:16px}}#cards{{grid-template-columns:minmax(0,1fr)}}.filters label,.filters select{{width:100%;max-width:100%}}}}
</style></head><body><main><p>ARCANACART</p><h1>Hojas y datos AP de movimiento</h1>
<p>{s["unique_resources"]} recursos distintos · {s["occurrences"]} apariciones · {s["roms"]} ROM</p>
<p>Las imágenes muestran las hojas completas de tiles con paletas de referencia del catálogo de reposo. Desplázate dentro de cada hoja para verla completa.</p>
<p>La composición de fotogramas AP, las paletas utilizadas en el juego y la reproducción de animaciones siguen pendientes de validar.</p>
<nav aria-label="Archivos"><a href="ocurrencias.csv" download>Procedencias CSV</a><a href="recursos.csv" download>Recursos CSV</a><a href="imagenes.csv" download>PNG CSV</a><a href="catalogo.json" download>Catálogo JSON</a><a href="resumen.json">Resumen y límites</a></nav>
<section class="filters" aria-label="Filtros"><label>Juego<select id="game"><option value="">Todos</option><option value="fe7">FE7</option><option value="fe8">FE8</option></select></label>
<label>ROM<select id="variant"></select></label><label>Paleta de referencia<select id="palette"></select></label><label>Buscar ID, variante o hash<input id="search" type="search" maxlength="256" placeholder="0x80, fe8-001, SHA-256…"></label>
<label class="check"><input id="transparent" type="checkbox">Mostrar transparentes</label><button id="reset" type="button">Restablecer</button></section>
<p id="count" role="status" aria-live="polite"></p><p id="empty" hidden>Sin coincidencias.</p><section id="cards" aria-label="Recursos únicos"></section>
<nav aria-label="Páginas"><button id="previous" type="button">Anterior</button><button id="next" type="button">Siguiente</button></nav>
<p>Los rangos incluidos no certifican la capacidad total de las tablas ni el uso de cada clase en una partida.</p><noscript>Los CSV y JSON conservan todas las procedencias.</noscript>
</main><script id="movement-data" type="application/json">{payload}</script><script>{SCRIPT}</script></body></html>""".encode()
