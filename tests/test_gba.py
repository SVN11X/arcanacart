import unittest

from feunpack.gba import header_info


class HeaderTests(unittest.TestCase):
    def test_synthetic_header(self):
        data = bytearray(b"\0" * 0xC0)
        data[0xA0:0xAC] = b"FIREEMBLEM\0\0"
        data[0xAC:0xB0] = b"BE8E"
        data[0xB2] = 0x96
        data[0xBD] = (-(sum(data[0xA0:0xBD]) + 0x19)) & 255
        report = header_info(bytes(data))
        self.assertTrue(report["header_checksum_valid"])
        self.assertEqual(report["software_guess"], "FE8 USA")
