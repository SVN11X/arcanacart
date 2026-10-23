"""Bounded GBA tile, RGB555 and text-BG renderers; no imaging dependency."""

from __future__ import annotations

import struct
import zlib

MAX_PIXELS = 1_048_576
PAGE_HEIGHT = 1024


def tile_page_plan(size_bytes: int, *, bpp: int = 4, width_tiles: int = 16) -> list[dict]:
    """Cover every complete tile; paginate only sheets exceeding the image limit."""
    if type(width_tiles) is not int or not 1 <= width_tiles <= 128:
        raise ValueError("El ancho debe ser de 1..128 tiles.")
    if bpp not in (4, 8) or size_bytes <= 0 or size_bytes % (8 * bpp):
        raise ValueError("Bloque incompatible con tiles completos.")
    tile_bytes = 8 * bpp
    count = size_bytes // tile_bytes
    columns = min(count, width_tiles)
    height = ((count + columns - 1) // columns) * 8
    capacity = count
    if columns * 8 * height > MAX_PIXELS:
        page_height = min(PAGE_HEIGHT, MAX_PIXELS // (columns * 8)) // 8 * 8
        capacity = columns * (page_height // 8)
    pages = []
    for first in range(0, count, capacity):
        length = min(capacity, count - first)
        page_columns = min(length, columns)
        pages.append(
            {
                "first_tile": first,
                "tile_count": length,
                "byte_offset": first * tile_bytes,
                "size_bytes": length * tile_bytes,
                "width": page_columns * 8,
                "height": ((length + page_columns - 1) // page_columns) * 8,
            }
        )
    return pages


def rgb555(value: int) -> tuple[int, int, int]:
    return (value & 31) * 255 // 31, ((value >> 5) & 31) * 255 // 31, ((value >> 10) & 31) * 255 // 31


def palette(raw: bytes) -> list[tuple[int, int, int]]:
    if not raw or len(raw) % 2 or len(raw) > 1024:
        raise ValueError("Paleta RGB555 requiere 2..1024 bytes y longitud par.")
    return [rgb555(value[0]) for value in struct.iter_unpack("<H", raw)]


def _size(width: int, height: int) -> None:
    if type(width) is not int or type(height) is not int or min(width, height) < 1:
        raise ValueError("Dimensiones gráficas inválidas.")
    if width * height > MAX_PIXELS:
        raise ValueError("La imagen supera el límite de 1048576 píxeles.")


def _indices(raw: bytes, bpp: int) -> list[int]:
    if bpp not in (4, 8) or not raw or len(raw) % (8 * bpp):
        raise ValueError("Se requieren tiles completos de 32 bytes (4bpp) o 64 bytes (8bpp).")
    if bpp == 8:
        return list(raw)
    return [n for value in raw for n in (value & 15, value >> 4)]


def tiles(
    raw: bytes,
    *,
    bpp: int = 4,
    width_tiles: int = 16,
    colors: list[tuple[int, int, int]] | None = None,
    palette_offset: int = 0,
    transparent_zero: bool = False,
) -> tuple[int, int, bytes]:
    if type(width_tiles) is not int or not 1 <= width_tiles <= 128:
        raise ValueError("El ancho debe ser de 1..128 tiles.")
    if bpp not in (4, 8) or not raw or len(raw) % (8 * bpp):
        raise ValueError("Bloque incompatible con tiles completos.")
    count = len(raw) // (8 * bpp)
    columns = min(count, width_tiles)
    width, height = columns * 8, ((count + columns - 1) // columns) * 8
    _size(width, height)
    indices = _indices(raw, bpp)
    if type(palette_offset) is not int or palette_offset < 0:
        raise ValueError("Índice de paleta inválido.")
    if colors is None:
        if palette_offset:
            raise ValueError("palette_offset requiere una paleta real.")
        colors = [(i * 255 // ((1 << bpp) - 1),) * 3 for i in range(1 << bpp)]
    if palette_offset + max(indices) >= len(colors):
        raise ValueError("La paleta no contiene los índices usados por estos tiles.")
    pixels = bytearray(width * height * 4)
    for tile in range(count):
        left, top = (tile % columns) * 8, (tile // columns) * 8
        for at in range(64):
            index = indices[tile * 64 + at]
            pos = ((top + at // 8) * width + left + at % 8) * 4
            pixels[pos : pos + 4] = bytes(
                (*colors[palette_offset + index], 0 if transparent_zero and not index else 255)
            )
    return width, height, bytes(pixels)


def swatches(raw: bytes) -> tuple[int, int, bytes]:
    colors = palette(raw)
    columns = min(16, len(colors))
    width, height = columns * 12, ((len(colors) + columns - 1) // columns) * 12
    pixels = bytearray(width * height * 4)
    for i, color in enumerate(colors):
        for y in range(12):
            for x in range(12):
                pos = (((i // columns) * 12 + y) * width + (i % columns) * 12 + x) * 4
                pixels[pos : pos + 4] = bytes((*color, 255))
    return width, height, bytes(pixels)


# Standard FE7/FE8 portrait OBJ arrangement. Rectangles are in 8x8 tiles:
# source x/y, width/height, destination x/y. Unused source tiles remain in the input.
PORTRAIT_RECTS = (
    (0, 0, 8, 4, 2, 0),
    (8, 0, 8, 4, 2, 4),
    (16, 0, 4, 2, 2, 8),
    (20, 0, 2, 4, 0, 6),
    (16, 2, 4, 2, 6, 8),
    (22, 0, 2, 4, 10, 6),
)


def portrait(raw: bytes, *, colors: list[tuple[int, int, int]] | None = None) -> tuple[int, int, bytes]:
    """Assemble the standard 96x80 portrait; no guessed palette or animation overlays."""
    if len(raw) not in (4096, 5120):
        raise ValueError(
            "Retrato estándar requiere 4096 o 5120 bytes; otros layouts necesitan definición propia."
        )
    width, _, sheet = tiles(raw, width_tiles=32, colors=colors, transparent_zero=True)
    output = bytearray(96 * 80 * 4)
    for sx, sy, w, h, dx, dy in PORTRAIT_RECTS:
        for y in range(h * 8):
            start = ((sy * 8 + y) * width + sx * 8) * 4
            destination = ((dy * 8 + y) * 96 + dx * 8) * 4
            output[destination : destination + w * 8 * 4] = sheet[start : start + w * 8 * 4]
    return 96, 80, bytes(output)


def bg_map(
    raw: bytes,
    tile_data: bytes,
    *,
    width_tiles: int,
    height_tiles: int,
    bpp: int = 4,
    colors: list[tuple[int, int, int]] | None = None,
    transparent_zero: bool = False,
    layout: str = "linear",
) -> tuple[int, int, bytes]:
    """Text BG only: tile index, flips and 4bpp palette bank; never FE metatiles."""
    _size(width_tiles * 8, height_tiles * 8)
    if len(raw) != width_tiles * height_tiles * 2:
        raise ValueError("Las dimensiones del mapa no corresponden al bloque de entradas u16.")
    if layout not in {"linear", "screenblocks"}:
        raise ValueError("Distribución de mapa desconocida.")
    if layout == "screenblocks" and (width_tiles not in (32, 64) or height_tiles not in (32, 64)):
        raise ValueError("Los screenblocks GBA requieren 32 o 64 tiles por dimensión.")
    indices = _indices(tile_data, bpp)
    if colors is None:
        colors = [((i % (1 << bpp)) * 255 // ((1 << bpp) - 1),) * 3 for i in range(256)]
    width, height = width_tiles * 8, height_tiles * 8
    pixels = bytearray(width * height * 4)
    for y in range(height_tiles):
        for x in range(width_tiles):
            at = y * width_tiles + x
            if layout == "screenblocks":
                at = ((y // 32) * (width_tiles // 32) + x // 32) * 1024 + (y % 32) * 32 + x % 32
            entry = struct.unpack_from("<H", raw, at * 2)[0]
            tile, bank = entry & 1023, (entry >> 12) * 16 if bpp == 4 else 0
            if (tile + 1) * 64 > len(indices):
                raise ValueError("El mapa referencia un tile inexistente en el tileset seleccionado.")
            for py in range(8):
                for px in range(8):
                    tx, ty = (7 - px if entry & 1024 else px), (7 - py if entry & 2048 else py)
                    index = indices[tile * 64 + ty * 8 + tx]
                    if bank + index >= len(colors):
                        raise ValueError("Falta un banco de paleta requerido por el mapa.")
                    pos = ((y * 8 + py) * width + x * 8 + px) * 4
                    pixels[pos : pos + 4] = bytes(
                        (*colors[bank + index], 0 if transparent_zero and index == 0 else 255)
                    )
    return width, height, bytes(pixels)


def png(width: int, height: int, rgba: bytes) -> bytes:
    _size(width, height)
    if len(rgba) != width * height * 4:
        raise ValueError("Cantidad de píxeles RGBA inválida.")

    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
        )

    rows = b"".join(b"\0" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
