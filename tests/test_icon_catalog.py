"""Consolidation preserves resources and identities, including shared PNGs."""

import base64
import contextlib
import io
import json
import struct
import unittest
import zlib
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

import test_icon_variants as fixtures
from arcanacart import icon_catalog as ic
from arcanacart import icon_variants as iv
from arcanacart.core.io import digest, json_bytes

# Fixed RGBA fixture using filters 0..4, independently decoded with Pillow
# when prepared. Tests themselves need only the Python standard library.
FILTER_FIXTURE = (
    'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAB60lEQVR4nI2SIa/aUBiG3wICRBNqj1ow/QHULRNNEFPN'
    'MaiaKYKcIdg7FMlENQniGERRywQGgcDyByqwSHKS/oB3X9vTu+5mN1vNefrmy/mS57yAfAF8TqA4RYgZIs4Rc4EE'
    'a6TcYskdVjhiwzMy3rDHHTmfOJG4wsPYZ4BSLgk9OYVD4VI4/K+8JxcA41AuKohxKewLh8KFcFkvkH/hQrjk2/k+P'
    'qhvo2HJ0RCQ0xsNI+FSGF6TRy6HyyOvOz+oN0CJCdmMig8d9h2rDh86XM3omIGOMNEppzrhTPuYa3ChQ661wlbn3O'
    'k9j/qKsz7xple86yWeOiP1hh6+JPUrBCiqU8QUwr5w4TV5/k7ezPcaSa28VlIr7995H58/voyGSsSETlgsnAinwkvh'
    'T8I/hS/CN+FC+PEqclDfJO/ZiCydMNkA5XL/nbydNxsGJuPELDE1K87MiXNzxcLsuTY5t0ZhZ0IeDXg2Pm4m4d2kfJ'
    'oINLFI/JGxaVjpGpZ2uMq/d7jKU3Tne7+bF4uYVFjeeXz5S/Ni4VT4IHx5bWofX1PXMOXEPFzzlMtbYcrljz/mB/WG'
    'WkzxpnlFp22VsKLTzu68vSKwJ05szqndY2Yzzu2GC7vC2i65tSl3NsHRxjzbiDcb4m4Vn9YnLfALLd8q6PqE92wAAAA'
    'ASUVORK5CYII='
)


