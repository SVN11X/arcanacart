"""ARM7TDMI GBA address space; addressability does not prove pointer semantics."""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import asdict, dataclass

ROM_BASE = 0x08000000
ROM_WINDOW = 0x02000000


@dataclass(frozen=True)
class Address:
    address: int
    region: str
    canonical: int
    file_offset: int | None = None
    thumb: bool = False


def resolve(address: int, rom_size: int, *, kind: str = "data") -> Address:
    if kind not in {"data", "function"} or not 0 <= address <= 0xFFFFFFFF or rom_size < 0:
        raise ValueError("Dirección, tamaño o tipo inválido.")
    thumb = kind == "function" and bool(address & 1)
    target = address & ~1 if thumb else address
    bank = target >> 24
    if 0x08 <= bank <= 0x0D:
        offset = (target - ROM_BASE) % ROM_WINDOW
        if offset >= min(rom_size, ROM_WINDOW):
            raise ValueError("Puntero ROM fuera de los bytes disponibles.")
        return Address(address, "ROM", ROM_BASE + offset, offset, thumb)
    mirrors = {2: ("EWRAM", 0x40000), 3: ("IWRAM", 0x8000), 5: ("Palette", 0x400), 7: ("OAM", 0x400)}
    if bank in mirrors:
        name, size = mirrors[bank]
        return Address(address, name, (bank << 24) + target % size, thumb=thumb)
    if bank == 6:
        offset = target & 0x1FFFF
        if offset >= 0x18000:
            offset -= 0x8000
        return Address(address, "VRAM", 0x06000000 + offset, thumb=thumb)
    if 0x04000000 <= target < 0x04000400:
        return Address(address, "IO", target, thumb=thumb)
    if 0 <= target < 0x4000:
        return Address(address, "BIOS", target, thumb=thumb)
    raise ValueError("Dirección no soportada en el mapa GBA.")


def rom_offset(address: int, rom_size: int, *, kind: str = "data") -> int:
    resolved = resolve(address, rom_size, kind=kind)
    if resolved.file_offset is None:
        raise ValueError("La dirección no corresponde a ROM.")
    return resolved.file_offset


def align(value: int, boundary: int = 4) -> int:
    if value < 0 or boundary <= 0 or boundary & (boundary - 1):
        raise ValueError("Alineación debe ser potencia de dos y valor no negativo.")
    return (value + boundary - 1) & ~(boundary - 1)


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise ValueError("Lectura fuera de límites de ROM.")
        return self.data[offset : offset + size]

    def unpack(self, fmt: str, offset: int) -> tuple:
        if not fmt.startswith("<"):
            raise ValueError("Las estructuras GBA deben declarar little-endian (<).")
        return struct.unpack(fmt, self.read(offset, struct.calcsize(fmt)))

    def pointer(self, offset: int, *, kind: str = "data") -> Address:
        return resolve(self.unpack("<I", offset)[0], len(self.data), kind=kind)


def find_references(data: bytes, targets: Iterable[int], *, max_results: int = 100_000) -> dict:
    """Only look for references to explicitly selected ROM offsets, at word alignment."""
    if max_results < 1:
        raise ValueError("Límite de referencias debe ser positivo.")
    wanted = set(targets)
    if any(o < 0 or o >= min(len(data), ROM_WINDOW) for o in wanted):
        raise ValueError("Destino de referencia fuera de ROM.")
    results: list[dict] = []
    truncated = False
    for at in range(0, len(data) - 3, 4):
        value = struct.unpack_from("<I", data, at)[0]
        if not 0x08000000 <= value < 0x0E000000:
            continue
        offset = (value - ROM_BASE) % ROM_WINDOW
        if offset not in wanted:
            continue
        if len(results) >= max_results:
            truncated = True
            break
        target = resolve(value, len(data))
        results.append(
            {
                "location": at,
                "target_offset": offset,
                "target": asdict(target),
                "validation": "inferred",
                "evidence": ["aligned-u32-le", "selected-target-in-rom"],
                "limitation": "Coincidencia de valor; no demuestra uso como puntero en código.",
            }
        )
    return {"references": results, "truncated": truncated, "alignment": 4}


def interval_coverage(ranges: Iterable[tuple[int, int]], size: int) -> dict:
    intervals = sorted(ranges)
    merged: list[list[int]] = []
    total = 0
    for start, length in intervals:
        end = start + length
        if start < 0 or length < 0 or end > size:
            raise ValueError("Región de cobertura fuera de ROM.")
        total += length
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    covered = sum(end - start for start, end in merged)
    events: dict[int, int] = {}
    for start, length in intervals:
        events[start] = events.get(start, 0) + 1
        events[start + length] = events.get(start + length, 0) - 1
    active = 0
    previous = 0
    overlap_ranges: list[list[int]] = []
    for position in sorted(events):
        if active > 1 and position > previous:
            if overlap_ranges and overlap_ranges[-1][1] == previous:
                overlap_ranges[-1][1] = position
            else:
                overlap_ranges.append([previous, position])
        active += events[position]
        previous = position
    gaps = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append([cursor, start])
        cursor = end
    if cursor < size:
        gaps.append([cursor, size])
    return {
        "denominator_bytes": size,
        "classified_bytes": covered,
        "overlap_bytes": sum(end - start for start, end in overlap_ranges),
        "overlap_ranges": overlap_ranges,
        "duplicated_classification_bytes": total - covered,
        "unknown_bytes": size - covered,
        "classified_ranges": merged,
        "unknown_ranges": gaps,
    }
