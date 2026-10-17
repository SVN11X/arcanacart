"""Regression tests for concrete v0.2 data-loss risks and malicious inputs."""

import copy
import os
import stat
import struct
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from test_ups import patch_from

from arcanacart.core import io
from arcanacart.core.io import atomic_write, read_bounded
from examples.generate_synthetic import fixture
from feunpack.archives import ArchiveLimits, inspect_zip, prepare_zip
from feunpack.gba import read_rom
from feunpack.manifest import inventory
from feunpack.ups import UPSError, apply_patch, patch_file


class FilesystemSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_atomic_no_clobber(self):
        path = self.root / "result"
        path.write_bytes(b"original")
        with self.assertRaises(ValueError):
            atomic_write(path, b"new")
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob(".arcana-*")), [])

    def test_atomic_force(self):
        path = self.root / "result"
        path.write_bytes(b"old")
        atomic_write(path, b"new", force=True)
        self.assertEqual(path.read_bytes(), b"new")

    def test_race_between_check_and_publication(self):
        path = self.root / "result"
        real_link = os.link

        def racing_link(src, dst):
            Path(dst).write_bytes(b"concurrent-owner")
            real_link(src, dst)

        with patch.object(io.os, "link", side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                atomic_write(path, b"ours")
        self.assertEqual(path.read_bytes(), b"concurrent-owner")
        self.assertEqual(list(self.root.glob(".arcana-*")), [])

    def test_failure_cleanup_and_preserved_target(self):
        path = self.root / "result"
        path.write_bytes(b"old")
        with patch.object(io.os, "replace", side_effect=OSError("simulated disk error")):
            with self.assertRaises(OSError):
                atomic_write(path, b"new", force=True)
        self.assertEqual(path.read_bytes(), b"old")
        self.assertEqual(list(self.root.glob(".arcana-*")), [])

    def test_symlink_directory_refused(self):
        folder = self.root / "real"
        folder.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(folder, target_is_directory=True)
        except OSError:
            self.skipTest("Symlinks unavailable for this Windows account")
        with self.assertRaises(ValueError):
            atomic_write(link / "result", b"data")
        self.assertFalse((folder / "result").exists())

    def test_read_limit_before_allocation(self):
        path = self.root / "oversized"
        with path.open("wb") as stream:
            stream.truncate(1024 * 1024)
        with self.assertRaises(ValueError):
            read_bounded(path, 16)

    def test_read_rom_incomplete(self):
        path = self.root / "short.gba"
        path.write_bytes(b"\0" * 10)
        with self.assertRaises(ValueError):
            read_rom(path)

    def test_xml_entities_rejected(self):
        path = self.root / "listing.txt"
        path.write_text('<!DOCTYPE x [<!ENTITY a "boom">]><entrada/>')
        with self.assertRaises(ValueError):
            inventory(path)

    def test_xml_invalid_controlled_error(self):
        path = self.root / "listing.txt"
        path.write_text("<entrada")
        with self.assertRaises(ValueError):
            inventory(path)


class ZipSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = fixture()[0]
        self.path = self.root / "input.zip"

    def make_zip(self, names=("rom.gba",), compression=0):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(self.path, "w", compression=compression) as archive:
                for name in names:
                    archive.writestr(name, self.rom)

    def test_selected_traversal_rejected(self):
        for name in ["../evil.gba", "/absolute.gba", "C:\\outside.gba", "a/../../bad.gba"]:
            with self.subTest(name=name):
                self.make_zip([name])
                with self.assertRaises(ValueError):
                    inspect_zip(self.path)

    def test_duplicates_rejected(self):
        for names in [("rom.gba", "rom.gba"), ("ROM.GBA", "rom.gba")]:
            with self.subTest(names=names):
                self.make_zip(names)
                with self.assertRaisesRegex(ValueError, "duplicados"):
                    inspect_zip(self.path, "rom.gba")

    def test_explicit_selection(self):
        self.make_zip(["one.gba", "two.gba"])
        self.assertEqual(inspect_zip(self.path, "two.gba")["size_bytes"], len(self.rom))

    def test_symlink_member_rejected(self):
        info = ZipInfo("rom.gba")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with ZipFile(self.path, "w") as archive:
            archive.writestr(info, self.rom)
        with self.assertRaisesRegex(ValueError, "simbólico"):
            inspect_zip(self.path)

    def test_ratio_limit(self):
        self.make_zip(compression=ZIP_DEFLATED)
        with self.assertRaisesRegex(ValueError, "Ratio"):
            inspect_zip(self.path, limits=ArchiveLimits(max_ratio=1))

    def test_member_limit_preflight(self):
        self.make_zip(["a.gba", "b.gba"])
        with patch(
            "feunpack.archives.ZipFile", side_effect=AssertionError("must reject before loading members")
        ):
            with self.assertRaisesRegex(ValueError, "límites"):
                inspect_zip(self.path, limits=ArchiveLimits(max_members=1))

    def test_central_directory_count_lie(self):
        self.make_zip(["a.gba", "b.gba"])
        data = bytearray(self.path.read_bytes())
        eocd = data.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", data, eocd + 8, 1, 1)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Conteo"):
            inspect_zip(self.path)

    def test_corrupt_member_crc(self):
        self.make_zip()
        data = bytearray(self.path.read_bytes())
        pos = 30 + len("rom.gba")
        data[pos + 0x200] ^= 1
        self.path.write_bytes(data)
        with self.assertRaises(BadZipFile):
            inspect_zip(self.path)

    def test_truncated_zip(self):
        self.make_zip()
        self.path.write_bytes(self.path.read_bytes()[:-10])
        with self.assertRaises((ValueError, BadZipFile)):
            inspect_zip(self.path)

    def test_stale_hash_never_published(self):
        self.make_zip()
        stale = copy.deepcopy(inspect_zip(self.path))
        stale["sha256"] = "0" * 64
        out = self.root / "workspace" / "base.gba"
        with patch("feunpack.archives.inspect_zip", return_value=stale):
            with self.assertRaisesRegex(ValueError, "cambió"):
                prepare_zip(self.path, out, require_known=False)
        self.assertFalse(out.exists())
        self.assertEqual(list(out.parent.glob(".arcana-*")), [])

    def test_preserve_preexisting_manifest(self):
        self.make_zip()
        out = self.root / "base.gba"
        sidecar = self.root / "base.manifest.json"
        sidecar.write_text("owned")
        with self.assertRaises(ValueError):
            prepare_zip(self.path, out, require_known=False)
        self.assertFalse(out.exists())
        self.assertEqual(sidecar.read_text(), "owned")

    def test_force_cannot_overwrite_input(self):
        self.make_zip()
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            prepare_zip(self.path, self.path, require_known=False, force=True)
        self.assertEqual(self.path.read_bytes(), original)


