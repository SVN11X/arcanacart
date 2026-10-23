"""Portable repackaging of an existing, hash-verified icon batch."""

import contextlib
import io
import json
import unittest
from zipfile import ZipFile

import test_item_icons as fixtures

from arcanacart.core.io import json_bytes
from arcanacart.icon_package import main, pack_icons


class IconPackage(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ItemIcons()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.source = self.root / 'existing icon batch'
        self.fixture.out = self.source / 'fe8'
        result = self.fixture.extract()
        self.batch = {
            'format': 'arcanacart-item-icon-batch-1', 'status': 'completed',
            'games': 1, 'icon_occurrences': 4, 'results': [result],
        }
        (self.source / 'resumen.json').write_bytes(json_bytes(self.batch))
        (self.source / 'run-state.json').write_bytes(json_bytes({'status': 'completed'}))
        self.out = self.root / 'portable.zip'

    def source_bytes(self):
        return {p.relative_to(self.source).as_posix(): p.read_bytes()
                for p in self.source.rglob('*') if p.is_file()}

    def test_portable_paths_exact_payloads_crc_and_no_input_changes(self):
        before = self.source_bytes()
        result = pack_icons(self.source, self.out)
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['portable_paths'])
        self.assertTrue(result['crc_verified'])
        self.assertFalse(result['rescanned'])
        self.assertFalse(result['inputs_modified'])
        self.assertEqual(before, self.source_bytes())
        with ZipFile(self.out) as archive:
            self.assertEqual(set(archive.namelist()), set(before))
            self.assertTrue(all('\\' not in n for n in archive.namelist()))
            self.assertIsNone(archive.testzip())
            for name, data in before.items():
                self.assertEqual(archive.read(name), data)
            dest = self.root / 'extracted'
            archive.extractall(dest)
        self.assertTrue((dest / 'fe8' / 'index.html').is_file())
        self.assertEqual((dest / 'fe8' / 'catalog.json').read_bytes(), before['fe8/catalog.json'])

    def test_same_snapshot_creates_same_zip_bytes(self):
        pack_icons(self.source, self.out)
        other = self.root / 'other.zip'
        pack_icons(self.source, other)
        self.assertEqual(self.out.read_bytes(), other.read_bytes())

    def test_existing_zip_is_preserved(self):
        self.out.write_bytes(b'keep this')
        with self.assertRaises(ValueError):
            pack_icons(self.source, self.out)
        self.assertEqual(self.out.read_bytes(), b'keep this')

    def test_refuses_output_inside_source(self):
        out = self.source / 'recursive.zip'
        with self.assertRaises(ValueError):
            pack_icons(self.source, out)
        self.assertFalse(out.exists())

    def test_tampered_raw_is_not_packaged(self):
        raw = next((self.source / 'fe8/raw').glob('*.bin'))
        raw.write_bytes(b'x' * 128)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            pack_icons(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_missing_file_is_not_packaged(self):
        next((self.source / 'fe8/imagenes').glob('*.png')).unlink()
        with self.assertRaisesRegex(ValueError, 'Faltan artefactos'):
            pack_icons(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_unrecorded_file_is_not_packaged(self):
        (self.source / 'fe8/unrecorded.txt').write_text('extra')
        with self.assertRaises(ValueError):
            pack_icons(self.source, self.out)

    def test_root_extra_file_is_not_packaged(self):
        (self.source / 'extra.txt').write_text('extra')
        with self.assertRaises(ValueError):
            pack_icons(self.source, self.out)

    def test_incomplete_batch_is_not_packaged(self):
        (self.source / 'run-state.json').write_bytes(json_bytes({'status': 'running'}))
        with self.assertRaises(ValueError):
            pack_icons(self.source, self.out)

    def test_global_count_must_match_games(self):
        self.batch['icon_occurrences'] = 999
        (self.source / 'resumen.json').write_bytes(json_bytes(self.batch))
        with self.assertRaises(ValueError):
            pack_icons(self.source, self.out)

    def test_powershell_integral_double_sum_is_supported(self):
        self.batch['icon_occurrences'] = 4.0
        (self.source / 'resumen.json').write_bytes(json_bytes(self.batch))
        self.assertEqual(pack_icons(self.source, self.out)['status'], 'completed')

    def test_backslash_in_manifest_is_rejected(self):
        path = self.source / 'fe8/icons-state.json'
        state = json.loads(path.read_bytes())
        old = next(n for n in state['artifacts'] if '/' in n)
        state['artifacts'][old.replace('/', '\\')] = state['artifacts'].pop(old)
        path.write_bytes(json_bytes(state))
        with self.assertRaises(ValueError):
            pack_icons(self.source, self.out)

    def test_symlink_input_is_rejected(self):
        link = self.root / 'linked batch'
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest('Symlinks not available')
        with self.assertRaises(ValueError):
            pack_icons(link, self.out)

    def test_cli_creates_portable_archive_and_reports_failures(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        args = ['--input', str(self.source), '--out', str(self.out)]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        self.assertEqual((code, stderr.getvalue()), (0, ''))
        self.assertTrue(json.loads(stdout.getvalue())['portable_paths'])
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stderr.getvalue())['status'], 'error')


if __name__ == '__main__':
    unittest.main()
