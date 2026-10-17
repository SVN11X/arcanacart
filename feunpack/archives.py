"""Inspect a selected ZIP ROM without ever using member paths as destinations."""

from __future__ import annotations

import hashlib
import re
import stat
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZipInfo

from arcanacart.core.io import atomic_json, check_destination, protect_inputs, staged_file

from .gba import KNOWN_US_ROMS as KNOWN_US_ROMS
from .gba import MAX_ROM_SIZE, GBAError, header_info


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 128 * 1024 * 1024
    max_members: int = 4096
    max_total_bytes: int = 256 * 1024 * 1024
    max_rom_bytes: int = MAX_ROM_SIZE
    max_ratio: int = 2000
    max_directory_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            min(
                self.max_archive_bytes,
                self.max_members,
                self.max_total_bytes,
                self.max_rom_bytes,
                self.max_ratio,
                self.max_directory_bytes,
            )
            <= 0
        ):
            raise ValueError("Los límites ZIP deben ser positivos.")


def _member(z: ZipFile, selected: str | None, limits: ArchiveLimits | None = None) -> ZipInfo:
    limits = limits or ArchiveLimits()
    entries = z.infolist()
    if len(entries) > limits.max_members or sum(e.file_size for e in entries) > limits.max_total_bytes:
        raise ValueError("ZIP excede los límites de miembros o expansión total.")
    names = [e.filename.replace("\\", "/").casefold() for e in entries]
    if len(names) != len(set(names)):
        raise ValueError("ZIP contiene nombres duplicados o ambiguos.")
    gba = [e for e in entries if not e.is_dir() and e.filename.lower().endswith(".gba")]
    if selected is None:
        if len(gba) != 1:
            raise ValueError(
                f"Se necesita exactamente una ROM GBA en el ZIP (se encontraron {len(gba)}). Usa --member."
            )
        entry = gba[0]
    else:
        matches = [e for e in gba if e.filename == selected]
        if len(matches) != 1:
            raise ValueError("No hay un miembro .gba único con ese nombre exacto en el ZIP.")
        entry = matches[0]
    path = PurePosixPath(entry.filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", str(path)):
        raise ValueError("Nombre de miembro ROM inseguro.")
    if stat.S_ISLNK(entry.external_attr >> 16):
        raise ValueError("La ROM seleccionada es un enlace simbólico.")
    if entry.flag_bits & 1:
        raise ValueError("ROM cifrada dentro del ZIP; no se admite.")
    if not 0xC0 <= entry.file_size <= limits.max_rom_bytes:
        raise ValueError(f"Tamaño ROM fuera de rango seguro: {entry.file_size}")
    if entry.file_size > max(1, entry.compress_size) * limits.max_ratio:
        raise ValueError("Ratio de compresión ZIP excede el límite configurado.")
    return entry


def _check_archive(path: Path, limits: ArchiveLimits) -> None:
    if not path.is_file() or path.stat().st_size > limits.max_archive_bytes:
        raise ValueError("Contenedor ZIP no regular o demasiado grande.")
    # Preflight central directory BEFORE ZipFile allocates one Python object/member.
    # This bounded input route deliberately rejects ZIP64 and multi-volume archives.
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
        index = tail.rfind(b"PK\x05\x06")
        if index < 0 or index + 22 > len(tail):
            raise ValueError("ZIP sin directorio central válido.")
        _, disk, central_disk, disk_count, count, directory_size, directory_offset, comment_size = (
            struct.unpack_from("<4s4H2LH", tail, index)
        )
        if index + 22 + comment_size != len(tail):
            raise ValueError("Final ZIP inconsistente o datos finales no admitidos.")
        if disk or central_disk or disk_count != count or count == 65535 or directory_offset == 0xFFFFFFFF:
            raise ValueError("No se admiten ZIP64 ni archivos ZIP multidisco.")
        if count > limits.max_members or directory_size > limits.max_directory_bytes:
            raise ValueError("Directorio central ZIP excede límites de miembros o memoria.")
        if directory_offset + directory_size > size - 22 - comment_size:
            raise ValueError("Directorio central ZIP fuera del archivo.")
        stream.seek(directory_offset)
        directory = stream.read(directory_size)
    cursor = 0
    actual = 0
    while cursor < len(directory):
        if cursor + 46 > len(directory) or directory[cursor : cursor + 4] != b"PK\x01\x02":
            raise ValueError("Entrada de directorio ZIP truncada o inválida.")
        name_size, extra_size, entry_comment = struct.unpack_from("<3H", directory, cursor + 28)
        cursor += 46 + name_size + extra_size + entry_comment
        actual += 1
        if actual > limits.max_members or cursor > len(directory):
            raise ValueError("ZIP excede límites o metadatos de miembros truncados.")
    if actual != count:
        raise ValueError("Conteo de miembros ZIP inconsistente.")


def inspect_zip(path: Path, member: str | None = None, *, limits: ArchiveLimits | None = None) -> dict:
    limits = limits or ArchiveLimits()
    _check_archive(path, limits)
    with ZipFile(path) as z:
        entry = _member(z, member, limits)
        with z.open(entry) as src:
            data = src.read(limits.max_rom_bytes + 1)  # ZipFile validates CRC at EOF.
        if len(data) != entry.file_size or len(data) > limits.max_rom_bytes:
            raise ValueError("Longitud descomprimida inconsistente.")
        result = header_info(data)
        result.update(zip_entry=entry.filename, source_zip=path.name)
        return result


def prepare_zip(
    path: Path,
    out: Path,
    member: str | None = None,
    require_known: bool = True,
    force: bool = False,
    *,
    limits: ArchiveLimits | None = None,
) -> dict:
    limits = limits or ArchiveLimits()
    protect_inputs(out, path)
    manifest = out.with_name(out.stem + ".manifest.json")
    protect_inputs(manifest, path)
    check_destination(out, force)
    check_destination(manifest, force)
    result = inspect_zip(path, member, limits=limits)
    if not result["gba_fixed_0x96"] or not result["header_checksum_valid"]:
        raise GBAError("Cabecera GBA inválida: no se permite preparar la ROM.")
    if require_known and not result["reference"]:
        raise ValueError("SHA-1 desconocido; usa --allow-unknown para una variante propia.")
    with staged_file(out, force) as (dst, _):
        _check_archive(path, limits)
        with ZipFile(path) as z:
            entry = _member(z, member, limits)
            total = 0
            check = hashlib.sha256()
            with z.open(entry) as src:
                while True:
                    block = src.read(min(1024 * 1024, limits.max_rom_bytes + 1 - total))
                    if not block:
                        break
                    total += len(block)
                    if total > limits.max_rom_bytes:
                        raise ValueError("Descompresión excesiva.")
                    check.update(block)
                    dst.write(block)
        if total != result["size_bytes"] or check.hexdigest() != result["sha256"]:
            raise ValueError("El archivo cambió entre inspección y extracción (hash o tamaño).")
        dst.flush()
        dst.seek(0)
        # Verify bytes actually written, not only the input stream.
        disk_hash = (
            hashlib.file_digest(dst, "sha256").hexdigest()
            if hasattr(hashlib, "file_digest")
            else hashlib.sha256(dst.read()).hexdigest()
        )
        if disk_hash != result["sha256"]:
            raise ValueError("La copia escrita no coincide con el SHA-256 verificado.")
    report = {**result, "prepared_local_file": str(out), "manifest": str(manifest)}
    atomic_json(manifest, report, force=force)
    return report