class UPSSecurityTests(unittest.TestCase):
    def test_explicit_directions(self):
        source, target = b"base123", b"edited12345"
        delta = patch_from(source, target)
        self.assertEqual(apply_patch(source, delta, "forward"), (target, "forward"))
        self.assertEqual(apply_patch(target, delta, "reverse"), (source, "reverse"))
        with self.assertRaises(UPSError):
            apply_patch(source, delta, "reverse")
        with self.assertRaises(UPSError):
            apply_patch(source, delta, "bogus")

    def test_output_crc_mismatch(self):
        import zlib

        delta = bytearray(patch_from(b"base", b"edit"))
        delta[-8:-4] = b"\0" * 4
        delta[-4:] = zlib.crc32(delta[:-4]).to_bytes(4, "little")
        with self.assertRaisesRegex(UPSError, "salida"):
            apply_patch(b"base", bytes(delta))

    def test_no_inplace_even_force_or_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, delta = root / "base", root / "patch"
            base.write_bytes(b"abc")
            delta.write_bytes(patch_from(b"abc", b"abd"))
            with self.assertRaises(ValueError):
                patch_file(base, delta, base, force=True)
            alias = root / "hardlink"
            os.link(base, alias)
            with self.assertRaises(ValueError):
                patch_file(base, delta, alias, force=True)
            self.assertEqual(base.read_bytes(), b"abc")

    def test_patch_dry_run_and_metadata(self):
        from arcanacart.core.io import digest, read_json

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, delta, out = root / "base", root / "patch", root / "out"
            base.write_bytes(b"abc")
            delta.write_bytes(patch_from(b"abc", b"abd-extra"))
            patch_file(base, delta, out, dry_run=True)
            self.assertFalse(out.exists())
            result = patch_file(base, delta, out)
            self.assertEqual(result["target_sha256"], digest(out.read_bytes()))
            self.assertEqual(read_json(root / "out.patch.json")["changed_bytes"], 7)
            self.assertEqual(base.read_bytes(), b"abc")
            with self.assertRaises(ValueError):
                patch_file(base, delta, out)

    def test_write_failure_never_modifies_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, delta, out = root / "base", root / "patch", root / "out"
            base.write_bytes(b"abc")
            delta.write_bytes(patch_from(b"abc", b"abd"))
            with patch("feunpack.ups.atomic_write", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    patch_file(base, delta, out)
            self.assertEqual(base.read_bytes(), b"abc")
            self.assertFalse(out.exists())

    def test_deterministic_roundtrip_corpus(self):
        import random

        rand = random.Random(20261016)
        for length in [0, 1, 2, 127, 128, 1024]:
            source = rand.randbytes(length)
            target = rand.randbytes(max(0, length - 3)) + b"synthetic"
            delta = patch_from(source, target)
            with self.subTest(length=length):
                self.assertEqual(apply_patch(source, delta)[0], target)
                self.assertEqual(apply_patch(target, delta)[0], source)

    def test_invalid_xor_run_with_valid_patch_crc(self):
        import zlib

        delta = bytearray(patch_from(b"abc", b"abd"))
        # Body starts at byte 6; change its relative offset from 2 to 10.
        delta[6] = 0x8A
        delta[-4:] = zlib.crc32(delta[:-4]).to_bytes(4, "little")
        with self.assertRaisesRegex(UPSError, "fuera"):
            apply_patch(b"abc", bytes(delta))
