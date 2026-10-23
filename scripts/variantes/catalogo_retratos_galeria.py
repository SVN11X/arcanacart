"""Portable offline gallery for a consolidated portrait catalog."""

import base64
import hashlib
import html
import json

SCRIPT = r"""
'use strict';
const data=JSON.parse(document.getElementById('catalog-data').textContent);
const labels={portrait:'Retrato',miniature:'Miniatura',classcard:'Tarjeta de clase'};
const order={portrait:0,miniature:1,classcard:2},size=36;
const assets=data.images.map(a=>({...a,origins:a.origins.map(o=>({...o,
 search:[o.variant_id,o.variant,o.game,o.face_id_hex,o.face_id].join(' ').toLowerCase()}))}));
assets.sort((a,b)=>order[a.kinds[0]]-order[b.kinds[0]]||a.origins[0].face_id-b.origins[0].face_id||a.png_sha256.localeCompare(b.png_sha256));
const game=document.getElementById('game'),kind=document.getElementById('kind');
const variant=document.getElementById('variant'),search=document.getElementById('search');
const transparent=document.getElementById('transparent'),cards=document.getElementById('cards');
const prev=document.getElementById('prev'),next=document.getElementById('next');
const count=document.getElementById('count'),pageLabel=document.getElementById('page');
const variants=[...new Map(assets.flatMap(a=>a.origins.map(o=>[o.variant_id,o]))).values()];
variants.sort((a,b)=>a.variant_id.localeCompare(b.variant_id));
let page=0,matched=[],timer;
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function fillVariants(){const old=variant.value;variant.replaceChildren(new Option('Todas las variantes',''));
 for(const o of variants){if(!game.value||o.game===game.value)variant.add(new Option(o.game.toUpperCase()+' / '+o.variant,o.variant_id));}
 if([...variant.options].some(o=>o.value===old))variant.value=old;}
function render(){const pages=Math.max(1,Math.ceil(matched.length/size));page=Math.min(page,pages-1);cards.replaceChildren();
 for(const {asset:a,origins} of matched.slice(page*size,(page+1)*size)){
  const card=element('article'),title=element('h2',a.kinds.map(k=>labels[k]).join(' / '));card.append(title);
  const img=element('img');img.src=a.file;img.alt=labels[a.kinds[0]]+' de '+origins[0].game.toUpperCase()+', ID '+origins[0].face_id_hex;img.loading='lazy';
  const picture=element('a');picture.href=a.file;picture.download='';picture.append(img);card.append(picture);
  card.append(element('p',new Set(origins.map(o=>o.variant_id)).size+' variantes · '+origins.length+' apariciones','muted'));
  if(!a.visible)card.append(element('p','Imagen totalmente transparente','muted'));
  const download=element('a','Descargar PNG · '+a.width+' × '+a.height);download.href=a.file;download.download='';card.append(download);
  const details=element('details'),summary=element('summary','Ver variantes e IDs ('+origins.length+')');details.append(summary);
  details.addEventListener('toggle',()=>{if(!details.open||details.dataset.loaded)return;details.dataset.loaded='yes';const list=element('ul');
   for(const o of origins){const li=element('li'),line=element('strong',o.game.toUpperCase()+' / '+o.variant_id+' / '+o.face_id_hex);li.append(line);
    li.append(element('div',o.variant),element('div',labels[o.kind]+' · ROM 0x'+o.source_offset.toString(16).toUpperCase()));
    const palette=element('a','Descargar paleta RGB555');palette.href='paletas/'+o.palette_sha256+'.bin';palette.download='';li.append(palette);list.append(li);}
   details.append(list,element('p','SHA-256 PNG: '+a.png_sha256,'hash'));});card.append(details);cards.append(card);
 }
 count.textContent=matched.length.toLocaleString('es-CL')+' imágenes coincidentes';
 pageLabel.textContent='Página '+(page+1)+' de '+pages;prev.disabled=page===0;next.disabled=page+1>=pages;
 document.getElementById('empty').hidden=matched.length!==0;
}
function filter(){page=0;const q=search.value.trim().toLowerCase();matched=[];
 for(const a of assets){if(!a.visible&&!transparent.checked)continue;const hashMatch=q&&a.png_sha256.includes(q);
  const origins=a.origins.filter(o=>(!game.value||o.game===game.value)&&(!kind.value||o.kind===kind.value)&&(!variant.value||o.variant_id===variant.value)&&(!q||hashMatch||o.search.includes(q)));
  if(origins.length)matched.push({asset:a,origins});}render();}
game.addEventListener('change',()=>{fillVariants();filter();});
for(const e of [kind,variant,transparent])e.addEventListener('change',filter);
search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(filter,120);});
prev.addEventListener('click',()=>{page--;render();document.getElementById('results').scrollIntoView({block:'start'});});
next.addEventListener('click',()=>{page++;render();document.getElementById('results').scrollIntoView({block:'start'});});
document.getElementById('reset').addEventListener('click',()=>{game.value='';kind.value='';search.value='';transparent.checked=false;fillVariants();variant.value='';filter();});
fillVariants();filter();
"""


