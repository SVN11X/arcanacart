"""Reusing sealed evidence must preserve the ROM-bound extraction gate."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import test_icon_variants as fixtures
from arcanacart import icon_variants as iv
from arcanacart.core.io import digest, json_bytes


class ConfirmVariantIcons(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.VariantIcons()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.approve_candidate()
        self.previous = self.fixture.root / 'revision'
        self.out = self.fixture.root / 'confirmada'

    def confirm(self):
        return iv.confirm_review(self.previous, self.out, self.fixture.plan_path)

    def reseal(self):
        artifacts = {p.relative_to(self.previous).as_posix(): digest(p.read_bytes())
                     for p in self.previous.rglob('*') if p.is_file() and p.name != iv.STATE}
        (self.previous / iv.STATE).write_bytes(json_bytes({'status': 'completed', 'artifacts': artifacts}))

    def test_confirmation_never_reads_rom_or_air_and_preserves_source(self):
        before = {p: p.read_bytes() for p in self.previous.rglob('*') if p.is_file()}
        with patch.object(iv, 'load_rom', side_effect=AssertionError('ROM reread')):
            result = self.confirm()
        self.assertTrue(result['ready_for_full_batch'])
        self.assertEqual(result['counts'], {'verified': 2, 'pending': 0, 'error': 0})
        self.assertFalse(result['roms_rehashed'])
        self.assertFalse(result['air_files_reread'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue((self.out / 'definiciones/fe8-002.json').is_file())
        self.assertFalse((self.out / 'candidatas/fe8-002.json').exists())

    def test_confirmed_report_can_drive_real_extractor_on_synthetic_roms(self):
        self.confirm()
        self.fixture.review = self.out
        self.fixture.out = self.fixture.root / 'extraida'
        result = self.fixture.run_extract()
        self.assertEqual(result['processed_variants'], 2)
        self.assertEqual(result['icon_occurrences'], 8)

    def test_unapproved_candidates_remain_pending(self):
        self.fixture.plan['reviewed_ranges'] = {}
        self.fixture.save_plan()
        result = self.confirm()
        self.assertFalse(result['ready_for_full_batch'])
        self.assertEqual(result['counts']['pending'], 1)
        self.assertFalse((self.out / 'definiciones/fe8-002.json').exists())

    def test_resealed_resource_change_rejected_by_review_recipe(self):
        file = self.previous / 'evidencias/fe8-002/banco-candidato.bin'
        file.write_bytes(bytes(len(file.read_bytes())))
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'bytes de evidencia'):
            self.confirm()
        self.assertFalse(self.out.exists())

    def test_truncated_resource_not_accepted(self):
        file = self.previous / 'evidencias/fe8-002/banco-candidato.bin'
        file.write_bytes(file.read_bytes()[:-1])
        self.reseal()
        with self.assertRaises(ValueError):
            self.confirm()
        self.assertFalse(self.out.exists())

    def test_wrong_recipe_count_not_inferred_from_available_bytes(self):
        self.fixture.plan['reviewed_ranges']['fe8-002']['last_id'] = 4
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, 'Falta evidencia'):
            self.confirm()

    def test_definition_cannot_claim_different_geometry(self):
        path = self.previous / 'candidatas/fe8-002.json'
        value = json.loads(path.read_bytes())
        value['icon_bytes'] = 64
        path.write_bytes(json_bytes(value))
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'definición anterior'):
            self.confirm()

    def test_identity_roster_changes_require_new_local_review(self):
        self.fixture.plan['variants'][0]['variant'] = 'otro-nombre'
        self.fixture.save_plan()
        with self.assertRaisesRegex(ValueError, 'identidades'):
            self.confirm()

    def test_pinned_report_matches_and_resealed_status_change_rejected(self):
        self.fixture.plan['reviewed_source_report_sha256'] = digest((self.previous / 'revision.json').read_bytes())
        self.fixture.save_plan()
        value = json.loads((self.previous / 'revision.json').read_bytes())
        value['results'][1]['status'] = 'verified'
        (self.previous / 'revision.json').write_bytes(json_bytes(value))
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'paquete revisado'):
            self.confirm()

    def test_pinned_source_allows_original_packet(self):
        self.fixture.plan['reviewed_source_report_sha256'] = digest((self.previous / 'revision.json').read_bytes())
        self.fixture.save_plan()
        self.assertTrue(self.confirm()['ready_for_full_batch'])

    def test_output_must_be_new_and_separate(self):
        self.out = self.previous / 'nueva'
        with self.assertRaises(ValueError):
            self.confirm()
        self.out = self.previous
        with self.assertRaises(ValueError):
            self.confirm()

    def test_cli_confirmation_and_portable_zip(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = iv.main(['confirm', '--review', str(self.previous), '--out', str(self.out),
                              '--plan', str(self.fixture.plan_path), '--zip', str(self.fixture.root / 'confirmada.zip')])
        self.assertEqual(result, 0, stderr.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())['zip']['portable_paths'])


if __name__ == '__main__':
    unittest.main()
