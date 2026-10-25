"""Offline movement resource gallery controls and complete origin access."""

import base64
import copy
import hashlib
import json
import re
import shutil
import subprocess
import unittest

from test_moving_sprite_catalog import make_sources

from arcanacart import moving_sprite_catalog as mc
from arcanacart import moving_sprite_gallery as mg

HARNESS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const request=JSON.parse(fs.readFileSync(0,'utf8')),data=request.data,base=data.resources[0],origin=data.occurrences[0];
class Element{constructor(tag){this.tagName=tag;this.children=[];this.handlers={};this.value='';this.checked=false;this.open=false;this.hidden=false;}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[...nodes];}
 addEventListener(name,fn){this.handlers[name]=fn;}fire(name){if(this.handlers[name])this.handlers[name]();}}
if(request.case==='pagination'){
 data.resources=Array.from({length:49},(_,i)=>({...base,resource_id:String(i).padStart(64,'0')}));
 data.occurrences=data.resources.map((r,i)=>({...origin,resource_id:r.resource_id,class_id:i+1,class_id_hex:'0x'+(i+1).toString(16)}));
}
if(request.case==='lazy'){
 data.resources=[base];data.occurrences=Array.from({length:205},(_,i)=>({...origin,class_id:i+1,class_id_hex:'0x'+(i+1).toString(16)}));
}
const nodes={};function get(id){return nodes[id]||(nodes[id]=new Element('div'));}get('movement-data').textContent=JSON.stringify(data);
const context={document:{getElementById:get,createElement:tag=>new Element(tag)}};vm.createContext(context);vm.runInContext(request.script,context);
if(request.case==='filters'){
 const fn=context.matchingResources;
 assert.equal(fn(data,'fe7','fe8-001','',true).length,0);
 assert.equal(fn(data,'fe8','','fe7-001',true).length,0);
 assert.equal(fn(data,'','','0x01',true)[0].origins.length,2);
 assert.equal(fn(data,'','','5',true).length,1);
 assert.equal(fn(data,'','','0xFF',true).length,0);
 assert.equal(fn(data,'','','',false).length,2);
 assert.equal(fn(data,'','','',true).length,3);
}
if(request.case==='controls'){
 assert.equal(get('cards').children.length,2);assert.match(get('count').textContent,/2 recursos distintos · 6 apariciones/);
 const sheet=card=>card.children.find(c=>c.className==='sheet').children[0];
 const before=sheet(get('cards').children[0]).src;get('palette').value='enemy';get('palette').fire('change');
 assert.notEqual(sheet(get('cards').children[0]).src,before);
 get('variant').value='fe8-001';get('game').value='fe7';get('game').fire('change');
 assert.equal(get('variant').value,'');assert.equal(get('variant').children.length,2);
 assert.match(get('count').textContent,/1 recursos distintos · 1 apariciones/);
 get('search').value='fe8-001';get('search').fire('input');assert.equal(get('cards').children.length,0);
 get('reset').fire('click');assert.equal(get('palette').value,'player');
 get('transparent').checked=true;get('transparent').fire('change');assert.equal(get('cards').children.length,3);
}
if(request.case==='pagination'){
 assert.equal(get('cards').children.length,48);get('next').fire('click');assert.equal(get('cards').children.length,1);
 assert.match(get('count').textContent,/Página 2 de 2/);get('search').value='0x01';get('search').fire('input');assert.equal(get('cards').children.length,1);
 get('search').value='no such origin';get('search').fire('input');assert.equal(get('empty').hidden,false);
 get('reset').fire('click');assert.equal(get('cards').children.length,48);
}
if(request.case==='lazy'){
 const box=get('cards').children[0].children.find(c=>c.tagName==='details'),list=box.children.find(c=>c.tagName==='ol'),more=box.children.find(c=>c.tagName==='button');
 assert.equal(list.children.length,0);box.open=true;box.fire('toggle');assert.equal(list.children.length,100);
 more.fire('click');assert.equal(list.children.length,200);more.fire('click');assert.equal(list.children.length,205);assert.equal(more.hidden,true);
 assert.equal(list.children[0].children.filter(c=>c.tagName==='a').length,6);
 box.open=false;box.fire('toggle');box.open=true;box.fire('toggle');assert.equal(list.children.length,205);
}
process.stdout.write('ok');
"""


class MovingSpriteGallery(unittest.TestCase):
    def setUp(self):
        root, source, palettes, definitions, _, _ = make_sources(self)
        self.out = root / "galeria"
        mc.extract_movement(source, palettes, self.out, definitions)
        self.data = json.loads((self.out / "catalogo.json").read_bytes())
        # UI-only logical rows cover raw/AP combinations shared across games.
        base = self.data["resources"][0]
        first = self.data["occurrences"][0]
        profile = {**self.data["profiles"][0], "game": "fe7", "variant_id": "fe7-001", "variant": "001-UI"}
        self.data["profiles"].append(profile)
        self.data["occurrences"].append(
            {**first, "game": "fe7", "variant_id": "fe7-001", "variant": "001-UI", "class_id": 7}
        )
        preview = copy.deepcopy(self.data["previews"][base["raw_sha256"]])
        preview.update(visible=False, raw_sha256="b" * 64)
        self.data["previews"]["b" * 64] = preview
        self.data["resources"].append({**base, "resource_id": "b" * 64, "raw_sha256": "b" * 64})
        self.data["occurrences"].append(
            {**first, "resource_id": "b" * 64, "raw_sha256": "b" * 64, "class_id": 9}
        )
        self.data["resources"].append({**base, "resource_id": "c" * 64})
        self.data["occurrences"].append(
            {**first, "variant_id": "fe8-001", "resource_id": "c" * 64, "class_id": 5}
        )

    def node_case(self, case):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is optional for gallery development tests")
        result = subprocess.run(
            [node, "-e", HARNESS],
            input=json.dumps({"case": case, "script": mg.SCRIPT, "data": self.data}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok")

    def test_filters_correlate_game_variant_id_and_hash_in_one_origin(self):
        self.node_case("filters")

    def test_palette_transparency_reset_and_game_variant_controls(self):
        self.node_case("controls")

    def test_pagination_and_empty_state(self):
        self.node_case("pagination")

    def test_every_origin_and_resource_link_remains_accessible(self):
        self.node_case("lazy")

    def test_html_is_offline_escaped_and_honest_about_tile_previews(self):
        self.data["profiles"][0]["variant"] = '</script><img src=x onerror="bad()">'
        text = mg.gallery(self.data).decode()
        embedded = re.search(
            r'<script id="movement-data" type="application/json">(.*?)</script>', text, re.S
        )[1]
        self.assertEqual(json.loads(embedded)["profiles"], self.data["profiles"])
        self.assertNotIn("</script>", embedded)
        self.assertIn("composición de fotogramas AP", text)
        self.assertIn("paletas de referencia", text)
        expected = base64.b64encode(hashlib.sha256(mg.SCRIPT.encode()).digest()).decode()
        self.assertIn("script-src 'sha256-" + expected, text)
        self.assertNotIn("fetch(", mg.SCRIPT)
        referenced = set(re.findall(r"getElementById\('([^']+)'\)", mg.SCRIPT))
        self.assertTrue(referenced <= set(re.findall(r'\bid="([^"]+)"', text)))
        for link in re.findall(r'href="([^"]+)"', text):
            self.assertTrue((self.out / link).is_file())


if __name__ == "__main__":
    unittest.main()
