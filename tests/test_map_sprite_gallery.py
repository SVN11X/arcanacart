"""Exercise the generated offline gallery without requiring a browser or server."""

import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_map_sprite_catalog import make_packet

from arcanacart import map_sprite_catalog, map_sprite_gallery

HARNESS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const request=JSON.parse(fs.readFileSync(0,'utf8')),data=request.data;
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.handlers={};this.value='';this.checked=false;this.open=false;this.hidden=false;}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 addEventListener(name,fn){this.handlers[name]=fn;}
 fire(name){if(this.handlers[name])this.handlers[name]();}
}
const visible=data.render_sets.find(s=>s.visible),origin=data.occurrences.find(o=>o.render_id===visible.render_id);
if(request.case==='pagination'){
 data.render_sets=Array.from({length:49},(_,i)=>({...visible,render_id:String(i).padStart(64,'0')}));
 data.occurrences=data.render_sets.map((s,i)=>({...origin,render_id:s.render_id,sprite_id:i,sprite_id_hex:'0x'+i.toString(16)}));
}
if(request.case==='lazy'){
 data.render_sets=[visible];data.occurrences=Array.from({length:205},(_,i)=>({...origin,sprite_id:i,sprite_id_hex:'0x'+i.toString(16)}));
}
const nodes={};function get(id){return nodes[id]||(nodes[id]=new Element('div'));}
get('sprite-data').textContent=JSON.stringify(data);
const context={document:{getElementById:get,createElement:tag=>new Element(tag)}};
vm.createContext(context);vm.runInContext(request.script,context);
if(request.case==='filters'){
 const fn=context.matchingSets;
 assert.equal(fn(data,'fe7','fe8-001','','',true).length,0);
 assert.equal(fn(data,'fe7','','','fe8-001',true).length,0);
 assert.equal(fn(data,'','','16x32','',true).length,1);
 assert.equal(fn(data,'','','','0x01',true)[0].origins.length,2);
 assert.equal(fn(data,'','','','1',true).length,1);
 assert.equal(fn(data,'','','','',false).length,2);
 assert.equal(fn(data,'','','','',true).length,3);
 assert.equal(fn(data,'','','','0xFF',true).length,0);
}
if(request.case==='controls'){
 assert.equal(get('cards').children.length,2);
 assert.match(get('count').textContent,/2 hojas distintas · 4 apariciones/);
 const frames=get('cards').children[0].children.find(n=>n.className==='frames');
 assert.equal(frames.children.length,3);const before=frames.children[0].children[0].src;
 get('palette').value='enemy';get('palette').fire('change');
 const after=get('cards').children[0].children.find(n=>n.className==='frames').children[0].children[0].src;
 assert.notEqual(before,after);
 get('variant').value='fe8-001';get('game').value='fe7';get('game').fire('change');
 assert.equal(get('variant').value,'');assert.equal(get('variant').children.length,2);
 assert.match(get('count').textContent,/2 hojas distintas · 2 apariciones/);
 get('search').value='fe8-001';get('search').fire('input');assert.equal(get('cards').children.length,0);
 get('reset').fire('click');assert.equal(get('palette').value,'player');
 get('transparent').checked=true;get('transparent').fire('change');assert.equal(get('cards').children.length,3);
}
if(request.case==='pagination'){
 assert.equal(get('cards').children.length,48);assert.equal(get('next').disabled,false);
 get('next').fire('click');assert.equal(get('cards').children.length,1);
 assert.match(get('count').textContent,/Página 2 de 2/);
 get('search').value='0x00';get('search').fire('input');assert.equal(get('cards').children.length,1);
 get('search').value='no such origin';get('search').fire('input');assert.equal(get('empty').hidden,false);
 get('reset').fire('click');assert.equal(get('cards').children.length,48);
}
if(request.case==='lazy'){
 const box=get('cards').children[0].children.find(n=>n.tagName==='details');
 const list=box.children.find(n=>n.tagName==='ol'),more=box.children.find(n=>n.tagName==='button');
 assert.equal(list.children.length,0);box.open=true;box.fire('toggle');assert.equal(list.children.length,100);
 more.fire('click');assert.equal(list.children.length,200);more.fire('click');assert.equal(list.children.length,205);
 assert.equal(more.hidden,true);box.open=false;box.fire('toggle');box.open=true;box.fire('toggle');
 assert.equal(list.children.length,205);
}
process.stdout.write('ok');
"""


class MapSpriteGallery(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="arcana galeria sprites ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source, definitions, _, _ = make_packet(self.root)
        self.out = self.root / "catalogo"
        map_sprite_catalog.extract_sprites(source, self.out, definitions)
        self.data = json.loads((self.out / "catalogo.json").read_bytes())

    def node_case(self, name):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is optional for gallery development tests")
        result = subprocess.run(
            [node, "-e", HARNESS],
            text=True,
            capture_output=True,
            check=False,
            input=json.dumps({"case": name, "script": map_sprite_gallery.SCRIPT, "data": self.data}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok")

    def test_game_variant_size_and_numeric_id_match_the_same_origin(self):
        self.node_case("filters")

    def test_palette_transparency_and_variant_controls(self):
        self.node_case("controls")

    def test_pagination_search_empty_state_and_reset(self):
        self.node_case("pagination")

    def test_every_origin_is_accessible_with_lazy_details(self):
        self.node_case("lazy")

    def test_offline_references_escaping_and_csp(self):
        self.data["profiles"][0]["variant"] = '</script><img src=x onerror="bad()">'
        page = map_sprite_gallery.gallery(self.data).decode()
        embedded = re.search(r'<script id="sprite-data" type="application/json">(.*?)</script>', page, re.S)[
            1
        ]
        self.assertEqual(json.loads(embedded)["profiles"], self.data["profiles"])
        self.assertNotIn("</script>", embedded)
        self.assertNotIn("<img src=x", page)
        expected = base64.b64encode(hashlib.sha256(map_sprite_gallery.SCRIPT.encode()).digest()).decode()
        self.assertIn("script-src 'sha256-" + expected + "'", page)
        self.assertNotIn("fetch(", map_sprite_gallery.SCRIPT)
        referenced = set(re.findall(r"getElementById\('([^']+)'\)", map_sprite_gallery.SCRIPT))
        self.assertTrue(referenced <= set(re.findall(r'\bid="([^"]+)"', page)))
        for path in re.findall(r'href="([^"]+)"', page):
            self.assertTrue((self.out / path).is_file())


if __name__ == "__main__":
    unittest.main()
