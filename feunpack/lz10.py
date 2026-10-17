"""GBA BIOS LZ10 (0x10) decompressor and conservative scanner."""

from __future__ import annotations

import hashlib


class LZError(ValueError):
    pass


def decompress(data: bytes, offset: int = 0, max_size: int = 2_097_152) -> tuple[bytes, int]:
    if offset < 0 or offset + 4 > len(data) or data[offset] != 0x10:
        raise LZError("No se encuentra cabecera LZ10 (0x10) en ese offset.")
    out_size = int.from_bytes(data[offset + 1 : offset + 4], "little")
    if out_size == 0 or out_size > max_size:
        raise LZError("Tamaño LZ10 cero o fuera del límite configurado.")
    out = bytearray()
    p = offset + 4
    while len(out) < out_size:
        if p >= len(data):
            raise LZError("LZ10 truncado en los flags.")
        flags = data[p]
        p += 1
        for bit in range(7, -1, -1):
            if len(out) >= out_size:
                break
            if flags & (1 << bit):
                if p + 2 > len(data):
                    raise LZError("LZ10 truncado en referencia.")
                a, b = data[p], data[p + 1]
                p += 2
                length = (a >> 4) + 3
                distance = (((a & 0xF) << 8) | b) + 1
                if distance > len(out):
                    raise LZError("Referencia LZ10 retrocede fuera del búfer.")
                for _ in range(min(length, out_size - len(out))):
                    out.append(out[-distance])
            else:
                if p >= len(data):
                    raise LZError("LZ10 truncado en literal.")
                out.append(data[p])
                p += 1
    return bytes(out), p - offset


def scan(
    data: bytes,
    max_size: int = 2_097_152,
    max_results: int = 100,
    step: int = 1,
    max_total_bytes: int = 64 * 1024 * 1024,
) -> list[dict]:
    if step < 1 or max_results < 1 or max_total_bytes < 1 or max_size < 1:
        raise ValueError("step y max_results deben ser >= 1")
    found = []
    remaining = max_total_bytes
    for offset in range(0, len(data) - 3, step):
        if data[offset] != 0x10:
            continue
        length = int.from_bytes(data[offset + 1 : offset + 4], "little")
        if not 4 <= length <= max_size:
            continue
        if length > remaining:
            break
        remaining -= length  # Bound attempted decoding, including rejected candidates.
        try:
            blob, encoded_size = decompress(data, offset, max_size=max_size)
        except LZError:
            continue
        found.append(
            {
                "rom_offset": f"0x{offset:08X}",
                "encoded_bytes": encoded_size,
                "decoded_bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "_bytes": blob,
            }
        )
        if len(found) >= max_results:
            break
    return found
