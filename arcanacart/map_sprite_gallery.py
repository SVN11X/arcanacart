"""Offline standing sprite catalog: palette selection and origin-correlated filters."""

from __future__ import annotations

import base64
import hashlib
import json

SCRIPT = r"""'use strict';
function matchingSets(data,game,variant,size,term,showTransparent){
 term=term.trim().toLowerCase();const id=/^(?:0x[0-9a-f]+|[0-9]+)$/.test(term)?Number(term):null;
 const groups=new Map();
 for(const o of data.occurrences){
  if((game&&o.game!==game)||(variant&&o.variant_id!==variant))continue;
  if(term&&(id!==null?o.sprite_id!==id:![o.variant_id,o.variant,o.rom_sha256,o.air_sha256,
   o.raw_sha256,o.stored_sha256].some(s=>String(s||'').toLowerCase().includes(term))))continue;
  if(!groups.has(o.render_id))groups.set(o.render_id,[]);groups.get(o.render_id).push(o);
 }
 return data.render_sets.filter(s=>groups.has(s.render_id)&&(showTransparent||s.visible)&&
  (!size||size===s.width+'x'+s.height)).map(sheet=>({sheet,origins:groups.get(sheet.render_id)}));
}
const data=JSON.parse(document.getElementById('sprite-data').textContent);
const game=document.getElementById('game'),variant=document.getElementById('variant');
const size=document.getElementById('size'),palette=document.getElementById('palette');
const search=document.getElementById('search'),transparent=document.getElementById('transparent');
const cards=document.getElementById('cards'),count=document.getElementById('count');
const previous=document.getElementById('previous'),next=document.getElementById('next');
let filtered=[],page=0;const pageSize=48;
function element(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;}
function download(label,path){const a=element('a',label);a.href=path;a.download='';return a;}
function variants(){const old=variant.value;variant.replaceChildren();
 const all=element('option','Todas las ROM');all.value='';variant.append(all);
 for(const p of data.profiles.filter(p=>!game.value||p.game===game.value)){
  const option=element('option',p.game.toUpperCase()+' · '+p.variant_id+' · '+p.variant);
  option.value=p.variant_id;variant.append(option);}
 variant.value=data.profiles.some(p=>p.variant_id===old&&(!game.value||p.game===game.value))?old:'';
}
function details(origins,rendering){
 const box=element('details'),list=element('ol'),status=element('p'),more=element('button','Mostrar más');
 box.append(element('summary',origins.length+' procedencias coincidentes'),list,status,more);
 more.type='button';let cursor=0;
 function append(){const end=Math.min(cursor+100,origins.length);
  for(const o of origins.slice(cursor,end)){
   const item=element('li');item.append(element('p',o.game.toUpperCase()+' · '+o.variant_id+' · '+o.variant+
    ' · ID '+o.sprite_id_hex));
   item.append(element('p','Offset ROM: 0x'+o.source_offset.toString(16).toUpperCase()+
    ' · Registro: 0x'+o.entry_offset.toString(16).toUpperCase()));
   item.append(download('Raw 4bpp',o.raw_file),download('LZ10 original',o.compressed_file),
    download('Paleta RGB555',rendering.palette_file),download('Definición',o.definition));
   item.append(element('p','ROM SHA-256: '+o.rom_sha256),element('p','AIR SHA-256: '+(o.air_sha256||'No incluido para esta base')),
    element('p','4bpp SHA-256: '+o.raw_sha256),element('p','LZ10 SHA-256: '+o.stored_sha256),
    element('p','Paleta SHA-256: '+rendering.palette_sha256));list.append(item);
  }
  cursor=end;status.textContent=cursor+' de '+origins.length+' procedencias';more.hidden=cursor>=origins.length;
 }
 box.addEventListener('toggle',()=>{if(box.open&&cursor===0)append();});more.addEventListener('click',append);return box;
}
function render(){const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
 page=Math.max(0,Math.min(page,pages-1));cards.replaceChildren();
 for(const row of filtered.slice(page*pageSize,(page+1)*pageSize)){
  const s=row.sheet,r=s.renderings[palette.value],card=element('article'),frames=element('div');frames.className='frames';
  card.append(element('h2','Hoja '+s.raw_sha256.slice(0,12)),element('p',s.width+' × '+s.height+' píxeles por fotograma'));
  r.frames.forEach((key,index)=>{const asset=data.assets[key],figure=element('figure'),png=element('img');
   png.src=asset.file;png.alt='Fotograma '+(index+1)+' de la hoja '+s.raw_sha256.slice(0,12);png.loading='lazy';
   png.width=s.width*3;png.height=s.height*3;
   figure.append(png,element('figcaption','Fotograma '+(index+1)),download('PNG',asset.file));frames.append(figure);});
  card.append(frames,download('Descargar hoja de tres fotogramas',data.assets[r.sheet].file),
   element('p',row.origins.length+' apariciones coincidentes'));
  if(!s.visible)card.append(element('p','Hoja totalmente transparente'));
  card.append(details(row.origins,r));cards.append(card);
 }
 const occurrences=filtered.reduce((n,r)=>n+r.origins.length,0);
 count.textContent=filtered.length+' hojas distintas · '+occurrences+' apariciones · Página '+(page+1)+' de '+pages;
 previous.disabled=page===0;next.disabled=page+1>=pages;document.getElementById('empty').hidden=filtered.length!==0;
}
function filter(){page=0;filtered=matchingSets(data,game.value,variant.value,size.value,search.value,transparent.checked);render();}
game.addEventListener('change',()=>{variants();filter();});variant.addEventListener('change',filter);
size.addEventListener('change',filter);search.addEventListener('input',filter);
transparent.addEventListener('change',filter);palette.addEventListener('change',render);
previous.addEventListener('click',()=>{page--;render();});next.addEventListener('click',()=>{page++;render();});
document.getElementById('reset').addEventListener('click',()=>{
 game.value='';variant.value='';size.value='';search.value='';transparent.checked=false;palette.value='player';variants();filter();});
for(const [key,label] of Object.entries(data.palette_roles)){const option=element('option',label);option.value=key;palette.append(option);}
palette.value='player';variants();filter();
"""


