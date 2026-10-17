"""Reproducible public-domain fixtures: no bytes, names or assets from a game ROM."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

from arcanacart.core.io import atomic_json, atomic_write, digest


def fixture(profile: str = "fe8-us") -> tuple[bytes, dict]:
    if profile not in {"fe7-us", "fe8-us"}:
        raise ValueError("Perfil sintético no soportado.")
    data = bytearray(0x1000)
    data[0xA0:0xAC] = b"ARCANATEST00"
    data[0xAC:0xB0] = b"BE8E" if profile == "fe8-us" else b"AE7E"
    data[0xB0:0xB2] = b"00"
    data[0xB2] = 0x96
    data[0xBD] = (-(sum(data[0xA0:0xBD]) + 0x19)) & 255
    tables = []
    for kind, offset, size in [("Character", 0x200, 0x34), ("Class", 0x300, 0x54)]:
        tables.append({"kind": kind, "offset": offset, "count": 2, "first_id": 1})
        for i in range(2):
            at = offset + i * size
            struct.pack_into("<HH", data, at, 100 + i, 200 + i)
            data[at + 4] = i + 1
            data[at + 5] = 1 if kind == "Character" else 2
            if kind == "Character":
                data[at + 11] = 3 + i
                data[at + 12] = 0xFE  # signed -2, tests the actual binary layout
                data[at + 0x1C] = 41 + i
            else:
                data[at + 0x12] = 5 + i
                data[at + 0x13] = 61 + i
    if profile == "fe8-us":
        tables.append({"kind": "Item", "offset": 0x500, "count": 2, "first_id": 1})
        for i in range(2):
            at = 0x500 + i * 0x24
            data[at + 6] = i + 1
            data[at + 20 : at + 26] = bytes([25, 7 + i, 80, 9, 3, 0x12])
    # The same literal LZ10 content at TWO unaligned addresses; one output blob.
    block = b"\x10\x04\0\0\x00DEMO"
    data[0x701 : 0x701 + len(block)] = block
    data[0x721 : 0x721 + len(block)] = block
    rle = b"\x30\x06\0\0\x83Q"
    data[0x741 : 0x741 + len(rle)] = rle
    struct.pack_into("<I", data, 0x800, 0x08000701)
    raw = bytes(data)
    config = {
        "profile": profile,
        "rom_sha256": digest(raw),
        "evidence": ["synthetic-generated-by-ArcanaCart; not a commercial ROM"],
        "tables": tables,
    }
    return raw, config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("workspace/demo"))
    parser.add_argument("--profile", choices=["fe7-us", "fe8-us"], default="fe8-us")
    args = parser.parse_args()
    data, tables = fixture(args.profile)
    atomic_write(args.out / "synthetic.gba", data)
    atomic_json(args.out / "tables.json", tables)
    print("Fixture sintético creado. Ejecuta:")
    print(
        f'python -m arcanacart pipeline --rom "{args.out}/synthetic.gba" --profile {args.profile} --tables "{args.out}/tables.json" --out "{args.out}/analysis"'
    )


if __name__ == "__main__":
    main()
