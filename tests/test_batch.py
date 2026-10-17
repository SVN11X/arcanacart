"""Batch integration uses original synthetic ROMs and independently generated UPS."""

import contextlib
import copy
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from test_ups import patch_from

from arcanacart.batch import (
    DEFAULT_CONFIG,
    DEFAULT_INPUTS,
    import_inputs,
    init_workspace,
    local_path,
    run_batch,
    validate_config,
)
from arcanacart.cli import main
from arcanacart.core.io import atomic_json
from arcanacart.patchsets import canonical_id, catalog_patchset, copy_verified, file_hash, read_patch
from examples.generate_synthetic import fixture
from feunpack.archives import ArchiveLimits

PALADIN = "FE7Remastered/FE7URemaster X QoL Final - Paladin Special.PATCH.20251026165125.ups"
VISUAL = "FE7Remastered/FE7URemaster.PATCH.20230114165323.ups"
CASUAL = "FE7Remastered/Fun Emblem 7/PME Nayru/FE7U PME Nayru CASUAL.PATCH.20260823150604.ups"
FULL = "Sacred Trilogy 2.1.3 Full Version.ups"
LITE = "Sacred Trilogy 2.1.3 Lite Version.ups"
LEGACY = "Legacy Versions Sacred Trilogy/Sacred Trilogy 2.1.2 Full Version.ups"


