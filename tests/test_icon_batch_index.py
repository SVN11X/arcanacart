"""Portable navigation for existing batches must not change extracted assets."""

import contextlib
import csv
import io
import json
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
from zipfile import ZipFile

import test_icon_variants as fixtures
from arcanacart import icon_variants as iv
from arcanacart.core.io import json_bytes


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs)['href'])


class BatchIndex(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.VariantIcons()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.make_all_unchanged()
        self.fixture.run_review()
        self.fixture.run_extract()
        self.future = self.fixture.out
        payloads = iv._sealed(self.future)
        payloads.pop(iv.STATE)
        payloads.pop('index.html')
        summary = json.loads(payloads['resumen.json'])
        fields = ['variant_id', 'game', 'variant', 'first_id', 'last_id', 'icon_occurrences',
                  'unique_images', 'gallery']
        payloads['galerias.csv'] = iv._csv(summary['results'], fields)
        self.source = self.fixture.root / 'lote-anterior'
        iv._publish(self.source, payloads)
        self.out = self.fixture.root / 'lote-con-indice'

    def rewrite_source(self, edit):
        payloads = iv._sealed(self.source)
        payloads.pop(iv.STATE)
        edit(payloads)
        new_source = self.fixture.root / ('source-' + str(len(list(self.fixture.root.iterdir()))))
        iv._publish(new_source, payloads)
        self.source = new_source

    def test_future_batches_have_relative_csv_and_clickable_root_index(self):
        parser = Links()
        parser.feed((self.future / 'index.html').read_text())
        self.assertIn('fe8-001/index.html', parser.links)
        self.assertIn('fe8-002/index.html', parser.links)
        self.assertTrue(all((self.future / link).is_file() for link in parser.links))
        with (self.future / 'galerias.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([r['gallery'] for r in rows], ['fe8-001/index.html', 'fe8-002/index.html'])
        self.assertTrue(all(r['gallery_original'] for r in rows))

    def test_existing_batch_copy_preserves_all_assets_and_original_folder(self):
        before = {p.relative_to(self.source).as_posix(): p.read_bytes()
                  for p in self.source.rglob('*') if p.is_file()}
        with patch.object(iv, 'load_rom', side_effect=AssertionError('ROM reread')), \
             patch.object(iv, 'extract_icons', side_effect=AssertionError('re-extraction')):
            result = iv.prepare_index(self.source, self.out)
        self.assertFalse(result['icons_exported'])
        self.assertFalse(result['assets_reencoded'])
        self.assertEqual(before, {p.relative_to(self.source).as_posix(): p.read_bytes()
                                  for p in self.source.rglob('*') if p.is_file()})
        for name, raw in before.items():
            if name not in {'galerias.csv', iv.STATE}:
                self.assertEqual((self.out / name).read_bytes(), raw, name)
        self.assertIn('index.html', iv._sealed(self.out))

    def test_relocated_bundle_references_resolve_and_zip_is_portable(self):
        iv.prepare_index(self.source, self.out)
        archive = self.fixture.root / 'portable.zip'
        iv.pack_variants(self.out, archive)
        target = self.fixture.root / 'otra-ubicacion'
        with ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            self.assertTrue(all('\\' not in name for name in z.namelist()))
            z.extractall(target)
        parser = Links()
        parser.feed((target / 'index.html').read_text())
        self.assertTrue(all((target / link).is_file() for link in parser.links))

    def test_missing_gallery_is_not_silently_linked(self):
        self.rewrite_source(lambda p: p.pop('fe8-001/index.html'))
        with self.assertRaisesRegex(ValueError, 'Falta la galería'):
            iv.prepare_index(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_tampered_payload_is_not_resealed_as_a_valid_copy(self):
        file = next((self.source / 'fe8-001/imagenes').glob('*.png'))
        file.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            iv.prepare_index(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_inconsistent_global_count_is_rejected(self):
        def edit(payloads):
            summary = json.loads(payloads['resumen.json'])
            summary['icon_occurrences'] += 1
            payloads['resumen.json'] = json_bytes(summary)
        self.rewrite_source(edit)
        with self.assertRaisesRegex(ValueError, 'conteos globales'):
            iv.prepare_index(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_variant_path_traversal_is_rejected(self):
        def edit(payloads):
            summary = json.loads(payloads['resumen.json'])
            summary['results'][0]['variant_id'] = '../outside'
            payloads['resumen.json'] = json_bytes(summary)
        self.rewrite_source(edit)
        with self.assertRaises(ValueError):
            iv.prepare_index(self.source, self.out)

    def test_display_names_are_escaped_without_changing_provenance(self):
        label = '<script>bad()</script> & "test"'
        def edit(payloads):
            summary = json.loads(payloads['resumen.json'])
            summary['results'][0]['variant'] = label
            payloads['resumen.json'] = json_bytes(summary)
        self.rewrite_source(edit)
        iv.prepare_index(self.source, self.out)
        page = (self.out / 'index.html').read_text()
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        with (self.out / 'galerias.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(next(csv.DictReader(stream))['variant'], label)

    def test_output_must_be_new_and_outside_input(self):
        with self.assertRaises(ValueError):
            iv.prepare_index(self.source, self.source / 'new')
        self.out.mkdir()
        with self.assertRaises(ValueError):
            iv.prepare_index(self.source, self.out)

    def test_cli_index_and_zip_do_not_require_rom_arguments(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = iv.main(['index', '--input', str(self.source), '--out', str(self.out),
                            '--zip', str(self.fixture.root / 'indice.zip')])
        self.assertEqual(code, 0, stderr.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertEqual(result['variants'], 2)
        self.assertTrue(result['navigation_portable'])
        self.assertTrue(result['zip']['portable_paths'])


if __name__ == '__main__':
    unittest.main()
