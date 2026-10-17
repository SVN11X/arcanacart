"""GBA BIOS LZ10 (0x10) decompressor and conservative scanner."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


class LZError(ValueError):
    pass


class DecodeBudgetExceeded(LZError):
    """A shared work/output quota was reached before the next operation."""


@dataclass
class DecodeBudget:
    limit: int
    used: int = 0

    def consume(self, count: int) -> None:
        if self.used + count > self.limit:
            raise DecodeBudgetExceeded("Presupuesto de trabajo agotado.")
        self.used += count


def measure(
    data: bytes, offset: int = 0, max_size: int = 2_097_152, budget: DecodeBudget | None = None
) -> tuple[int, int]:
    """Validate references and input bounds without allocating the claimed output.

    The optional budget counts actual token visits, separately from output bytes.
    LZ10 reference validity depends on the produced length, not on byte values.
    """
    if offset < 0 or offset + 4 > len(data) or data[offset] != 0x10:
        raise LZError("No se encuentra cabecera LZ10 (0x10) en ese offset.")
    size = int.from_bytes(data[offset + 1 : offset + 4], "little")
    if not 0 < size <= max_size:
        raise LZError("Tamaño LZ10 cero o fuera del límite configurado.")
    produced, pos = 0, offset + 4
    while produced < size:
        if pos >= len(data):
            raise LZError("LZ10 truncado en los flags.")
        flags = data[pos]
        pos += 1
        for bit in range(7, -1, -1):
            if produced >= size:
                break
            if budget is not None:
                budget.consume(1)
            if flags & (1 << bit):
                if pos + 2 > len(data):
                    raise LZError("LZ10 truncado en referencia.")
                first, second = data[pos], data[pos + 1]
                pos += 2
                distance = (((first & 15) << 8) | second) + 1
                if distance > produced:
                    raise LZError("Referencia LZ10 retrocede fuera del búfer.")
                produced += min((first >> 4) + 3, size - produced)
            else:
                if pos >= len(data):
                    raise LZError("LZ10 truncado en literal.")
                pos += 1
                produced += 1
    return produced, pos - offset


def decompress(
    data: bytes, offset: int = 0, max_size: int = 2_097_152, budget: DecodeBudget | None = None
) -> tuple[bytes, int]:
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
                count = min(length, out_size - len(out))
                if budget is not None:
                    budget.consume(count)
                for _ in range(count):
                    out.append(out[-distance])
            else:
                if p >= len(data):
                    raise LZError("LZ10 truncado en literal.")
                if budget is not None:
                    budget.consume(1)
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
    budget = DecodeBudget(max_total_bytes)
    validation = DecodeBudget(max(max_size * 2, 6_400_000))
    for offset in range(0, len(data) - 3, step):
        if data[offset] != 0x10:
            continue
        length = int.from_bytes(data[offset + 1 : offset + 4], "little")
        if not 4 <= length <= max_size:
            continue
        try:
            measure(data, offset, max_size, validation)
            blob, encoded_size = decompress(data, offset, max_size=max_size, budget=budget)
        except DecodeBudgetExceeded:
            break
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