def gallery(catalog: dict) -> bytes:
    summary = catalog["summary"]
    payload = {
        key: catalog[key] for key in ("profiles", "occurrences", "render_sets", "assets", "palette_roles")
    }
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    csp = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'sha256-{csp}'; base-uri 'none'; form-action 'none'">
<title>ArcanaCart · Sprites de mapa en reposo</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f4f8;color:#1b293c;font:16px/1.5 system-ui}}
main{{max-width:1500px;padding:24px;margin:auto}}h1{{margin-bottom:8px}}h2{{font:15px monospace;overflow-wrap:anywhere}}
nav,.filters{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:24px 0}}
label{{display:grid;gap:6px}}select,input,button{{font:inherit;padding:10px;border:1px solid #66788f;border-radius:6px}}
select{{max-width:340px}}input[type=search]{{width:280px;max-width:100%}}
.check{{display:flex;align-items:center;gap:8px}}input[type=checkbox]{{width:22px;height:22px}}
a{{color:#204f9c}}button,summary{{cursor:pointer}}:focus-visible{{outline:3px solid #315fa8;outline-offset:3px}}
#cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}}
article{{background:white;border:1px solid #ccd5e1;border-radius:10px;padding:18px;min-width:0}}
.frames{{display:flex;gap:8px;overflow-x:auto;margin:16px 0;padding-bottom:8px}}figure{{margin:0;flex:none}}
figure img{{display:block;image-rendering:pixelated;background:repeating-conic-gradient(#dde4ef 0% 25%,#f6f8fb 0% 50%) 0/12px 12px}}
figcaption,figure a{{font-size:12px}}details{{margin-top:16px}}details p{{font:12px/1.5 monospace;overflow-wrap:anywhere}}
details a{{display:block;margin:6px 0}}details li{{margin-bottom:20px}}ol{{padding-left:24px}}[hidden]{{display:none!important}}
@media(max-width:600px){{main{{padding:16px}}#cards{{grid-template-columns:minmax(0,1fr)}}.filters label,.filters select{{width:100%;max-width:100%}}}}
</style></head><body><main><p>ARCANACART</p><h1>Sprites de mapa en reposo</h1>
<p>{summary["render_sets"]} hojas distintas · {summary["sheet_occurrences"]} apariciones · {summary["roms"]} ROM</p>
<p>Tres fotogramas completos por hoja y siete paletas del cargador revisado. Algunas paletas se usan en contextos específicos del juego.</p>
<p>La apariencia dentro del juego y los tiempos de animación siguen pendientes de contraste.</p>
<nav aria-label="Archivos del catálogo"><a href="ocurrencias.csv" download>Procedencias CSV</a>
<a href="imagenes.csv" download>Imágenes CSV</a><a href="catalogo.json" download>Catálogo JSON</a>
<a href="resumen.json">Resumen y límites</a></nav>
<section class="filters" aria-label="Filtros"><label>Juego<select id="game">
<option value="">Todos los juegos</option><option value="fe7">FE7</option><option value="fe8">FE8</option></select></label>
<label>ROM<select id="variant"></select></label><label>Tamaño por fotograma<select id="size">
<option value="">Todos</option><option value="16x16">16 × 16</option><option value="16x32">16 × 32</option>
<option value="32x32">32 × 32</option></select></label><label>Paleta<select id="palette"></select></label>
<label>Buscar ID, variante o hash<input id="search" type="search" maxlength="256" placeholder="0x80, fe8-001, SHA-256…"></label>
<label class="check"><input id="transparent" type="checkbox">Mostrar transparentes</label>
<button id="reset" type="button">Restablecer</button></section>
<p id="count" role="status" aria-live="polite"></p><p id="empty" hidden>Sin coincidencias.</p>
<section id="cards" aria-label="Hojas únicas"></section><nav aria-label="Páginas">
<button id="previous" type="button">Anterior</button><button id="next" type="button">Siguiente</button></nav>
<p>Los rangos exportados no demuestran la capacidad total ni la totalidad de recursos del juego.</p>
<noscript>Activa JavaScript para usar los filtros. Los CSV y JSON conservan todas las procedencias.</noscript>
</main><script id="sprite-data" type="application/json">{embedded}</script><script>{SCRIPT}</script></body></html>""".encode()