def create_inputs(root):
    config_path = root / "private/fire-emblem.json"
    init_workspace(root, config_path)
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["allow_unknown_bases"] = True
    atomic_json(config_path, config, force=True)
    bases = {}
    for game, members in [("fe7", [PALADIN, VISUAL, CASUAL]), ("fe8", [FULL, LITE, LEGACY])]:
        raw, _ = fixture(game + "-us")
        bases[game] = raw
        with ZipFile(root / DEFAULT_INPUTS[game + "_rom"], "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("original filename [!].gba", raw)
        with ZipFile(root / DEFAULT_INPUTS[game + "_mods"], "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("Readme.txt", "Synthetic fixture; not copied from a game.")
            for i, name in enumerate(members):
                target = raw[:0x250] + bytes([11 + i]) + raw[0x251:]
                archive.writestr(name, patch_from(raw, target))
    return config_path, config, bases


class NamingAndPatchsetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path, self.config, self.bases = create_inputs(self.root)

    def test_resource_quota_makes_batch_partial_without_marking_patches_failed(self):
        self.config["scan_limits"]["max_decode_bytes"] = 4
        atomic_json(self.path, self.config, force=True)
        result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(all(job["status"] == "partial" for job in result["jobs"]))
        self.assertTrue(all(job["scan_truncated"] for job in result["jobs"]))

    def test_canonical_names_preserve_version_and_timestamp(self):
        self.assertEqual(canonical_id("fe7", PALADIN), DEFAULT_CONFIG["selection"]["fe7"][0])
        self.assertEqual(canonical_id("fe8", FULL), "fe8-usa-sacred-trilogy-2.1.3-full")
        self.assertEqual(canonical_id("fe8", LEGACY), "fe8-usa-legacy-sacred-trilogy-2.1.2-full")
        self.assertIn("pme-nayru-casual-20260823t150604", canonical_id("fe7", CASUAL))

    def test_legacy_grows_flags_and_long_names(self):
        name = "Legacy Versions Sacred Trilogy/Sacred Trilogy - Full - Fixed Growths - With AI.ups"
        self.assertEqual(
            canonical_id("fe8", name), "fe8-usa-legacy-sacred-trilogy-full-fixed-growths-with-ai"
        )
        self.assertIn("-legacy-", canonical_id("fe7", "(Antiguo) FE7U PME Nayru.PATCH.20260614125706.ups"))
        self.assertLessEqual(len(canonical_id("fe7", "FE7U " + "Name" * 60 + ".ups")), 110)

    def test_catalog_does_not_extract_anything(self):
        source = self.root / DEFAULT_INPUTS["fe7_mods"]
        before = set(self.root.rglob("*"))
        catalog = catalog_patchset(source, "fe7")
        self.assertEqual(catalog["count"], 3)
        self.assertEqual(set(self.root.rglob("*")), before)
        self.assertEqual(catalog["archive_sha256"], file_hash(source))

    def test_read_selected_ups_crc(self):
        source = self.root / DEFAULT_INPUTS["fe8_mods"]
        catalog = catalog_patchset(source, "fe8")
        record = next(e for e in catalog["entries"] if e["member"] == FULL)
        data, meta = read_patch(source, catalog, record)
        self.assertTrue(data.startswith(b"UPS1"))
        self.assertEqual(meta["source_size"], 4096)

    def test_changed_patch_archive_refused(self):
        source = self.root / DEFAULT_INPUTS["fe8_mods"]
        catalog = catalog_patchset(source, "fe8")
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            read_patch(source, catalog, catalog["entries"][0])

    def test_unsafe_members_duplicates_symlink(self):
        source = self.root / "malicious.zip"
        raw = patch_from(b"base", b"edit")
        for names in [["../evil.ups"], ["/evil.ups"], ["C:\\evil.ups"], ["same.ups", "SAME.UPS"]]:
            with self.subTest(names=names):
                with ZipFile(source, "w") as archive:
                    for name in names:
                        archive.writestr(name, raw)
                with self.assertRaises(ValueError):
                    catalog_patchset(source, "fe7")
        info = ZipInfo("symlink.ups")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with ZipFile(source, "w") as archive:
            archive.writestr(info, raw)
        with self.assertRaises(ValueError):
            catalog_patchset(source, "fe7")

    def test_total_expansion_guard_and_no_ups(self):
        source = self.root / DEFAULT_INPUTS["fe7_mods"]
        with self.assertRaises(ValueError):
            catalog_patchset(source, "fe7", ArchiveLimits(max_total_bytes=1))
        empty = self.root / "empty.zip"
        with ZipFile(empty, "w") as archive:
            archive.writestr("listing.txt", "not binary UPS")
        with self.assertRaises(ValueError):
            catalog_patchset(empty, "fe7")

    def test_slug_collisions_are_disambiguated(self):
        source = self.root / "collision.zip"
        with ZipFile(source, "w") as archive:
            archive.writestr("A-one.ups", patch_from(b"abc", b"abd"))
            archive.writestr("B/A one.ups", patch_from(b"abc", b"abe"))
        catalog = catalog_patchset(source, "fe7")
        self.assertEqual(len({e["id"] for e in catalog["entries"]}), 2)


class BatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path, self.config, self.bases = create_inputs(self.root)

    def test_four_default_projects_and_independent_sources(self):
        before = {key: file_hash(self.root / name) for key, name in DEFAULT_INPUTS.items()}
        result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["job_count"], 4)
        self.assertEqual(sum(j["kind"] == "mod" for j in result["jobs"]), 2)
        for game in ["fe7", "fe8"]:
            base = next(j for j in result["jobs"] if j["id"] == game + "-base")
            mod = next(j for j in result["jobs"] if j["game"] == game and j["kind"] == "mod")
            self.assertNotEqual(base["rom_sha256"], mod["rom_sha256"])
            sidecar = self.root / (mod["prepared"] + ".patch.json")
            self.assertEqual(json.loads(sidecar.read_text())["base_sha256"], base["rom_sha256"])
            self.assertGreater(mod["changed_bytes"], 0)
        for key, name in DEFAULT_INPUTS.items():
            self.assertEqual(file_hash(self.root / name), before[key])
        workspace = self.root / "workspace/fire-emblem"
        self.assertTrue((workspace / "index.html").is_file())
        self.assertEqual(json.loads((workspace / "batch-report.json").read_text())["status"], "completed")

    def test_all_variants_includes_legacy(self):
        result = run_batch(self.root, self.path, all_variants=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["job_count"], 8)
        self.assertTrue(any("legacy-" in j["id"] for j in result["jobs"]))

    def test_resume_reuses_patches_and_pipeline(self):
        run_batch(self.root, self.path)
        with patch("arcanacart.batch.patch_file", side_effect=AssertionError("must reuse verified output")):
            result = run_batch(self.root, self.path, resume=True)
        self.assertEqual(result["status"], "completed", result)
        self.assertTrue(all(j["cache_hit"] for j in result["jobs"]))
        self.assertTrue(all(j["patch_reused"] for j in result["jobs"] if j["kind"] == "mod"))

    def test_catalog_only_needs_no_rom(self):
        (self.root / DEFAULT_INPUTS["fe7_rom"]).unlink()
        (self.root / DEFAULT_INPUTS["fe8_rom"]).unlink()
        result = run_batch(self.root, self.path, catalog_only=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["job_count"], 2)
        self.assertEqual(list((self.root / "private/prepared").rglob("*.gba")), [])

    def test_game_filter_does_not_touch_other_inputs(self):
        (self.root / DEFAULT_INPUTS["fe8_rom"]).unlink()
        (self.root / DEFAULT_INPUTS["fe8_mods"]).unlink()
        result = run_batch(self.root, self.path, game="fe7")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["job_count"], 2)

    def test_dry_run_no_outputs_or_patches_written(self):
        before = set(self.root.rglob("*"))
        result = run_batch(self.root, self.path, dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(set(self.root.rglob("*")), before)
        self.assertEqual(result["job_count"], 4)

    def test_unknown_base_requires_explicit_config(self):
        self.config["allow_unknown_bases"] = False
        atomic_json(self.path, self.config, force=True)
        result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(sum(j["status"] == "failed" for j in result["jobs"]), 2)
        self.assertEqual(sum(j["status"] == "blocked" for j in result["jobs"]), 2)

    def test_crc_mismatch_records_failure_and_continues_other_game(self):
        source = self.root / DEFAULT_INPUTS["fe7_mods"]
        with ZipFile(source, "w") as archive:
            archive.writestr(PALADIN, patch_from(b"wrong", b"base"))
        result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "partial")
        failed = next(j for j in result["jobs"] if j["game"] == "fe7" and j["kind"] == "mod")
        self.assertIn("CRC32", failed["error"])
        self.assertTrue(all(j["status"] == "completed" for j in result["jobs"] if j["game"] == "fe8"))

    def test_missing_selection_has_actionable_catalog(self):
        self.config["selection"]["fe7"] = ["fe7-unknown-variant"]
        atomic_json(self.path, self.config, force=True)
        result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "partial")
        job = next(j for j in result["jobs"] if j["id"] == "fe7-mod-package")
        self.assertIn("catalog.json", job["error"])
        self.assertTrue((self.root / "workspace/fire-emblem/catalog.json").exists())

    def test_no_selection_runs_only_bases(self):
        self.config["selection"] = {"fe7": [], "fe8": []}
        atomic_json(self.path, self.config, force=True)
        result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["job_count"], 2)

    def test_corrupted_generated_rom_is_not_overwritten(self):
        result = run_batch(self.root, self.path)
        mod = next(j for j in result["jobs"] if j["kind"] == "mod")
        output = self.root / mod["prepared"]
        output.write_bytes(b"corrupted")
        result = run_batch(self.root, self.path, resume=True)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(output.read_bytes(), b"corrupted")

    def test_scan_config_change_creates_new_analysis_namespace(self):
        first = run_batch(self.root, self.path)
        second = run_batch(self.root, self.path, resume=True, no_scan=True)
        self.assertEqual(second["status"], "completed", second)
        self.assertNotEqual(first["jobs"][0]["report"], second["jobs"][0]["report"])
        self.assertTrue((self.root / "workspace/fire-emblem" / first["jobs"][0]["report"]).exists())

    def test_tables_are_hash_bound_per_variant(self):
        # Independently specify only BASE layouts for this synthetic verification.
        for game in ["fe7", "fe8"]:
            _, tables = fixture(game + "-us")
            name = f"private/tables/{game}.json"
            atomic_json(self.root / name, tables)
            self.config["tables"][game + "-base"] = name
        atomic_json(self.path, self.config, force=True)
        result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "completed", result)
        for job in result["jobs"]:
            doc = json.loads((self.root / "workspace/fire-emblem" / job["air"]).read_text())
            records = [e for e in doc["entities"] if e["kind"] == "Character"]
            self.assertEqual(len(records), 2 if job["kind"] == "base" else 0)

    def test_batch_lock_refuses_concurrent_writer(self):
        lock = self.root / "workspace/fire-emblem/.arcanacart.lock"
        lock.write_text("other process")
        with self.assertRaisesRegex(ValueError, "bloqueo"):
            run_batch(self.root, self.path)
        self.assertEqual(lock.read_text(), "other process")

    def test_core_batch_needs_no_network_or_subprocess(self):
        with (
            patch("socket.socket", side_effect=AssertionError("no network")),
            patch("subprocess.run", side_effect=AssertionError("no process")),
        ):
            result = run_batch(self.root, self.path)
        self.assertEqual(result["status"], "completed")


class BatchConfigurationAndImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path, self.config, self.bases = create_inputs(self.root)

    def test_init_preserves_modified_config(self):
        self.config["selection"]["fe7"] = []
        atomic_json(self.path, self.config, force=True)
        init_workspace(self.root, self.path)
        self.assertEqual(json.loads(self.path.read_text())["selection"]["fe7"], [])

    def test_init_dry_run_writes_nothing(self):
        root = self.root / "new-project"
        config = root / "private/fire-emblem.json"
        result = init_workspace(root, config, dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertFalse(root.exists())

    def test_config_rejects_escape_and_symlink(self):
        for relative in ["../escape", "/absolute", "C:/outside", "private/../outside", "private\\wrong"]:
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                local_path(self.root, relative)
        target = self.root / "target"
        target.mkdir()
        link = self.root / "private/link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink permission unavailable")
        with self.assertRaises(ValueError):
            local_path(self.root, "private/link/output")

    def test_bad_config_types_controlled(self):
        for key, value in [("scan", "true"), ("scan_limits", {}), ("selection", {"fe7": []}), ("tables", [])]:
            bad = copy.deepcopy(self.config)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(bad, self.root)
        bad = copy.deepcopy(self.config)
        bad["inputs"]["fe8_rom"] = bad["inputs"]["fe7_rom"]
        with self.assertRaises(ValueError):
            validate_config(bad, self.root)

    def test_import_mods_canonical_copy_original_preserved(self):
        source = self.root / DEFAULT_INPUTS["fe7_mods"]
        original_hash = file_hash(source)
        target = self.root / "new-project"
        result = import_inputs(target, {"fe7_mods": source})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(file_hash(source), original_hash)
        self.assertEqual(file_hash(target / DEFAULT_INPUTS["fe7_mods"]), original_hash)
        repeat = import_inputs(target, {"fe7_mods": source})
        self.assertTrue(repeat["entries"][0]["already_present"])

    def test_import_dry_run_and_bad_format(self):
        source = self.root / DEFAULT_INPUTS["fe8_mods"]
        target = self.root / "dry"
        result = import_inputs(target, {"fe8_mods": source}, dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertFalse(target.exists())
        txt = self.root / "code2text.txt"
        txt.write_text("listing only")
        with self.assertRaisesRegex(ValueError, "TXT"):
            import_inputs(target, {"fe8_mods": txt})

    def test_import_rejects_unknown_rom_and_existing_different_file(self):
        source = self.root / DEFAULT_INPUTS["fe7_rom"]
        with self.assertRaisesRegex(ValueError, "SHA-1"):
            import_inputs(self.root / "unknown", {"fe7_rom": source})
        target = self.root / "existing"
        dest = target / DEFAULT_INPUTS["fe7_mods"]
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"owned")
        with self.assertRaises(ValueError):
            import_inputs(target, {"fe7_mods": self.root / DEFAULT_INPUTS["fe7_mods"]})
        self.assertEqual(dest.read_bytes(), b"owned")

    def test_import_no_partial_copy_after_late_preflight_error(self):
        target = self.root / "import"
        missing = self.root / "missing.zip"
        with self.assertRaises(ValueError):
            import_inputs(target, {"fe7_mods": self.root / DEFAULT_INPUTS["fe7_mods"], "fe8_mods": missing})
        self.assertFalse(target.exists())

    def test_copy_hash_failure_cleanup(self):
        source = self.root / "source.zip"
        source.write_bytes(b"data")
        dest = self.root / "destination.zip"
        with patch("arcanacart.patchsets.file_hash", return_value="0" * 64):
            with self.assertRaises(ValueError):
                copy_verified(source, dest)
        self.assertFalse(dest.exists())
        self.assertEqual(list(self.root.glob(".arcana-*")), [])

    def test_cli_init_catalog_and_partial_exit(self):
        def call(args):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(list(map(str, args)))
            return code, stdout.getvalue(), stderr.getvalue()

        code, _, error = call(["batch", "--root", self.root, "--init"])
        self.assertEqual(code, 0, error)
        code, text, error = call(["batch", "--root", self.root, "--catalog-only"])
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(text)["job_count"], 2)
        (self.root / DEFAULT_INPUTS["fe8_rom"]).unlink()
        code, text, error = call(["batch", "--root", self.root])
        self.assertEqual(code, 3, error)
        self.assertEqual(json.loads(text)["status"], "partial")

    def test_foreign_workspace_index_is_preserved(self):
        workspace = self.root / "workspace/fire-emblem"
        (workspace / "index.html").write_text("owned by another project")
        with self.assertRaisesRegex(ValueError, "ajenas"):
            run_batch(self.root, self.path)
        self.assertEqual((workspace / "index.html").read_text(), "owned by another project")

    def test_foreign_batch_marker_is_preserved(self):
        marker = self.root / "workspace/fire-emblem/batch-report.json"
        marker.write_text('{"format":"other-app"}')
        with self.assertRaisesRegex(ValueError, "ajeno"):
            run_batch(self.root, self.path)
        self.assertEqual(json.loads(marker.read_text())["format"], "other-app")