def render_gallery(catalog: dict) -> str:
    stats = catalog["summary"]
    token = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    payload = json.dumps({"images": catalog["images"]}, ensure_ascii=True, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = html.escape("ArcanaCart · Catálogo de retratos")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'sha256-{token}'; base-uri 'none'; form-action 'none'">
<title>{title}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f4fa;color:#172238;font:16px/1.5 system-ui}}
main{{max-width:1400px;margin:auto;padding:28px}}h1{{font-size:clamp(1.8rem,4vw,2.8rem);margin:0}}h2{{font-size:1.1rem;margin:0 0 12px}}
a{{color:#244ea3}}.muted{{color:#485770}}.eyebrow{{letter-spacing:.12em;font-size:.8rem;color:#405677}}.stats{{display:flex;flex-wrap:wrap;gap:14px;margin:24px 0}}
.stats div{{background:white;padding:16px 22px;border:1px solid #ccd4e3;border-radius:12px}}.stats strong{{display:block;font-size:1.7rem;color:#173f8c}}
.filters{{display:flex;flex-wrap:wrap;gap:14px;align-items:end;padding:18px;background:white;border-radius:12px;margin:24px 0}}
label{{display:grid;gap:5px;min-width:0}}input,select,button{{font:inherit;min-height:44px;border:1px solid #7383a0;border-radius:6px;background:white;color:inherit;padding:8px 12px}}
select{{max-width:300px}}input[type=search]{{width:250px}}label.check{{display:flex;align-items:center;gap:8px}}input[type=checkbox]{{min-height:22px;width:22px}}
button{{cursor:pointer}}button:disabled{{cursor:default;color:#59677d;background:#e7ecf4}}:focus-visible{{outline:3px solid #3766bb;outline-offset:3px}}
#cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px}}article{{min-width:0;background:white;padding:18px;border:1px solid #ccd4e3;border-radius:12px}}
article img{{display:block;width:100%;height:180px;object-fit:contain;image-rendering:pixelated;background:repeating-conic-gradient(#e8eaf2 0% 25%,#dce1ec 0% 50%) 0/16px 16px}}
details{{margin-top:14px}}summary{{cursor:pointer}}details ul{{padding-left:20px;max-height:320px;overflow:auto}}details li{{margin:0 0 14px;overflow-wrap:anywhere;font-size:.85rem}}
.hash{{font:12px/1.5 monospace;overflow-wrap:anywhere}}.pagination{{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:24px 0}}[hidden]{{display:none!important}}
@media(max-width:600px){{main{{padding:16px}}.filters{{padding:14px}}label,input[type=search],select{{width:100%;max-width:none}}label.check{{width:auto}}}}
</style></head><body><main><p class="eyebrow">ARCANACART / RECURSOS CONSOLIDADOS</p>
<h1>Catálogo de retratos</h1><p>Cada PNG se guarda una vez. En «Ver variantes e IDs» puedes consultar todas sus apariciones.</p>
<div class="stats"><div><strong>{stats["visible_images"]:,}</strong>imágenes visibles distintas</div>
<div><strong>{stats["component_occurrences"]:,}</strong>apariciones conservadas</div><div><strong>{stats["variants"]}</strong>variantes</div></div>
<p class="muted">Los retratos, miniaturas y tarjetas conservan sus colores. Las imágenes transparentes están disponibles mediante el filtro.
Los nombres de personajes y las animaciones de ojos y boca siguen pendientes.</p>
<p><a href="imagenes.csv" download>Índice de imágenes CSV</a> · <a href="ocurrencias.csv" download>Variantes e IDs CSV</a> ·
<a href="catalogo.json" download>Catálogo JSON con orígenes</a> · <a href="resumen.json">Resumen</a></p>
<section class="filters" aria-label="Filtros del catálogo">
<label>Juego<select id="game"><option value="">Ambos juegos</option><option value="fe7">FE7</option><option value="fe8">FE8</option></select></label>
<label>Tipo<select id="kind"><option value="">Todos los tipos</option><option value="portrait">Retratos</option><option value="miniature">Miniaturas</option><option value="classcard">Tarjetas de clase</option></select></label>
<label>Variante<select id="variant"><option value="">Todas las variantes</option></select></label>
<label>Buscar<input id="search" type="search" placeholder="ID 0x016, variante o hash…"></label>
<label class="check"><input id="transparent" type="checkbox">Mostrar transparentes ({stats["transparent_images"]})</label>
<button id="reset" type="button">Restablecer</button></section>
<section id="results" aria-label="Resultados"><p id="count" role="status" aria-live="polite"></p>
<p id="empty" hidden>No hay imágenes que coincidan con estos filtros.</p><div id="cards"></div></section>
<nav class="pagination" aria-label="Páginas de resultados"><button id="prev" type="button">Anterior</button><span id="page"></span><button id="next" type="button">Siguiente</button></nav>
<noscript><p>Los índices CSV y el catálogo JSON contienen todas las imágenes y sus orígenes. Activa JavaScript para usar los filtros de esta galería.</p></noscript>
</main><script type="application/json" id="catalog-data">{payload}</script><script>{SCRIPT}</script></body></html>"""
