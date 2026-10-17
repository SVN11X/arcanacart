import unittest
import zlib

from feunpack.ups import UPSError, apply_patch, parse_info


def number(x: int) -> bytes:
    o = bytearray()
    while True:
        b = x & 127
        x >>= 7
        if x == 0:
            o.append(b | 128)
            return bytes(o)
        o.append(b)
        x -= 1


def patch_from(source: bytes, target: bytes) -> bytes:
    a, b = source, target
    n = max(len(a), len(b))
    a = a.ljust(n, b"\0")
    b = b.ljust(n, b"\0")
    p = bytearray(b"UPS1" + number(len(source)) + number(len(target)))
    cursor = 0
    idx = 0
    while idx < n:
        if a[idx] == b[idx]:
            idx += 1
            continue
        start = idx
        p += number(start - cursor)
        while idx < n and a[idx] != b[idx]:
            p.append(a[idx] ^ b[idx])
            idx += 1
        p.append(0)
        cursor = idx + 1
    p += zlib.crc32(source).to_bytes(4, "little")
    p += zlib.crc32(target).to_bytes(4, "little")
    p += zlib.crc32(p).to_bytes(4, "little")
    return bytes(p)


class UPSTests(unittest.TestCase):
    def test_forward_reverse(self):
        source = b"GBA!" + (b"abcd" * 70)
        target = source[:40] + b"changed" + source[47:] + b"added!"
        patch = patch_from(source, target)
        self.assertEqual(parse_info(patch)["source_size"], len(source))
        self.assertEqual(apply_patch(source, patch), (target, "forward"))
        self.assertEqual(apply_patch(target, patch), (source, "reverse"))

    def test_reject_bad_base(self):
        patch = patch_from(b"abc", b"abd")
        with self.assertRaises(UPSError):
            apply_patch(b"abe", patch)

    def test_reject_corrupt_patch(self):
        patch = bytearray(patch_from(b"abc", b"abd"))
        patch[-1] ^= 1
        with self.assertRaises(UPSError):
            parse_info(bytes(patch))

    def test_shrinks(self):
        a = b"abcde\0\0\0"
        b = b"abcde"
        patch = patch_from(a, b)
        self.assertEqual(apply_patch(a, patch)[0], b)
        self.assertEqual(apply_patch(b, patch)[0], a)
