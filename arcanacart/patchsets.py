"""Bounded, selective UPS cataloguing; never expand arbitrary ZIP member paths."""

from __future__ import annotations

import hashlib
import re
import stat
import unicodedata
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from arcanacart.core.io import digest, staged_file
from feunpack.archives import ArchiveLimits, _check_archive
from feunpack.ups import MAX_SIZE, parse_info

PATCHSET_LIMITS = ArchiveLimits(
    max_archive_bytes=2 * 1024**3,
    max_total_bytes=2 * 1024**3,
    max_members=4096,
    max_directory_bytes=4 * 1024**2,
)
MAX_PATCH_BYTES = 2 * MAX_SIZE + 1024


def file_hash(path: Path, limit: int = 2 * 1024**3) -> str:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Archivo inexistente, no regular o superior al límite configurado.")
    result = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            total += len(block)
            if total > limit:
                raise ValueError("El archivo creció durante la lectura.")
            result.update(block)
    return result.hexdigest()


def canonical_id(game: str, member: str) -> str:
    if game not in {"fe7", "fe8"}:
        raise ValueError("Juego de parche desconocido.")
    path = PurePosixPath(member.replace("\\", "/"))
    name = path.stem
    legacy = any("legacy" in part.casefold() for part in path.parts[:-1]) or "(antiguo)" in name.casefold()
    name = re.sub(r"\(antiguo\)\s*", "", name, flags=re.I)
    timestamp = re.search(r"\.patch\.(\d{14})$", name, re.I)
    suffix = ""
    if timestamp:
        digits = timestamp[1]
        suffix = "-" + digits[:8] + "t" + digits[8:]
        name = name[: timestamp.start()]
    if game == "fe7":
        name = re.sub(r"^FE7URemaster\b", "fe7-usa-remastered", name, flags=re.I)
        name = re.sub(r"^FE7U\b", "fe7-usa", name, flags=re.I)
    else:
        name = re.sub(r"^Sacred\s+Trilogy\b", "fe8-usa-sacred-trilogy", name, flags=re.I)
    name = re.sub(r"\bVersion\b", "", name, flags=re.I)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z0-9.]+", "-", name).strip("-.")
    if not name.startswith(game + "-"):
        name = game + "-usa-" + name
    if legacy:
        name = name.replace(game + "-usa-", game + "-usa-legacy-", 1)
    name += suffix
    if len(name) > 110:
        name = name[:97].rstrip("-.") + "-" + digest(member.encode())[:12]
    return name


def catalog_patchset(path: Path, game: str, limits: ArchiveLimits = PATCHSET_LIMITS) -> dict:
    _check_archive(path, limits)
    before = path.stat()
    entries = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    with ZipFile(path) as archive:
        members = archive.infolist()
        if sum(m.file_size for m in members) > limits.max_total_bytes:
            raise ValueError("El paquete de mods excede el límite agregado de expansión.")
        for member in members:
            normalized = member.filename.replace("\\", "/").casefold()
            if normalized in seen_names:
                raise ValueError("Paquete de mods con miembros duplicados o ambiguos.")
            seen_names.add(normalized)
            if member.is_dir() or not normalized.endswith(".ups"):
                continue
            name = PurePosixPath(member.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or re.match(r"^[a-zA-Z]:", str(name)):
                raise ValueError("Ruta UPS insegura dentro del ZIP.")
            if member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Parche cifrado o symlink no admitido.")
            if not 18 <= member.file_size <= MAX_PATCH_BYTES:
                raise ValueError("Tamaño UPS fuera del límite permitido.")
            if member.file_size > max(1, member.compress_size) * limits.max_ratio:
                raise ValueError("Ratio de expansión UPS excesivo.")
            identity = canonical_id(game, member.filename)
            if identity in seen_ids:
                identity += "-" + digest(member.filename.encode())[:8]
            if identity in seen_ids:
                raise ValueError("Identificador de variante duplicado.")
            seen_ids.add(identity)
            entries.append(
                {
                    "id": identity,
                    "game": game,
                    "member": member.filename,
                    "file_name": identity + ".ups",
                    "size_bytes": member.file_size,
                    "zip_crc32": f"{member.CRC:08x}",
                    "legacy": "legacy-" in identity,
                }
            )
    if not entries:
        raise ValueError("El ZIP de mods no contiene archivos UPS1 (.ups).")
    fingerprint = file_hash(path, limits.max_archive_bytes)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("El paquete cambió durante su catalogación.")
    return {
        "format": "arcanacart-patchset-1",
        "game": game,
        "archive_name": path.name,
        "archive_sha256": fingerprint,
        "archive_size": after.st_size,
        "archive_mtime_ns": after.st_mtime_ns,
        "count": len(entries),
        "entries": sorted(entries, key=lambda e: e["id"]),
    }


def read_patch(path: Path, catalog: dict, record: dict) -> tuple[bytes, dict]:
    current = path.stat()
    if (current.st_size, current.st_mtime_ns) != (catalog["archive_size"], catalog["archive_mtime_ns"]):
        raise ValueError("El ZIP de mods cambió después del catálogo; vuelve a ejecutar.")
    _check_archive(path, PATCHSET_LIMITS)
    with ZipFile(path) as archive:
        matches = [i for i in archive.infolist() if i.filename == record["member"]]
        if len(matches) != 1:
            raise ValueError("Miembro UPS ausente o ambiguo.")
        member = matches[0]
        if member.file_size != record["size_bytes"] or f"{member.CRC:08x}" != record["zip_crc32"]:
            raise ValueError("Metadatos UPS cambiaron después del catálogo.")
        with archive.open(member) as stream:
            data = stream.read(MAX_PATCH_BYTES + 1)
    if len(data) != record["size_bytes"] or len(data) > MAX_PATCH_BYTES:
        raise ValueError("Longitud UPS descomprimida inconsistente.")
    return data, parse_info(data)


def copy_verified(source: Path, target: Path, *, limit: int = 2 * 1024**3) -> dict:
    """Copy under a canonical filename, retaining the original and checking disk bytes."""
    from arcanacart.core.io import check_destination, protect_inputs

    protect_inputs(target, source)
    expected = file_hash(source, limit)
    if target.exists():
        check_destination(target, force=True)
        if file_hash(target, limit) != expected:
            raise ValueError(f"Ya existe {target.name} con otro contenido. No se sobrescribe.")
        return {"sha256": expected, "size_bytes": target.stat().st_size, "reused": True}
    with staged_file(target) as (destination, _):
        result = hashlib.sha256()
        count = 0
        with source.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                count += len(block)
                if count > limit:
                    raise ValueError("La entrada creció o supera el límite de copia.")
                result.update(block)
                destination.write(block)
        if result.hexdigest() != expected:
            raise ValueError("La entrada cambió durante la copia.")
        destination.flush()
        destination.seek(0)
        written = hashlib.sha256()
        while block := destination.read(1024 * 1024):
            written.update(block)
        if written.hexdigest() != expected:
            raise ValueError("La copia escrita no coincide con el original.")
    return {"sha256": expected, "size_bytes": count, "reused": False}
