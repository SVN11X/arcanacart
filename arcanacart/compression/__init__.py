"""Validated block decoding with explicit heuristic discovery and resource budgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import chain
from struct import unpack_from
from typing import Any

from arcanacart.core.io import digest
from arcanacart.core.memory import find_references
from feunpack.lz10 import DecodeBudget, DecodeBudgetExceeded, LZError
from feunpack.lz10 import decompress as lz10
from feunpack.lz10 import measure as measure_lz10

Decoder = Callable[[bytes, int, int, DecodeBudget | None], tuple[bytes, int]]
Measurer = Callable[[bytes, int, int, DecodeBudget | None], tuple[int, int]]


def measure_rle(
    data: bytes, offset: int = 0, max_size: int = 2_097_152, budget: DecodeBudget | None = None
) -> tuple[int, int]:
    """Check every RLE packet without expanding run or literal data."""
    if offset < 0 or offset + 4 > len(data) or data[offset] != 0x30:
        raise LZError("Cabecera RLE inválida.")
    size = int.from_bytes(data[offset + 1 : offset + 4], "little")
    if not 0 < size <= max_size:
        raise LZError("Tamaño RLE fuera de límite.")
    produced, pos = 0, offset + 4
    while produced < size:
        if budget is not None:
            budget.consume(1)
        if pos >= len(data):
            raise LZError("RLE truncado en control.")
        control = data[pos]
        count = (control & 127) + (3 if control & 128 else 1)
        pos += 1 + (1 if control & 128 else count)
        if produced + count > size or pos > len(data):
            raise LZError("RLE truncado o paquete fuera del destino.")
        produced += count
    return produced, pos - offset


def rle(
    data: bytes, offset: int = 0, max_size: int = 2_097_152, budget: DecodeBudget | None = None
) -> tuple[bytes, int]:
    """GBA BIOS RLUnComp 0x30; flags bit7 run, count=(low7)+3 or +1."""
    if offset < 0 or offset + 4 > len(data) or data[offset] != 0x30:
        raise LZError("Cabecera RLE inválida.")
    size = int.from_bytes(data[offset + 1 : offset + 4], "little")
    if not 0 < size <= max_size:
        raise LZError("Tamaño RLE fuera de límite.")
    out = bytearray()
    pos = offset + 4
    while len(out) < size:
        if pos >= len(data):
            raise LZError("RLE truncado en control.")
        control = data[pos]
        pos += 1
        count = (control & 0x7F) + (3 if control & 0x80 else 1)
        if len(out) + count > size:
            raise LZError("RLE declara un paquete que excede el destino.")
        consumed = 1 if control & 0x80 else count
        if pos + consumed > len(data):
            raise LZError("RLE truncado en datos.")
        if budget is not None:
            budget.consume(count)
        out.extend(data[pos : pos + 1] * count if control & 0x80 else data[pos : pos + count])
        pos += consumed
    return bytes(out), pos - offset


DECODERS: dict[int, tuple[str, Decoder, Measurer]] = {
    0x10: ("lz10", lz10, measure_lz10),
    0x30: ("rle", rle, measure_rle),
}


@dataclass(frozen=True)
class ScanLimits:
    max_block_bytes: int = 2_097_152
    max_decode_bytes: int = 64 * 1024 * 1024
    max_results: int = 1000
    max_candidates: int = 100_000
    step: int = 1

    def __post_init__(self) -> None:
        if (
            min(self.max_block_bytes, self.max_decode_bytes, self.max_results, self.max_candidates, self.step)
            < 1
        ):
            raise ValueError("Todos los límites de escaneo deben ser positivos.")


def referenced_offsets(
    data: bytes, start: int, limits: ScanLimits, methods: tuple[str, ...]
) -> tuple[list[int], bool]:
    """Prioritize plausible headers referenced by aligned ROM address values.

    This is heuristic evidence only. Unreferenced and unaligned data remains in
    the later linear pass; output is bounded by the configured candidate quota.
    """
    targets: set[int] = set()
    truncated = False
    for at in range(0, len(data) - 3, 4):
        address = unpack_from("<I", data, at)[0]
        if not 0x08000000 <= address < 0x0E000000:
            continue
        offset = (address - 0x08000000) % 0x02000000
        if not start <= offset < len(data) - 3 or (offset - start) % limits.step:
            continue
        entry = DECODERS.get(data[offset])
        if entry is None or entry[0] not in methods:
            continue
        if not 1 <= int.from_bytes(data[offset + 1 : offset + 4], "little") <= limits.max_block_bytes:
            continue
        if offset not in targets and len(targets) >= limits.max_candidates:
            truncated = True
            break
        targets.add(offset)
    # Smaller referenced resources first: one speculative huge block should not
    # exhaust the quota before small, strongly bounded assets are considered.
    return sorted(targets, key=lambda o: (int.from_bytes(data[o + 1 : o + 4], "little"), o)), truncated


def scan_resources(
    data: bytes, limits: ScanLimits | None = None, *, methods: tuple[str, ...] = ("lz10", "rle")
) -> tuple[list[dict], dict[str, bytes], dict]:
    limits = limits or ScanLimits()
    if not methods or set(methods) - {name for name, _, _ in DECODERS.values()}:
        raise ValueError("Método no soportado; disponibles: lz10, rle.")
    resources: list[dict] = []
    blobs: dict[str, bytes] = {}
    budget = DecodeBudget(limits.max_decode_bytes)
    # Bound unsuccessful token walks as well as actual output allocation.
    validation = DecodeBudget(max(limits.max_block_bytes * 2, limits.max_candidates * 64))
    stats: dict[str, Any] = {
        "candidate_headers": 0,
        "attempted": 0,
        "rejected": 0,
        "decoded_blocks": 0,
        "unique_outputs": 0,
        "decode_budget_used": 0,
        "decode_budget_limit": limits.max_decode_bytes,
        "decode_budget_unit": "actual-output-bytes-including-rejected-blocks",
        "attempted_declared_bytes": 0,
        "validation_budget_limit": validation.limit,
        "validation_budget_unit": "compression-tokens",
        "structurally_valid_blocks": 0,
        "header_positions_checked": 0,
        "truncated": False,
        "stop_reason": None,
        "step": limits.step,
        "scanned_through_offset": 0,
    }
    has_header = (
        len(data) >= 0xC0 and data[0xB2] == 0x96 and data[0xBD] == (-(sum(data[0xA0:0xBD]) + 0x19)) & 255
    )
    start = 0xC0 if has_header else 0
    stats["excluded_header_bytes"] = start
    positions = range(start, max(start, len(data) - 3), limits.step)
    stats["header_positions_total"] = len(positions)
    stats["rom_size_bytes"] = len(data)
    priority, reference_targets_truncated = (
        referenced_offsets(data, start, limits, methods) if has_header else ([], False)
    )
    priority_set = set(priority)
    stats.update(
        discovery_order="referenced-first-then-linear" if has_header else "linear",
        referenced_header_targets=len(priority),
        referenced_header_targets_checked=0,
        reference_target_inventory_truncated=reference_targets_truncated,
    )
    visits = chain(((True, o) for o in priority), ((False, o) for o in positions))
    for from_reference, offset in visits:
        if from_reference:
            stats["referenced_header_targets_checked"] += 1
        else:
            stats["header_positions_checked"] += 1
            stats["scanned_through_offset"] = offset
            if offset in priority_set:
                continue
        entry = DECODERS.get(data[offset])
        if entry is None or entry[0] not in methods:
            continue
        stats["candidate_headers"] += 1
        size = int.from_bytes(data[offset + 1 : offset + 4], "little")
        if not 1 <= size <= limits.max_block_bytes:
            stats["rejected"] += 1
            continue
        if len(resources) >= limits.max_results or stats["attempted"] >= limits.max_candidates:
            stats.update(truncated=True, stop_reason="result-or-candidate-limit")
            break
        stats["attempted"] += 1
        stats["attempted_declared_bytes"] += size
        method, decode, measure = entry
        try:
            measure(data, offset, limits.max_block_bytes, validation)
        except DecodeBudgetExceeded:
            stats.update(truncated=True, stop_reason="validation-budget")
            break
        except LZError:
            stats["rejected"] += 1
            continue
        stats["structurally_valid_blocks"] += 1
        try:
            blob, consumed = decode(data, offset, limits.max_block_bytes, budget)
        except DecodeBudgetExceeded:
            stats.update(truncated=True, stop_reason="decode-budget")
            break
        except LZError:
            stats["rejected"] += 1
            continue
        hash_ = digest(blob)
        blobs.setdefault(hash_, blob)
        resources.append(
            {
                "offset": offset,
                "address": 0x08000000 + offset if offset < 0x2000000 else None,
                "compression": method,
                "discovery": "referenced-header" if from_reference else "linear-header",
                "compressed_bytes": consumed,
                "decompressed_bytes": len(blob),
                "sha256": hash_,
                "encoded_sha256": digest(data[offset : offset + consumed]),
                "validation": "structural",
                "confidence": "heuristic",
                "possible_type": None,
                "evidence": ["signature", "bounded-decode", "output-size-matches-header"],
                "references": [],
                "unknown_fields": ["resource_type", "semantic_use"],
            }
        )
    # One cross-reference pass for all selected block offsets, not one ROM scan per block.
    refs = find_references(data, [r["offset"] for r in resources if r["offset"] < 0x2000000])
    by_target: dict[int, list[dict]] = {}
    for ref in refs["references"]:
        by_target.setdefault(ref["target_offset"], []).append(ref)
    for resource in resources:
        resource["references"] = by_target.get(resource["offset"], [])
    stats.update(
        decoded_blocks=len(resources),
        unique_outputs=len(blobs),
        references_truncated=refs["truncated"],
        decode_budget_used=budget.used,
        validation_budget_used=validation.used,
        search_progress_percent=(100.0 * stats["header_positions_checked"] / len(positions))
        if positions
        else 100.0,
    )
    return resources, blobs, stats
