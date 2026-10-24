"""Offline filtering and DOM behavior; Node is optional for development tests."""

import base64
import hashlib
import json
import re
import shutil
import subprocess
import unittest

from arcanacart.icon_catalog_gallery import SCRIPT, gallery

HARNESS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const request=JSON.parse(fs.readFileSync(0,'utf8'));
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.handlers={};this.value='';this.checked=false;this.open=false;this.hidden=false;}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 addEventListener(name,callback){this.handlers[name]=callback;}
 fire(name){if(this.handlers[name])this.handlers[name]();}
}
const nodes={};function get(id){return nodes[id]||(nodes[id]=new Element('div'));}
function origin(game='fe8',id=0,variant='fe8-001',name='Variante'){
 return {game,icon_id:id,icon_id_hex:'0x'+id.toString(16).padStart(2,'0'),variant_id:variant,variant:name,
 rom_sha256:'b'.repeat(64),air_sha256:'c'.repeat(64),source_sha256:'d'.repeat(64),palette_sha256:'e'.repeat(64),
 source_offset:id*128,palette_offset:10000,source_png:'origen.png',raw_file:'raw/source.bin',palette_file:'paletas/source.bin'};
}
function image(id,origins,visible=true){return {png_sha256:id.toString(16).padStart(64,'0'),file:'imagenes/'+id+'.png',visible,origins};}
let data={variants:[{game:'fe8',variant_id:'fe8-001',variant:'Variante'}],images:[]};
if(request.case==='pagination')data.images=Array.from({length:65},(_,i)=>image(i,[origin('fe8',i)]));
else if(request.case==='lazy')data.images=[image(1,Array.from({length:201},(_,i)=>origin('fe8',i)))];
else {
 data.variants=[{game:'fe7',variant_id:'fe7-001',variant:'Only seven'},
                {game:'fe8',variant_id:'fe8-001',variant:'Only eight'}];
 data.images=[image(1,[origin('fe7',0,'fe7-001','Only seven'),origin('fe8',1,'fe8-001','Only eight')]),
              image(2,[origin('fe8',2)],false)];
}
get('catalog-data').textContent=JSON.stringify(data);
const context={document:{getElementById:get,createElement:tag=>new Element(tag)}};
vm.createContext(context);vm.runInContext(request.script,context);
if(request.case==='correlation'){
 const fn=context.matchingImages;
 assert.equal(fn(data.images,'fe7','fe8-001','',true).length,0);
 assert.equal(fn(data.images,'fe7','','only eight',true).length,0);
 assert.equal(fn(data.images,'fe7','','0x01',true).length,0);
 assert.equal(fn(data.images,'fe8','','1',true)[0].origins.length,1);
 assert.equal(fn(data.images,'','','',false).length,1);
 assert.equal(fn(data.images,'','','',true).length,2);
 assert.equal(data.images[0].origins.length,2);
}
if(request.case==='pagination'){
 assert.equal(get('cards').children.length,64);assert.equal(get('previous').disabled,true);
 assert.equal(get('next').disabled,false);get('next').fire('click');
 assert.equal(get('cards').children.length,1);assert.match(get('count').textContent,/Página 2 de 2/);
 get('search').value='0x00';get('search').fire('input');
 assert.equal(get('cards').children.length,1);assert.equal(get('next').disabled,true);
 get('search').value='no matching origin';get('search').fire('input');
 assert.equal(get('cards').children.length,0);assert.equal(get('empty').hidden,false);
 get('reset').fire('click');assert.equal(get('cards').children.length,64);
}
if(request.case==='controls'){
 get('variant').value='fe8-001';get('game').value='fe7';get('game').fire('change');
 assert.equal(get('variant').value,'');assert.equal(get('variant').children.length,2);
 assert.match(get('count').textContent,/1 icono · 1 aparición/);
 get('search').value='only eight';get('search').fire('input');assert.equal(get('cards').children.length,0);
 get('reset').fire('click');assert.match(get('count').textContent,/1 icono · 2 apariciones/);
 get('transparent').checked=true;get('transparent').fire('change');assert.equal(get('cards').children.length,2);
}
if(request.case==='lazy'){
 const details=get('cards').children[0].children.find(n=>n.tagName==='details');
 const list=details.children.find(n=>n.tagName==='ol'),more=details.children.find(n=>n.tagName==='button');
 assert.equal(list.children.length,0);details.open=true;details.fire('toggle');assert.equal(list.children.length,100);
 more.fire('click');assert.equal(list.children.length,200);more.fire('click');assert.equal(list.children.length,201);
 assert.equal(more.hidden,true);details.open=false;details.fire('toggle');details.open=true;details.fire('toggle');
 assert.equal(list.children.length,201);
}
process.stdout.write('ok');
"""


class CatalogGallery(unittest.TestCase):
    def node_case(self, name):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; required only for gallery development tests")
        result = subprocess.run(
            [node, "-e", HARNESS],
            input=json.dumps({"script": SCRIPT, "case": name}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok")

    def test_filters_use_the_same_origin_for_game_variant_and_search(self):
        self.node_case("correlation")

    def test_pagination_search_empty_state_and_reset(self):
        self.node_case("pagination")

    def test_controls_keep_variants_consistent_with_game(self):
        self.node_case("controls")

    def test_origin_details_progressively_expose_every_origin(self):
        self.node_case("lazy")

    def test_embedded_data_is_escaped_and_csp_matches_script(self):
        catalog = {
            "summary": {"unique_images": 1, "icon_occurrences": 1, "variants": 1},
            "variants": [{"variant": '</script><img src=x onerror=bad()> & "'}],
            "images": [],
        }
        page = gallery(catalog).decode()
        embedded = re.search(r'<script id="catalog-data" type="application/json">(.*?)</script>', page, re.S)[
            1
        ]
        self.assertEqual(json.loads(embedded)["variants"], catalog["variants"])
        self.assertNotIn("</script>", embedded)
        self.assertNotIn("<img src=x", page)
        digest = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
        self.assertIn("script-src 'sha256-" + digest + "'", page)
        self.assertNotIn("fetch(", SCRIPT)
        ids = set(re.findall(r'\bid="([^"]+)"', page))
        referenced = set(re.findall(r"getElementById\('([^']+)'\)", SCRIPT))
        self.assertTrue(referenced <= ids)


if __name__ == "__main__":
    unittest.main()
