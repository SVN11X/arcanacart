"""Generate original synthetic graphics, run extraction and create an offline gallery."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

from arcanacart.core.io import atomic_json, atomic_write, digest, read_json
from arcanacart.interpret import interpret
from arcanacart.pipeline import pipeline
from examples.generate_synthetic import fixture


def literal_lz(raw: bytes) -> bytes:
    return (
        b"\x10"
        + len(raw).to_bytes(3, "little")
        + b"".join(b"\0" + raw[i : i + 8] for i in range(0, len(raw), 8))
    )


def generate(out: Path) -> dict:
    raw, tables = fixture()
    data = bytearray(raw)
    pixels = bytearray()
    for tile in range(64):
        for y in range(8):
            for x in range(0, 8, 2):
                a = ((x + y + tile) % 15) + 1
                b = ((x + y + tile + 1) % 15) + 1
                pixels.append(a | (b << 4))
    colors = struct.pack(
        "<16H", *[((i * 2) & 31) | (((31 - i * 2) & 31) << 5) | ((i & 31) << 10) for i in range(16)]
    )
    tilemap = struct.pack("<1024H", *[(i % 64) | (1024 if i % 3 == 0 else 0) for i in range(1024)])
    for block in (bytes(pixels), colors, tilemap):
        data += b"\xff" * 17 + literal_lz(block)
    tables["rom_sha256"] = digest(data)
    rom = out / "synthetic-graphics.gba"
    atomic_write(rom, bytes(data))
    atomic_json(out / "tables.json", tables)
    analysis = out / "analysis"
    pipeline(rom, analysis, profile="fe8-us", tables=tables, compression_methods=("lz10",))
    interpret(analysis / "air.json", out / "initial-gallery", max_previews=100)
    recipes = read_json(out / "initial-gallery/recipes.json")
    recipes["resources"][digest(bytes(pixels))].update(
        mode="tiles", palette_sha256=digest(colors), width_tiles=8
    )
    recipes["resources"][digest(tilemap)].update(
        mode="bg-map",
        tiles_sha256=digest(bytes(pixels)),
        palette_sha256=digest(colors),
        width_tiles=32,
        height_tiles=32,
        map_layout="screenblocks",
    )
    atomic_json(out / "demo-recipes.json", recipes)
    return interpret(
        analysis / "air.json", out / "gallery", recipes=out / "demo-recipes.json", max_previews=100
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(generate(args.out))


if __name__ == "__main__":
    main()
