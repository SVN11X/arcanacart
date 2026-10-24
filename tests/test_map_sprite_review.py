"""Bounded map-sprite review on synthetic ROMs; no commercial data required."""

import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from arcanacart import map_sprite_review as mr
from arcanacart.core.io import digest, json_bytes


def literal_lz(raw):
    return b'\x10' + len(raw).to_bytes(3, 'little') + b''.join(
        b'\0' + raw[i:i + 8] for i in range(0, len(raw), 8))


class MapSpriteReview(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='arcana map sprites con espacios ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.datos = self.root / 'datos'
        self.out = self.root / 'revision'
        self.plan_path = self.root / 'identidades.json'
        self.raw = bytes(range(128)) * 3
        self.sheet = literal_lz(self.raw)
        data = bytearray(0x2000)
        data[0xAC:0xB0] = b'BE8E'
        data[0xB2] = 0x96
        struct.pack_into('<I', data, 0x180, 0x08000400)
        struct.pack_into('<I', data, 0x1C4, 0x08000400)
        struct.pack_into('<HHI', data, 0x400, 2, 0, 0x08000800)
        struct.pack_into('<HHI', data, 0x408, 3, 0, 0x08000800)
        data[0x800:0x800 + len(self.sheet)] = self.sheet
        data[0x1200:0x12E0] = bytes(range(224))
        self.base = bytes(data)
        self.base_path = self.datos / 'resultados/fe8/fe8-usa-base.gba'
        self.base_path.parent.mkdir(parents=True)
        self.base_path.write_bytes(self.base)
        profile = {'rom_sha256': digest(self.base), 'pointer_locations': [0x180, 0x1C4],
                   'palette_offset': 0x1200}
        patcher = patch.object(mr, 'PROFILES', {'fe8': profile})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plan = {'format': 'arcanacart-item-icon-variant-plan-1', 'reviewed_ranges': {}, 'variants': []}
        self.row = {'variant_id': 'fe8-001', 'game': 'fe8', 'variant': '001-sintetica',
                    'rom_relative_path': 'fe8/001-sintetica/mod.gba',
                    'air_relative_path': 'fe8/001-sintetica/analisis/air.json'}
        self.plan['variants'].append(self.row)
        variant = bytearray(self.base)
        variant[0x300] = 1
        self.save_variant(variant)

    def save_variant(self, data, *, records=None):
        self.rom = self.datos / 'resultados' / self.row['rom_relative_path']
        self.air = self.datos / 'resultados' / self.row['air_relative_path']
        self.rom.parent.mkdir(parents=True, exist_ok=True)
        self.air.parent.mkdir(parents=True, exist_ok=True)
        self.rom.write_bytes(data)
        self.row['rom_sha256'] = digest(data)
        if records is None:
            records = [{'offset': 0x800, 'compression': 'lz10', 'compressed_bytes': len(self.sheet),
                        'decompressed_bytes': len(self.raw), 'sha256': digest(self.raw),
                        'references': [0x404, 0x40C]}]
        self.air.write_bytes(json_bytes({'rom': {'sha256': digest(data), 'size_bytes': len(data)},
                                        'resources': records, 'scan': {'truncated': False, 'methods': ['lz10']}}))
        self.row['air_sha256'] = digest(self.air.read_bytes())
        self.plan_path.write_bytes(json_bytes(self.plan))

    def run_review(self, **kwargs):
        return mr.review_maps(self.datos, self.out, self.plan_path, **kwargs)

    def results(self):
        return json.loads((self.out / 'revision.json').read_bytes())['results']

    def test_known_profiles_and_real_identities(self):
        plan = mr._plan(mr.DEFAULT_PLAN)
        self.assertEqual(len(plan['variants']), 43)
        self.assertEqual(sum(r['game'] == 'fe7' for r in plan['variants']), 8)
        self.assertEqual(sum(r['game'] == 'fe8' for r in plan['variants']), 35)
        self.assertEqual(mr.PROBE_SLOTS, 128)

    def test_review_preserves_evidence_without_scan_decode_or_approval(self):
        originals = {p: p.read_bytes() for p in (self.base_path, self.rom, self.air, self.plan_path)}
        with patch('arcanacart.compression.scan_resources', side_effect=AssertionError('scan')), \
             patch('feunpack.lz10.decompress', side_effect=AssertionError('decompression')):
            summary = self.run_review()
        self.assertEqual(summary['counts'], {'pending': 2, 'error': 0, 'approved': 0})
        self.assertFalse(summary['ready_for_extraction'])
        self.assertFalse(summary['sheets_decompressed'])
        self.assertFalse(any(self.out.rglob('*.png')))
        self.assertFalse((self.out / 'definiciones').exists())
        self.assertEqual(summary['unique_stored_sheets'], 1)
        base, variant = self.results()
        self.assertEqual(variant['entries'][0]['air_correlation'], 'metadata-consistent')
        self.assertEqual(variant['entries'][0]['air_decoded_sha256'], digest(self.raw))
        self.assertFalse(variant['entries'][0]['decoded_sha256_recomputed'])
        self.assertEqual(variant['base_comparison']['identical_stored_sheets_and_flags'], 2)
        self.assertEqual(base['boundary_hint'], {'reason': 'zero-record-heuristic', 'sprite_id': 2})
        self.assertFalse(base['table_capacity_confirmed'])
        self.assertTrue(all(not p['runtime_use_verified'] for p in variant['palette_candidates']))
        sheet = self.out / variant['entries'][0]['stored_file']
        self.assertEqual(sheet.read_bytes(), self.sheet)
        for p, raw in originals.items():
            self.assertEqual(p.read_bytes(), raw)

    def test_repointed_table_remains_pending_and_records_context(self):
        data = bytearray(self.rom.read_bytes())
        data[0x600:0x618] = data[0x400:0x418]
        struct.pack_into('<I', data, 0x180, 0x08000600)
        struct.pack_into('<I', data, 0x1C4, 0x08000600)
        self.save_variant(data)
        self.run_review()
        row = self.results()[1]
        self.assertEqual(row['table_offset'], 0x600)
        self.assertEqual(row['status'], 'pending')
        self.assertTrue(all(r['code_before_literal_identical'] for r in row['base_comparison']['access_contexts']))

    def test_conflicting_aliases_do_not_promote_or_silently_select_another_table(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into('<I', data, 0x1C4, 0x08000600)
        self.save_variant(data)
        self.run_review()
        row = self.results()[1]
        self.assertIn('conflicting-access-pointers', row['issues'])
        self.assertEqual(row['table_offset'], 0x400)
        self.assertFalse(row['extraction_enabled'])

    def test_invalid_canonical_pointer_has_no_alias_fallback(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into('<I', data, 0x180, 0)
        self.save_variant(data)
        self.run_review()
        row = self.results()[1]
        self.assertIsNone(row['table_offset'])
        self.assertEqual(row['entries'], [])
        self.assertIn('canonical-pointer-unusable-no-fallback', row['issues'])
        self.assertTrue((self.out / row['access_pointers'][1]['context_file']).is_file())

    def test_rom_identity_mismatch_is_retained_as_an_error(self):
        raw = bytearray(self.rom.read_bytes())
        raw[0x300] ^= 1
        self.rom.write_bytes(raw)
        self.assertEqual(self.run_review()['counts']['error'], 1)
        self.assertEqual(self.results()[1]['status'], 'error')
        self.assertFalse((self.out / 'candidatas/fe8-001.json').exists())

    def test_air_line_endings_are_not_normalized(self):
        self.air.write_bytes(self.air.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(self.run_review()['counts']['error'], 1)
        self.assertIn('AIR', self.results()[1]['error'])

    def test_registry_line_endings_preserve_canonical_plan_hash(self):
        first = self.run_review()['plan_canonical_sha256']
        self.out = self.root / 'revision-crlf'
        self.plan_path.write_bytes(self.plan_path.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(self.run_review()['plan_canonical_sha256'], first)

    def test_air_correspondence_checks_compression_bounds_and_size(self):
        records = [{'offset': 0x800, 'compression': 'lz10', 'compressed_bytes': len(self.sheet) + 1,
                    'decompressed_bytes': len(self.raw), 'sha256': digest(self.raw), 'references': []}]
        self.save_variant(self.rom.read_bytes(), records=records)
        self.run_review()
        entry = self.results()[1]['entries'][0]
        self.assertEqual(entry['air_correlation'], 'metadata-mismatch')
        self.assertIn('air-metadata-mismatch', entry['issues'])

    def test_missing_air_candidate_is_reported_without_new_search(self):
        self.save_variant(self.rom.read_bytes(), records=[])
        self.run_review()
        self.assertEqual(self.results()[1]['entries'][0]['air_correlation'], 'no-existing-candidate')

    def test_reserved_first_slot_does_not_end_the_table(self):
        data = bytearray(self.rom.read_bytes())
        data[0x400:0x408] = bytes(8)
        self.save_variant(data)
        self.run_review()
        row = self.results()[1]
        self.assertEqual(row['entries'][0]['status'], 'reserved')
        self.assertEqual(row['entries'][1]['status'], 'candidate')
        self.assertEqual(row['boundary_hint']['sprite_id'], 2)

    def test_null_pointer_with_flags_preserved_as_reserved_not_end(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into('<HHI', data, 0x408, 3, 1, 0)
        self.save_variant(data)
        self.run_review()
        row = self.results()[1]
        self.assertEqual(row['entries'][1]['status'], 'reserved')
        self.assertEqual(row['boundary_hint']['sprite_id'], 2)

    def test_bad_sheet_has_bounded_header_evidence_and_no_decode(self):
        data = bytearray(self.rom.read_bytes())
        data[0x800] = 0x30
        self.save_variant(data)
        self.run_review()
        entry = self.results()[1]['entries'][0]
        self.assertEqual(entry['status'], 'unsupported-sheet')
        self.assertEqual(len((self.out / entry['header_file']).read_bytes()), 64)

    def test_invalid_lz_backreference_is_not_accepted_as_a_sheet(self):
        data = bytearray(self.rom.read_bytes())
        data[0x800:0x807] = b'\x10\x80\x01\0\x80\0\0'
        self.save_variant(data)
        self.run_review()
        entry = self.results()[1]['entries'][0]
        self.assertEqual(entry['status'], 'unsupported-sheet')
        self.assertNotIn('stored_file', entry)

    def test_ram_pointer_ends_probe_but_does_not_confirm_table_capacity(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into('<I', data, 0x40C, 0x02000400)
        self.save_variant(data)
        self.run_review()
        row = self.results()[1]
        self.assertEqual(row['boundary_hint'], {'reason': 'invalid-pointer-heuristic', 'sprite_id': 1})
        self.assertFalse(row['table_capacity_confirmed'])
        self.assertEqual((self.out / row['table_window_file']).read_bytes(), data[0x400:0x800])

    def test_truncated_table_pointer_and_gba_mirror_are_bounded(self):
        self.assertEqual(mr._rom_offset(0x0A000400, self.base, 8), 0x400)
        for pointer in (0x08001FFC, 0x08000401, 0x0E000400):
            with self.assertRaises(ValueError):
                mr._rom_offset(pointer, self.base, 8)

    def test_unknown_size_and_nonstandard_length_remain_unapproved(self):
        data = bytearray(self.rom.read_bytes())
        struct.pack_into('<H', data, 0x402, 9)
        struct.pack_into('<H', data, 0x40A, 2)
        self.save_variant(data)
        self.run_review()
        entries = self.results()[1]['entries']
        self.assertIn('unknown-size-code', entries[0]['issues'])
        self.assertIn('nonstandard-three-frame-size', entries[1]['issues'])

    def test_probe_budget_is_a_limit_even_without_a_boundary_hint(self):
        data = bytearray(self.rom.read_bytes())
        for i in range(mr.PROBE_SLOTS):
            struct.pack_into('<HHI', data, 0x400 + i * 8, 2, 0, 0x08000800)
        self.save_variant(data, records=[])
        self.run_review()
        row = self.results()[1]
        self.assertEqual(len(row['entries']), 128)
        self.assertIsNone(row['boundary_hint'])
        self.assertIn('probe-budget-or-rom-bound-reached', row['issues'])

    def test_changed_base_is_not_used_as_a_reference(self):
        raw = bytearray(self.base)
        raw[0x300] = 8
        self.base_path.write_bytes(raw)
        self.run_review()
        self.assertEqual(self.results()[0]['status'], 'error')
        self.assertEqual(self.results()[1]['base_comparison'], {'available': False})

    def test_bases_only_does_not_open_variant_inputs(self):
        self.rom.unlink()
        self.air.unlink()
        summary = self.run_review(scope='bases')
        self.assertEqual(summary['roms'], 1)
        self.assertEqual(summary['variants'], 0)
        self.assertEqual(summary['counts']['error'], 0)

    def test_full_45_rom_roster_preserves_all_43_variant_identities(self):
        base7 = bytearray(self.base)
        base7[0xAC:0xB0] = b'BE7E'
        base7 = bytes(base7)
        path = self.datos / 'resultados/fe7/fe7-usa-base.gba'
        path.parent.mkdir(parents=True)
        path.write_bytes(base7)
        profiles = {game: {**mr.PROFILES['fe8'], 'rom_sha256': digest(raw)}
                    for game, raw in (('fe7', base7), ('fe8', self.base))}
        self.plan['variants'] = []
        for game, count, raw in (('fe7', 8, base7), ('fe8', 35, self.base)):
            for i in range(1, count + 1):
                self.row = {'variant_id': f'{game}-{i:03}', 'game': game, 'variant': f'{i:03}-sintetica',
                            'rom_relative_path': f'{game}/{i:03}-sintetica/mod.gba',
                            'air_relative_path': f'{game}/{i:03}-sintetica/analisis/air.json'}
                self.plan['variants'].append(self.row)
                data = bytearray(raw)
                data[0x300] = i
                self.save_variant(data)
        with patch.object(mr, 'PROFILES', profiles):
            summary = self.run_review()
        self.assertEqual(summary['roms'], 45)
        self.assertEqual(summary['variants'], 43)
        self.assertEqual(summary['bases'], 2)
        self.assertEqual(summary['counts'], {'pending': 45, 'error': 0, 'approved': 0})
        results = self.results()
        self.assertEqual(len({r['variant_id'] for r in results}), 45)
        self.assertEqual(sum(r['game'] == 'fe7' for r in results), 9)
        self.assertEqual(sum(r['game'] == 'fe8' for r in results), 36)
        self.assertEqual(len(list((self.out / 'candidatas').glob('*.json'))), 45)

    def test_existing_output_or_output_containing_input_rejected(self):
        self.out.mkdir()
        with self.assertRaises(ValueError):
            self.run_review()
        with self.assertRaises(ValueError):
            mr.review_maps(self.datos, self.datos.parent, self.plan_path)

    def test_portable_zip_repackages_sealed_evidence_without_rom(self):
        self.run_review()
        self.rom.unlink()
        self.air.unlink()
        out = self.root / 'revision.zip'
        result = mr.pack_variants(self.out, out, state_name=mr.STATE)
        self.assertTrue(result['crc_verified'])
        with ZipFile(out) as z:
            self.assertIsNone(z.testzip())
            for n in z.namelist():
                self.assertNotIn('\\', n)
                self.assertEqual(z.read(n), (self.out / n).read_bytes())

    def test_modified_evidence_is_rejected_before_packaging(self):
        self.run_review()
        sheet = next(self.out.glob('hojas-comprimidas/*.lz10'))
        sheet.write_bytes(sheet.read_bytes() + b'alterado')
        out = self.root / 'alterado.zip'
        with self.assertRaises(ValueError):
            mr.pack_variants(self.out, out, state_name=mr.STATE)
        self.assertFalse(out.exists())

    def test_cli_errors_are_json_and_existing_outputs_are_preserved(self):
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            code = mr.main(['review', '--datos', str(self.datos), '--out', str(self.out),
                            '--identities', str(self.plan_path), '--zip', str(self.root / 'cli.zip')])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text.getvalue())['counts']['error'], 0)
        before = (self.out / 'revision.json').read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            code = mr.main(['review', '--datos', str(self.datos), '--out', str(self.out),
                            '--identities', str(self.plan_path)])
        self.assertEqual(code, 2)
        self.assertEqual((self.out / 'revision.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
