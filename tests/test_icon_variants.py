"""Synthetic variants exercise the review gate without commercial ROMs."""

import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from arcanacart import icon_variants as iv
from arcanacart.core.io import digest, json_bytes
import test_item_icons as fixtures


class VariantIcons(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ItemIcons()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.temp = tempfile.TemporaryDirectory(prefix='arcana variantes con espacios ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.datos = self.root / 'datos'
        self.review = self.root / 'revision'
        self.out = self.root / 'extraccion'
        base = bytearray(fixture.rom.read_bytes())
        struct.pack_into('<I', base, 0x200, 0x08002000)
        self.base = bytes(base)
        self.base_path = self.datos / 'resultados/fe8/fe8-usa-base.gba'
        self.base_path.parent.mkdir(parents=True)
        self.base_path.write_bytes(self.base)
        self.spec = {**fixture.layout, 'rom_sha256': digest(self.base), 'first_id': 0,
                     'palette_pointer_location': 0x200}
        self.patcher = patch.object(iv, 'BUILTIN_LAYOUTS', {digest(self.base): self.spec})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.plan_path = self.root / 'plan.json'
        self.plan = {'format': iv.PLAN_FORMAT, 'variants': [], 'reviewed_ranges': {}}
        self.make_variant(1)
        self.make_variant(2, changed=True)

    def save_plan(self):
        self.plan_path.write_bytes(json_bytes(self.plan))

    def make_variant(self, number, changed=False):
        vid = f'fe8-{number:03}'
        row = {'variant_id': vid, 'game': 'fe8', 'variant': f'{number:03}-sintetica',
               'rom_relative_path': f'fe8/{number:03}-sintetica/mod.gba',
               'air_relative_path': f'fe8/{number:03}-sintetica/analisis/air.json'}
        data = bytearray(self.base)
        data[0x350] = number
        if changed:
            data[0x1080] = 0x42
        self.plan['variants'].append(row)
        self.write_variant(row, data)
        return row

    def write_variant(self, row, data):
        rom = iv._input(self.datos, row['rom_relative_path'])
        air = iv._input(self.datos, row['air_relative_path'])
        rom.parent.mkdir(parents=True, exist_ok=True)
        air.parent.mkdir(parents=True, exist_ok=True)
        rom.write_bytes(data)
        row['rom_sha256'] = digest(data)
        document = {'rom': {'sha256': row['rom_sha256'], 'size_bytes': len(data)},
                    'resources': [], 'scan': {'truncated': False, 'methods': ['lz10']}}
        air.write_bytes(json_bytes(document))
        row['air_sha256'] = digest(air.read_bytes())
        self.save_plan()

    def run_review(self):
        return iv.review_variants(self.datos, self.review, self.plan_path)

    def run_extract(self, **kwargs):
        return iv.extract_variants(self.datos, self.review, self.out, self.plan_path, **kwargs)

    def report(self):
        return json.loads((self.review / 'revision.json').read_bytes())

    def make_all_unchanged(self):
        row = self.plan['variants'][1]
        data = bytearray(self.base)
        data[0x350] = 2
        self.write_variant(row, data)

    def approve_candidate(self):
        self.run_review()
        row = self.report()['results'][1]
        evidence = {k: row[k] for k in iv.RANGE_FIELDS if k != 'evidence'}
        evidence['evidence'] = ['Synthetic independent range review; not a game ROM.']
        self.plan['reviewed_ranges'][row['variant_id']] = evidence
        self.save_plan()
        self.review = self.root / 'revision-aprobada'

    def test_real_roster_has_43_unique_variant_identities(self):
        plan = iv._plan(iv.DEFAULT_PLAN)
        self.assertEqual(len(plan['variants']), 43)
        self.assertEqual(sum(r['game'] == 'fe7' for r in plan['variants']), 8)
        self.assertEqual(sum(r['game'] == 'fe8' for r in plan['variants']), 35)
        self.assertEqual(len({r['rom_sha256'] for r in plan['variants']}), 43)
        self.assertTrue(set(plan['reviewed_ranges']) <= {r['variant_id'] for r in plan['variants']})

    def test_identical_prefix_verified_changed_bank_only_candidate_no_scan(self):
        with patch('arcanacart.compression.scan_resources', side_effect=AssertionError('scan')):
            result = self.run_review()
        self.assertEqual(result['counts'], {'verified': 1, 'pending': 1, 'error': 0})
        self.assertFalse(result['ready_for_full_batch'])
        self.assertFalse(result['icons_exported'])
        self.assertTrue((self.review / 'definiciones/fe8-001.json').is_file())
        self.assertFalse((self.review / 'definiciones/fe8-002.json').exists())
        self.assertTrue((self.review / 'candidatas/fe8-002.json').is_file())
        self.assertFalse(any(self.review.rglob('*.png')))
        self.assertFalse(self.report()['results'][0]['table_capacity_confirmed'])

    def test_no_new_range_derived_from_relocation(self):
        row = self.plan['variants'][0]
        data = bytearray(iv._input(self.datos, row['rom_relative_path']).read_bytes())
        data[0x3000:0x3200] = data[0x1000:0x1200]
        struct.pack_into('<I', data, 0x100, 0x08003000)
        self.write_variant(row, data)
        self.run_review()
        result = self.report()['results'][0]
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['last_id'], 3)
        self.assertTrue(result['table_relocated'])

    def test_changed_access_context_not_promoted_by_identical_graphics(self):
        row = self.plan['variants'][0]
        data = bytearray(iv._input(self.datos, row['rom_relative_path']).read_bytes())
        data[0xFC] = 0xAA
        self.write_variant(row, data)
        self.run_review()
        result = self.report()['results'][0]
        self.assertTrue(result['base_bank_identical'])
        self.assertEqual(result['status'], 'pending')

    def test_changed_palette_requires_review(self):
        row = self.plan['variants'][0]
        data = bytearray(iv._input(self.datos, row['rom_relative_path']).read_bytes())
        data[0x2002] ^= 1
        self.write_variant(row, data)
        self.run_review()
        self.assertEqual(self.report()['results'][0]['status'], 'pending')

    def test_exact_air_bytes_not_newline_normalized(self):
        row = self.plan['variants'][0]
        air = iv._input(self.datos, row['air_relative_path'])
        air.write_bytes(air.read_bytes().replace(b'\n', b'\r\n'))
        self.run_review()
        self.assertEqual(self.report()['results'][0]['status'], 'error')
        self.assertIn('LF/CRLF', self.report()['results'][0]['error'])

    def test_wrong_rom_hash_not_used_for_evidence(self):
        row = self.plan['variants'][0]
        rom = iv._input(self.datos, row['rom_relative_path'])
        rom.write_bytes(rom.read_bytes() + b'x')
        self.run_review()
        result = self.report()['results'][0]
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['code_window'])

    def test_invalid_pointer_retains_bounded_code_evidence(self):
        row = self.plan['variants'][0]
        data = bytearray(iv._input(self.datos, row['rom_relative_path']).read_bytes())
        struct.pack_into('<I', data, 0x100, 0x02000000)
        self.write_variant(row, data)
        self.run_review()
        result = self.report()['results'][0]
        self.assertEqual(result['status'], 'error')
        self.assertIsNotNone(result['code_window'])
        self.assertTrue((self.review / result['code_window']['file']).is_file())

    def test_bad_base_stops_before_creating_output(self):
        self.base_path.write_bytes(self.base + b'x')
        with self.assertRaisesRegex(ValueError, 'base exacta'):
            self.run_review()
        self.assertFalse(self.review.exists())

    def test_missing_variant_reports_error_and_continues(self):
        iv._input(self.datos, self.plan['variants'][0]['rom_relative_path']).unlink()
        self.run_review()
        self.assertEqual(self.report()['counts'], {'verified': 0, 'pending': 1, 'error': 1})

    def test_complete_batch_blocked_if_any_candidate(self):
        self.run_review()
        with self.assertRaisesRegex(ValueError, 'sin verificar'):
            self.run_extract()
        self.assertFalse(self.out.exists())

    def test_explicit_partial_batch_preserves_every_occurrence_and_origin(self):
        self.run_review()
        result = self.run_extract(only_verified=True)
        self.assertEqual(result['processed_variants'], 1)
        self.assertEqual(result['skipped_variants'], ['fe8-002'])
        self.assertEqual(result['icon_occurrences'], 4)
        import csv
        with (self.out / 'ocurrencias.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([r['icon_id'] for r in rows], ['0', '1', '2', '3'])
        self.assertEqual({r['variant_id'] for r in rows}, {'fe8-001'})
        self.assertTrue(all((self.out / r['file']).is_file() for r in rows))
        self.assertEqual(rows[0]['file'], rows[1]['file'])

    def test_full_batch_rechecks_and_preserves_inputs(self):
        self.make_all_unchanged()
        self.run_review()
        before = {p: p.read_bytes() for p in self.datos.rglob('*') if p.is_file()}
        with patch('arcanacart.compression.scan_resources', side_effect=AssertionError('scan')):
            result = self.run_extract()
        self.assertEqual(result['processed_variants'], 2)
        self.assertEqual(result['icon_occurrences'], 8)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(len(iv._sealed(self.out)), len([p for p in self.out.rglob('*') if p.is_file()]))

    def test_complete_workflow_43_synthetic_variants_both_games(self):
        base7 = bytearray(self.base)
        base7[0x360] = 7
        path = self.datos / 'resultados/fe7/fe7-usa-base.gba'
        path.parent.mkdir(parents=True)
        path.write_bytes(base7)
        spec7 = {**self.spec, 'game': 'fe7', 'rom_sha256': digest(base7)}
        self.plan['variants'] = []
        for game, count, base in [('fe7', 8, base7), ('fe8', 35, self.base)]:
            for n in range(1, count + 1):
                row = {'variant_id': f'{game}-{n:03}', 'game': game, 'variant': f'{n:03}-sintetica',
                       'rom_relative_path': f'{game}/{n:03}/mod.gba',
                       'air_relative_path': f'{game}/{n:03}/analisis/air.json'}
                data = bytearray(base)
                data[0x350] = n
                self.plan['variants'].append(row)
                self.write_variant(row, data)
        with patch.object(iv, 'BUILTIN_LAYOUTS', {digest(self.base): self.spec, digest(base7): spec7}):
            review = self.run_review()
            result = self.run_extract()
        self.assertEqual(review['counts'], {'verified': 43, 'pending': 0, 'error': 0})
        self.assertEqual(result['processed_variants'], 43)
        self.assertEqual(result['icon_occurrences'], 172)
        self.assertEqual(result['unique_pngs_across_variants'], 3)
        self.assertFalse(result['rescanned'])
        self.assertEqual(len(list((self.out / 'definiciones').glob('*.json'))), 43)

    def test_batch_failure_keeps_completed_variant_and_records_failed_state(self):
        self.make_all_unchanged()
        self.run_review()
        real_extract = iv.extract_icons
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('synthetic output failure')
            return real_extract(*args, **kwargs)

        with patch.object(iv, 'extract_icons', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'synthetic output failure'):
                self.run_extract()
        self.assertTrue((self.out / 'fe8-001/catalog.json').is_file())
        self.assertEqual(json.loads((self.out / iv.STATE).read_bytes())['status'], 'failed')
        with self.assertRaises(ValueError):
            iv.pack_variants(self.out, self.root / 'fallido.zip')

    def test_explicit_review_checks_all_range_hashes(self):
        self.approve_candidate()
        result = self.run_review()
        self.assertTrue(result['ready_for_full_batch'])
        self.assertEqual(self.report()['results'][1]['reason'], 'explicit-hash-bound-range-review')
        self.assertEqual(self.run_extract()['processed_variants'], 2)

    def test_incorrect_reviewed_bound_or_hash_not_enabled(self):
        self.approve_candidate()
        self.plan['reviewed_ranges']['fe8-002']['bank_sha256'] = '0' * 64
        self.save_plan()
        self.run_review()
        self.assertEqual(self.report()['results'][1]['status'], 'error')
        self.assertFalse((self.review / 'definiciones/fe8-002.json').exists())

    def test_relocated_table_out_of_rom_rejected(self):
        row = self.plan['variants'][0]
        data = bytearray(iv._input(self.datos, row['rom_relative_path']).read_bytes())
        struct.pack_into('<I', data, 0x100, 0x08003F80)
        self.write_variant(row, data)
        self.run_review()
        self.assertEqual(self.report()['results'][0]['status'], 'error')

    def test_current_rom_changed_after_review_no_batch_output(self):
        self.make_all_unchanged()
        self.run_review()
        rom = iv._input(self.datos, self.plan['variants'][1]['rom_relative_path'])
        rom.write_bytes(rom.read_bytes() + b'x')
        with self.assertRaises(ValueError):
            self.run_extract()
        self.assertFalse(self.out.exists())

    def test_plan_line_endings_canonical_but_resources_exact(self):
        self.make_all_unchanged()
        self.run_review()
        self.plan_path.write_bytes(self.plan_path.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(self.run_extract()['processed_variants'], 2)

    def test_plan_semantic_change_requires_new_review(self):
        self.run_review()
        self.plan['variants'][0]['variant'] = 'changed-name'
        self.save_plan()
        with self.assertRaisesRegex(ValueError, 'plan actual'):
            self.run_extract(only_verified=True)

    def test_forged_status_and_resealed_manifest_do_not_promote_candidate(self):
        self.run_review()
        report = self.report()
        report['results'][1]['status'] = 'verified'
        (self.review / 'revision.json').write_bytes(json_bytes(report))
        artifacts = {p.relative_to(self.review).as_posix(): digest(p.read_bytes())
                     for p in self.review.rglob('*') if p.is_file() and p.name != iv.STATE}
        (self.review / iv.STATE).write_bytes(json_bytes({'status': 'completed', 'artifacts': artifacts}))
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            self.run_extract()
        self.assertFalse(self.out.exists())

    def test_tampered_review_artifact_rejected(self):
        self.run_review()
        p = self.review / 'definiciones/fe8-001.json'
        p.write_bytes(p.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.run_extract(only_verified=True)

    def test_portable_zip_exact_payloads_crc_and_standard_extraction(self):
        self.run_review()
        output = self.root / 'revision.zip'
        result = iv.pack_variants(self.review, output)
        self.assertTrue(result['portable_paths'])
        with ZipFile(output) as z:
            self.assertIsNone(z.testzip())
            self.assertTrue(all('\\' not in name for name in z.namelist()))
            for name in z.namelist():
                self.assertEqual(z.read(name), (self.review / name).read_bytes())
            z.extractall(self.root / 'extraida')
        self.assertTrue((self.root / 'extraida/definiciones/fe8-001.json').is_file())
        with self.assertRaises(ValueError):
            iv.pack_variants(self.review, output)

    def test_extra_or_symlink_file_blocks_packaging(self):
        self.run_review()
        extra = self.review / 'extra.txt'
        extra.write_text('extra')
        with self.assertRaises(ValueError):
            iv.pack_variants(self.review, self.root / 'extra.zip')
        extra.unlink()
        try:
            extra.symlink_to(self.plan_path)
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            iv.pack_variants(self.review, self.root / 'link.zip')

    def test_reject_output_inside_review_and_existing_review(self):
        self.run_review()
        with self.assertRaises(ValueError):
            self.run_review()
        with self.assertRaises(ValueError):
            iv.pack_variants(self.review, self.review / 'bad.zip')

    def test_bad_plan_traversal_duplicates_and_unbound_ranges(self):
        original = json.loads(json.dumps(self.plan))
        for field, value in [('rom_relative_path', '../outside.gba'), ('air_relative_path', 'fe8\\air.json'),
                             ('rom_sha256', 'no hash')]:
            with self.subTest(field=field):
                self.plan = json.loads(json.dumps(original))
                self.plan['variants'][0][field] = value
                self.save_plan()
                with self.assertRaises(ValueError):
                    iv._plan(self.plan_path)
        self.plan = original
        self.plan['variants'].append(self.plan['variants'][0])
        self.save_plan()
        with self.assertRaises(ValueError):
            iv._plan(self.plan_path)

    def test_feditor_fe7_excludes_embedded_code_from_original_last_slot(self):
        base = bytearray(0xD0100)
        base[:0xC0] = self.base[:0xC0]
        spec = {'format': self.spec['format'], 'game': 'fe7', 'first_id': 0, 'icon_count': 173,
                'icon_bytes': 128, 'table_offset': 0xC5EA4, 'pointer_location': 0x4E20,
                'palette_offset': 0xD0000, 'palette_pointer_location': 0x4D40,
                'sources': ['synthetic FEditor range regression']}
        struct.pack_into('<I', base, 0x4E20, 0x080C5EA4)
        struct.pack_into('<I', base, 0x4D40, 0x080D0000)
        base[0xC5EA4:0xCB524] = b'\x11' * (173 * 128)
        spec['rom_sha256'] = digest(base)
        p = self.datos / 'resultados/fe7/fe7-usa-base.gba'
        p.parent.mkdir(parents=True)
        p.write_bytes(base)
        base[0xCB51A:0xCB51E] = bytes.fromhex('02494018')
        row = {'variant_id': 'fe7-001', 'game': 'fe7', 'variant': '001-feditor',
               'rom_relative_path': 'fe7/feditor/mod.gba', 'air_relative_path': 'fe7/feditor/air.json'}
        self.plan['variants'] = [row]
        self.write_variant(row, base)
        with patch.object(iv, 'BUILTIN_LAYOUTS', {spec['rom_sha256']: spec}):
            self.run_review()
        result = self.report()['results'][0]
        self.assertTrue(result['feditor_final_slot_excluded'])
        self.assertEqual(result['last_id'], 0xAB)
        self.assertEqual(result['status'], 'verified')

    def test_cli_review_zip_with_spaces_and_missing_base_error(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        args = ['review', '--datos', str(self.datos), '--out', str(self.review), '--plan', str(self.plan_path),
                '--zip', str(self.root / 'con espacios.zip')]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = iv.main(args)
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())['variants'], 2)
        self.base_path.unlink()
        args[args.index('--out') + 1] = str(self.root / 'otro')
        args = args[:-2]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            self.assertEqual(iv.main(args), 2)


if __name__ == '__main__':
    unittest.main()
