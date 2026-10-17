"""Strict UPS1 patch inspection and application (including reversible patches)."""

from __future__ import annotations

import zlib
from pathlib import Path

from arcanacart.core.io import (
    atomic_json,
    atomic_write,
    check_destination,
    digest,
    protect_inputs,
    read_bounded,
)

MAX_SIZE = 64 * 1024 * 1024


class UPSError(ValueError):
    pass


def _varint(patch: bytes, pos: int, limit: int) -> tuple[int, int]:
    value = 0
    shift = 1
    while True:
        if pos >= limit:
            raise UPSError("Entero UPS truncado.")
        byte = patch[pos]
        pos += 1
        value += (byte & 0x7F) * shift
        if value > MAX_SIZE + 1:
            raise UPSError("Entero UPS fuera del límite de tamaño.")
        if byte & 0x80:
            return value, pos
        shift <<= 7
        value += shift
        if shift > (1 << 63):
            raise UPSError("Entero UPS demasiado largo.")


def parse_info(patch: bytes) -> dict:
    if not patch.startswith(b"UPS1") or len(patch) < 18:
        raise UPSError("No es un parche UPS1 válido.")
    if len(patch) > 2 * MAX_SIZE + 1024:
        raise UPSError("Parche demasiado grande.")
    checksum = int.from_bytes(patch[-4:], "little")
    if zlib.crc32(patch[:-4]) != checksum:
        raise UPSError("CRC32 del parche incorrecto: archivo dañado o incompleto.")
    end = len(patch) - 12
    src_size, pos = _varint(patch, 4, end)
    dst_size, pos = _varint(patch, pos, end)
    if pos > end:
        raise UPSError("Cabecera UPS cruza el bloque de CRC.")
    if src_size > MAX_SIZE or dst_size > MAX_SIZE:
        raise UPSError("Tamaño declarado excede el máximo permitido.")
    return {
        "type": "ups",
        "source_size": src_size,
        "target_size": dst_size,
        "source_crc32": f"{int.from_bytes(patch[-12:-8], 'little'):08x}",
        "target_crc32": f"{int.from_bytes(patch[-8:-4], 'little'):08x}",
        "patch_crc32": f"{checksum:08x}",
        "body_start": pos,
        "body_end": end,
        "size_bytes": len(patch),
    }


def apply_patch(base: bytes, patch: bytes, direction: str = "auto") -> tuple[bytes, str]:
    if direction not in {"auto", "forward", "reverse"}:
        raise UPSError("Dirección inválida; usa auto, forward o reverse.")
    if len(base) > MAX_SIZE:
        raise UPSError("ROM base excede el límite de tamaño.")
    meta = parse_info(patch)
    actual_crc = f"{zlib.crc32(base):08x}"
    forward = len(base) == meta["source_size"] and actual_crc == meta["source_crc32"]
    reverse = len(base) == meta["target_size"] and actual_crc == meta["target_crc32"]
    if direction == "forward":
        reverse = False
    elif direction == "reverse":
        forward = False
    if not (forward or reverse):
        raise UPSError(
            "ROM base no corresponde al parche: tamaño o CRC32 incorrecto. "
            f"Recibido: {len(base)} bytes, CRC32={actual_crc}; "
            f"esperado origen={meta['source_size']} / {meta['source_crc32']} "
            f"o destino={meta['target_size']} / {meta['target_crc32']}."
        )
    target_size = meta["target_size"] if forward else meta["source_size"]
    expected_crc = meta["target_crc32"] if forward else meta["source_crc32"]
    work = bytearray(max(len(base), target_size))
    work[: len(base)] = base
    pos = meta["body_start"]
    offset = 0
    while pos < meta["body_end"]:
        delta, pos = _varint(patch, pos, meta["body_end"])
        offset += delta
        if offset >= len(work):
            raise UPSError("Parche UPS intenta escribir fuera de ROM.")
        while True:
            if pos >= meta["body_end"]:
                raise UPSError("Parche UPS truncado en secuencia XOR.")
            byte = patch[pos]
            pos += 1
            if byte == 0:
                offset += 1
                break
            if offset >= len(work):
                raise UPSError("Secuencia UPS fuera de límites.")
            work[offset] ^= byte
            offset += 1
    result = bytes(work[:target_size])
    actual = f"{zlib.crc32(result):08x}"
    if actual != expected_crc:
        raise UPSError(f"CRC32 de salida incorrecto: {actual} (esperado {expected_crc}).")
    return result, ("forward" if forward else "reverse")


def patch_file(
    base_path: Path,
    patch_path: Path,
    out_path: Path,
    *,
    direction: str = "auto",
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    protect_inputs(out_path, base_path, patch_path)
    manifest = out_path.with_name(out_path.name + ".patch.json")
    protect_inputs(manifest, base_path, patch_path)
    check_destination(out_path, force)
    check_destination(manifest, force)
    base = read_bounded(base_path, MAX_SIZE)
    patch = read_bounded(patch_path, 2 * MAX_SIZE + 1024)
    result, applied = apply_patch(base, patch, direction)
    common = min(len(base), len(result))
    report = {
        "operation": "apply-ups",
        "direction": applied,
        "output": str(out_path),
        "size_bytes": len(result),
        "crc32": f"{zlib.crc32(result):08x}",
        "base_sha256": digest(base),
        "target_sha256": digest(result),
        "patch_sha256": digest(patch),
        "patch": parse_info(patch),
        "changed_bytes": sum(a != b for a, b in zip(base[:common], result[:common], strict=False))
        + abs(len(base) - len(result)),
        "dry_run": dry_run,
    }
    if not dry_run:
        atomic_write(out_path, result, force=force)
        atomic_json(manifest, report, force=force)
    return report
