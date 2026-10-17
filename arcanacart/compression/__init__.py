"""Validated block decoding with explicit heuristic discovery and resource budgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arcanacart.core.io import digest
from arcanacart.core.memory import find_references
from feunpack.lz10 import LZError
from feunpack.lz10 import decompress as lz10

Decoder = Callable[[bytes, int, int], tuple[bytes, int]]


def rle(data: bytes, offset: int = 0, max_size: int = 2_097_152) -> tuple[bytes, int]:
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
        out.extend(data[pos : pos + 1] * count if control & 0x80 else data[pos : pos + count])
        pos += consumed
    return bytes(out), pos - offset


DECODERS: dict[int, tuple[str, Decoder]] = {0x10: ("lz10", lz10), 0x30: ("rle", rle)}


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


def scan_resources(
    data: bytes, limits: ScanLimits | None = None, *, methods: tuple[str, ...] = ("lz10", "rle")
) -> tuple[list[dict], dict[str, bytes], dict]:
    limits = limits or ScanLimits()
    if not methods or set(methods) - {name for name, _ in DECODERS.values()}:
        raise ValueError("Método no soportado; disponibles: lz10, rle.")
    resources: list[dict] = []
    blobs: dict[str, bytes] = {}
    stats: dict[str, Any] = {
        "candidate_headers": 0,
        "attempted": 0,
        "rejected": 0,
        "decoded_blocks": 0,
        "unique_outputs": 0,
        "decode_budget_used": 0,
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
    for offset in range(start, len(data) - 3, limits.step):
        stats["scanned_through_offset"] = offset
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
        if stats["decode_budget_used"] + size > limits.max_decode_bytes:
            stats.update(truncated=True, stop_reason="decode-budget")
            break
        stats["attempted"] += 1
        stats["decode_budget_used"] += size
        method, decode = entry
        try:
            blob, consumed = decode(data, offset, limits.max_block_bytes)
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
        decoded_blocks=len(resources), unique_outputs=len(blobs), references_truncated=refs["truncated"]
    )
    return resources, blobs, stats
