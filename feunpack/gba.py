"""Minimal read-only validation of Game Boy Advance cartridge headers."""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path

from arcanacart.core.io import read_bounded

KNOWN_US_ROMS = {
    "c735fdbb9e8abe19e0c6a44708df19acc962e204": {
        "game": "Fire Emblem 7 (USA)",
        "profile": "fe7-us",
        "repo": "https://github.com/StanHash/fe7_us",
        "filename": "fe7/baserom.gba",
    },
    "c25b145e37456171ada4b0d440bf88a19f4d509f": {
        "game": "Fire Emblem 8 (USA)",
        "profile": "fe8-us",
        "repo": "https://github.com/FireEmblemUniverse/fireemblem8u",
        "filename": "fe8/baserom.gba",
    },
}

MAX_ROM_SIZE = 64 * 1024 * 1024


class GBAError(ValueError):
    pass


def read_rom(path: str | Path) -> bytes:
    try:
        return read_bounded(path, MAX_ROM_SIZE, 0xC0)
    except ValueError as exc:
        raise GBAError(str(exc)) from exc


def header_info(data: bytes) -> dict:
    if len(data) < 0xC0:
        raise GBAError("Cabecera GBA incompleta.")
    title = data[0xA0:0xAC].rstrip(b"\x00 ").decode("ascii", "replace")
    code = data[0xAC:0xB0].decode("ascii", "replace")
    maker = data[0xB0:0xB2].decode("ascii", "replace")
    header_checksum = (-(sum(data[0xA0:0xBD]) + 0x19)) & 0xFF
    code_match = {"AE7E": "FE7 USA", "AE7J": "FE7 Japón", "BE8E": "FE8 USA", "BE8J": "FE8 Japón"}.get(code)
    return {
        "type": "gba",
        "size_bytes": len(data),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "crc32": f"{zlib.crc32(data):08x}",
        "title": title,
        "game_code": code,
        "maker_code": maker,
        "gba_fixed_0x96": data[0xB2] == 0x96,
        "header_checksum_valid": header_checksum == data[0xBD],
        "header_checksum_stored": data[0xBD],
        "header_checksum_expected": header_checksum,
        "software_guess": code_match,
        "header_version": data[0xBC],
        "region_hint": {"E": "USA", "J": "Japón", "P": "Europa"}.get(code[-1:], "desconocida"),
        "reserved_bytes_zero": not any(data[0xB5:0xBC]) and not any(data[0xBE:0xC0]),
        "standard_rom_window": len(data) <= 32 * 1024 * 1024,
        "reference": KNOWN_US_ROMS.get(hashlib.sha1(data).hexdigest()),
        "verification": "exact-reference"
        if hashlib.sha1(data).hexdigest() in KNOWN_US_ROMS
        else "unknown-or-modified",
        "warning": "Game code and header are hints, not proof of a clean or licensed ROM. Check SHA1 and patch CRC.",
    }