class IconCatalog(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.VariantIcons()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.make_all_unchanged()
        self.out = self.fixture.root / 'catalogo'

    def build(self, **kwargs):
        self.fixture.run_review()
        self.fixture.run_extract(**kwargs)
        self.source = self.fixture.out
        return self.source

    def catalog(self):
        return json.loads((self.out / 'catalogo.json').read_bytes())

    def mutate(self, edit, *, csvs=True):
        payloads = iv._sealed(self.source)
        payloads.pop(iv.STATE)
        edit(payloads)
        summary = json.loads(payloads['resumen.json'])
        allrows = []
        for result in summary['results']:
            vid = result['variant_id']
            rows = json.loads(payloads[vid + '/catalog.json'])['icons']
            if csvs:
                payloads[vid + '/icons.csv'] = iv._csv(rows, list(rows[0]))
            for r in rows:
                origin = {'variant_id': vid, 'variant': result['variant'], **r}
                for field in ('file', 'raw_file', 'palette_file'):
                    origin[field] = vid + '/' + origin[field]
                allrows.append(origin)
            artifacts = {n[len(vid) + 1:]: digest(raw) for n, raw in payloads.items()
                         if n.startswith(vid + '/') and n != vid + '/icons-state.json'}
            payloads[vid + '/icons-state.json'] = json_bytes({'status': 'completed', 'artifacts': artifacts})
        if csvs:
            payloads['ocurrencias.csv'] = iv._csv(allrows, list(allrows[0]))
        self.source = self.fixture.root / 'lote-modificado'
        iv._publish(self.source, payloads)

    def test_shared_images_retain_all_ids_and_variant_origins(self):
        self.build()
        result = ic.consolidate(self.source, self.out)
        self.assertEqual((result['variants'], result['icon_occurrences'], result['unique_images']), (2, 8, 3))
        self.assertEqual(result['source_png_files'], 6)
        self.assertEqual(result['duplicate_png_copies_avoided'], 3)
        images = self.catalog()['images']
        self.assertEqual(sorted(i['occurrences'] for i in images), [2, 2, 4])
        rows = [r for i in images for r in i['origins']]
        self.assertEqual({(r['variant_id'], r['icon_id']) for r in rows},
                         {(v, i) for v in ('fe8-001', 'fe8-002') for i in range(4)})

    def test_transparent_images_and_occurrences_are_counted_separately(self):
        self.build()
        result = ic.consolidate(self.source, self.out)
        self.assertEqual(result['visible_images'], 2)
        self.assertEqual(result['transparent_images'], 1)
        self.assertEqual(result['transparent_occurrences'], 2)

    def test_resources_and_every_original_field_preserved(self):
        self.build()
        before = {p.relative_to(self.source).as_posix(): p.read_bytes()
                  for p in self.source.rglob('*') if p.is_file()}
        with patch.object(iv, 'load_rom', side_effect=AssertionError('ROM read')), \
             patch.object(iv, 'extract_icons', side_effect=AssertionError('extraction')):
            ic.consolidate(self.source, self.out)
        self.assertEqual(before, {p.relative_to(self.source).as_posix(): p.read_bytes()
                                  for p in self.source.rglob('*') if p.is_file()})
        for image in self.catalog()['images']:
            for origin in image['origins']:
                vid = origin['variant_id']
                source = json.loads(before[vid + '/catalog.json'])['icons'][origin['icon_id']]
                for field, value in source.items():
                    self.assertEqual(origin[field], value)
                for field, source_field in [('file', 'source_png'), ('raw_file', 'source_raw_file'),
                                             ('palette_file', 'source_palette_file')]:
                    self.assertEqual((self.out / origin[field]).read_bytes(), before[origin[source_field]])
        self.assertEqual((self.out / 'fuentes/resumen-original.json').read_bytes(), before['resumen.json'])

    def test_same_png_with_different_raw_and_palette_keeps_both(self):
        row = self.fixture.plan['variants'][1]
        data = bytearray(iv._input(self.fixture.datos, row['rom_relative_path']).read_bytes())
        swap = lambda value: 2 if value == 1 else 1 if value == 2 else value
        for i in range(0x1000, 0x1200):
            data[i] = swap(data[i] & 15) | (swap(data[i] >> 4) << 4)
        data[0x2002:0x2006] = data[0x2004:0x2006] + data[0x2002:0x2004]
        self.fixture.write_variant(row, data)
        self.fixture.approve_candidate()
        self.fixture.run_review()
        self.fixture.run_extract()
        result = ic.consolidate(self.fixture.out, self.out)
        self.assertEqual((result['unique_images'], result['unique_raw_resources'], result['unique_palettes']), (3, 5, 2))
        shared = next(i for i in self.catalog()['images'] if i['occurrences'] == 4)
        self.assertEqual(len({r['source_sha256'] for r in shared['origins']}), 2)
        self.assertEqual(len({r['palette_sha256'] for r in shared['origins']}), 2)

    def test_directory_and_zip_produce_same_assets_and_origins(self):
        self.build()
        ic.consolidate(self.source, self.out)
        zip_path = self.fixture.root / 'lote.zip'
        iv.pack_variants(self.source, zip_path)
        other = self.fixture.root / 'desde-zip'
        ic.consolidate(zip_path, other)
        catalog = json.loads((other / 'catalogo.json').read_bytes())
        self.assertEqual(catalog['images'], self.catalog()['images'])
        self.assertEqual((other / 'index.html').read_bytes(), (self.out / 'index.html').read_bytes())

    def test_partial_source_remains_explicit(self):
        row = self.fixture.plan['variants'][1]
        data = bytearray(iv._input(self.fixture.datos, row['rom_relative_path']).read_bytes())
        data[0x1080] = 0x42
        self.fixture.write_variant(row, data)
        self.build(only_verified=True)
        result = ic.consolidate(self.source, self.out)
        self.assertEqual(result['variants'], 1)
        self.assertEqual(result['source_expected_variants'], 2)
        self.assertEqual(result['source_skipped_variants'], ['fe8-002'])

    def test_tampered_input_fails_before_output_creation(self):
        self.build()
        png = next((self.source / 'fe8-001/imagenes').glob('*.png'))
        png.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            ic.consolidate(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_valid_png_for_another_raw_not_accepted_even_when_resealed(self):
        self.build()
        def edit(payloads):
            catalog = json.loads(payloads['fe8-001/catalog.json'])
            catalog['icons'][0]['file'] = catalog['icons'][3]['file']
            catalog['icons'][0]['png_sha256'] = catalog['icons'][3]['png_sha256']
            payloads['fe8-001/catalog.json'] = json_bytes(catalog)
        self.mutate(edit)
        with self.assertRaisesRegex(ValueError, 'PNG no coincide'):
            ic.consolidate(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_missing_global_csv_origin_is_not_silently_lost(self):
        self.build()
        self.mutate(lambda p: p.__setitem__('ocurrencias.csv', b'variant_id\n'), csvs=False)
        with self.assertRaisesRegex(ValueError, 'CSV o los conteos'):
            ic.consolidate(self.source, self.out)

    def test_unreferenced_raw_is_not_silently_dropped(self):
        self.build()
        raw = b'\x88' * 128
        self.mutate(lambda p: p.__setitem__('fe8-001/raw/' + digest(raw) + '.bin', raw))
        with self.assertRaisesRegex(ValueError, 'sin procedencia'):
            ic.consolidate(self.source, self.out)

    def test_source_definition_hash_uses_exact_bytes(self):
        self.build()
        def edit(payloads):
            for name in ('definiciones/fe8-001.json', 'fe8-001/definition.json'):
                payloads[name] = payloads[name].replace(b'\n', b'\r\n')
        self.mutate(edit)
        with self.assertRaisesRegex(ValueError, 'definición no coincide'):
            ic.consolidate(self.source, self.out)

    def test_source_row_identity_must_match_variant(self):
        self.build()
        def edit(payloads):
            catalog = json.loads(payloads['fe8-001/catalog.json'])
            catalog['icons'][0]['rom_sha256'] = '0' * 64
            payloads['fe8-001/catalog.json'] = json_bytes(catalog)
        self.mutate(edit)
        with self.assertRaisesRegex(ValueError, 'Procedencia'):
            ic.consolidate(self.source, self.out)

    def test_unknown_root_resources_are_rejected(self):
        self.build()
        self.mutate(lambda p: p.__setitem__('otra-carpeta/recurso.bin', b'data'))
        with self.assertRaisesRegex(ValueError, 'archivos raíz'):
            ic.consolidate(self.source, self.out)

    def test_reject_existing_or_nested_output(self):
        self.build()
        with self.assertRaises(ValueError):
            ic.consolidate(self.source, self.source / 'catalogo')
        self.out.mkdir()
        with self.assertRaises(ValueError):
            ic.consolidate(self.source, self.out)

    def test_zip_slip_duplicate_paths_and_symlink_entries_rejected(self):
        cases = [('../escape.bin', b'x', None), ('link.bin', b'x', 0o120777 << 16)]
        for index, (name, body, mode) in enumerate(cases):
            with self.subTest(name=name):
                path = self.fixture.root / f'bad-{index}.zip'
                with ZipFile(path, 'w') as z:
                    info = ZipInfo(name)
                    if mode:
                        info.create_system, info.external_attr = 3, mode
                    z.writestr(info, body)
                with self.assertRaises(ValueError):
                    ic.consolidate(path, self.out)
        path = self.fixture.root / 'duplicate.zip'
        with ZipFile(path, 'w') as z:
            z.writestr('a.json', b'{}')
            z.writestr('A.json', b'{}')
        with self.assertRaises(ValueError):
            ic.consolidate(path, self.out)

    def test_png_all_five_filters_match_independent_known_pixels(self):
        expected = bytes(c for y in range(16) for x in range(16)
                         for c in (x * 17, y * 16, (x ^ y) * 13, 0 if (x + y) % 3 == 0 else 255))
        self.assertEqual(ic._png_pixels(base64.b64decode(FILTER_FIXTURE)), expected)

    def test_png_crc_and_decompression_bounds(self):
        png = bytearray(base64.b64decode(FILTER_FIXTURE))
        png[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC'):
            ic._png_pixels(bytes(png))
        def chunk(kind, body):
            return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
        oversized = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(b'x' * 2097152)) + chunk(b'IEND', b''))
        with self.assertRaisesRegex(ValueError, 'tamaño descomprimido'):
            ic._png_pixels(oversized)

    def test_catalog_manifest_and_portable_zip(self):
        self.build()
        ic.consolidate(self.source, self.out)
        files = iv._sealed(self.out, state_name=ic.CATALOG_STATE)
        self.assertIn('catalog-state.json', files)
        self.assertNotIn('variant-icons-state.json', files)
        target = self.fixture.root / 'catalogo.zip'
        iv.pack_variants(self.out, target, state_name=ic.CATALOG_STATE)
        with ZipFile(target) as z:
            self.assertIsNone(z.testzip())
            self.assertTrue(all('\\' not in n for n in z.namelist()))
            for name, raw in files.items():
                self.assertEqual(z.read(name), raw)

    def test_cli_does_not_read_roms_and_creates_zip(self):
        self.build()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = ic.main(['consolidate', '--input', str(self.source), '--out', str(self.out),
                            '--zip', str(self.fixture.root / 'catalogo-cli.zip')])
        self.assertEqual(code, 0, stderr.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertFalse(result['roms_read'])
        self.assertTrue(result['zip']['portable_paths'])

    def test_invalid_input_folder_does_not_read_unrelated_resources(self):
        directory = self.fixture.root / 'otra-carpeta'
        directory.mkdir()
        with patch.object(ic, '_sealed', side_effect=AssertionError('unrelated read')):
            with self.assertRaisesRegex(ValueError, 'carpeta de un lote'):
                ic.consolidate(directory, self.out)
        rom = self.fixture.root / 'not-a-zip.gba'
        rom.write_bytes(b'ROM')
        with self.assertRaises(ValueError):
            ic.consolidate(rom, self.out)


if __name__ == '__main__':
    unittest.main()
