"""Bounded local validation; derived from the tested variant diagnostic v2."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import struct
import sys
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

MAX_AIR_BYTES = MAX_ROM_BYTES = 64 * 1024 * 1024
MAX_COMPONENT_BYTES = 8192
MAX_DIAGNOSTIC_ENTRIES = 4096
FIELDS = ((0, "portrait"), (4, "miniature"), (16, "classcard"))
EXPECTED_BYTES = {"portrait": (4096, 5120), "miniature": (512,), "classcard": (2880, 3200)}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_file(path: Path, maximum: int, label: str, *, keep: bool = True) -> tuple[bytes, dict]:
    before = path.stat()
    if before.st_size > maximum:
        raise ValueError(f"El archivo supera {maximum // 1048576} MiB: {path}")
    print(f"    {label}: {before.st_size / 1048576:.1f} MiB...", flush=True)
    stop = threading.Event()
    progress = [0]
    started = time.monotonic()

    def heartbeat():
        while not stop.wait(10):
            print(
                f"    {label}: {progress[0] / 1048576:.1f}/{before.st_size / 1048576:.1f} MiB "
                f"({int(time.monotonic() - started)} s).",
                flush=True,
            )

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    checksum, chunks = hashlib.sha256(), []
    try:
        with path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                progress[0] += len(block)
                if progress[0] > maximum:
                    raise ValueError("El archivo creció por encima del límite durante su lectura.")
                checksum.update(block)
                if keep:
                    chunks.append(block)
    finally:
        stop.set()
        worker.join(timeout=1)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or progress[
        0
    ] != before.st_size:
        raise ValueError("El archivo cambió durante su lectura: " + str(path))
    identity = {"sha256": checksum.hexdigest(), "size_bytes": progress[0], "mtime_ns": after.st_mtime_ns}
    return b"".join(chunks), identity


def read_air(path: Path) -> tuple[dict, dict]:
    data, identity = read_file(path, MAX_AIR_BYTES, "Leyendo AIR")
    print("    Interpretando el JSON del AIR...", flush=True)
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Se esperaba un objeto JSON: " + str(path))
    return value, identity


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def load_api(repo: Path) -> SimpleNamespace:
    if not (repo / "arcanacart/__init__.py").is_file():
        raise ValueError("No se encuentra el paquete arcanacart dentro del repositorio indicado.")
    sys.path.insert(0, str(repo))
    package = importlib.import_module("arcanacart")
    actual = Path(package.__file__).resolve()
    if not actual.is_relative_to(repo.resolve()):
        raise ValueError("Python importó otra copia de ArcanaCart: " + str(actual))
    version = tuple(int(part) for part in package.__version__.split(".")[:3])
    if version < (0, 6, 1):
        raise ValueError("Este diagnóstico requiere ArcanaCart 0.6.1 o posterior.")
    comparison = importlib.import_module("arcanacart.resource_compare")
    compression = importlib.import_module("arcanacart.compression")
    faces = importlib.import_module("arcanacart.faces")
    return SimpleNamespace(
        version=package.__version__,
        compare=comparison.compare_resources,
        catalog_csv=comparison.catalog_csv,
        decoders=compression.DECODERS,
        layouts={"fe7": dict(faces.DEFAULT_LAYOUT), "fe8": dict(faces.FE8_LAYOUT)},
    )


def rom_offset(pointer: int, rom: bytes, length: int = 1) -> int:
    if not 0x08000000 <= pointer < 0x0E000000:
        raise ValueError(f"Puntero fuera de las ventanas ROM: 0x{pointer:08X}")
    offset = (pointer - 0x08000000) % 0x02000000
    if offset + length > len(rom):
        raise ValueError(f"Puntero o rango fuera del archivo: 0x{pointer:08X}")
    return offset


def decode_component(rom: bytes, offset: int, api: SimpleNamespace) -> tuple[bytes, int, str]:
    if offset + 4 > len(rom):
        raise ValueError("Cabecera de componente incompleta.")
    header = rom[offset : offset + 4]
    declared = int.from_bytes(header[1:], "little")
    if header[0] == 0:
        if not 4 < declared <= MAX_COMPONENT_BYTES + 4 or offset + declared > len(rom):
            raise ValueError("El tamaño raw es inválido o supera el límite del layout estándar.")
        return rom[offset + 4 : offset + declared], declared, "none"
    decoder = api.decoders.get(header[0])
    if decoder is None:
        raise ValueError(f"Compresión no compatible: 0x{header[0]:02X}")
    if not 0 < declared <= MAX_COMPONENT_BYTES:
        raise ValueError("El componente supera los 8192 bytes permitidos para este diagnóstico.")
    raw, consumed = decoder[1](rom, offset, MAX_COMPONENT_BYTES, None)
    if consumed > 32768:
        raise ValueError("El bloque codificado supera el límite de 32768 bytes.")
    return raw, consumed, decoder[0]


def probe_table(rom: bytes, base_rom: bytes, air: dict, layout: dict, api: SimpleNamespace) -> dict:
    pointer_location = layout["pointer_location"]
    reference_count = layout["entry_count"] - 1
    result = {
        "format": "arcanacart-variant-face-table-probe-1",
        "rom_sha256": air["rom"]["sha256"],
        "rom_hash_matches_air": True,
        "range_components_validated": False,
        "allocated_table_size_confirmed": False,
        "planned_range_entries": reference_count,
        "pointer_location": pointer_location,
        "limitations": [
            "La ventana revisada corresponde al rango de IDs indicado en el plan.",
            "No confirma el final de la tabla ni descarta entradas añadidas o eliminadas.",
            "Validar el rango de exportación no confirma el tamaño total reservado de la tabla.",
            "La comparación de inventarios cubre los candidatos comprimidos registrados, no todos los datos raw.",
        ],
        "entries": [],
        "errors": [],
    }
    if pointer_location is None or pointer_location < 16 or pointer_location + 4 > len(rom):
        result.update(status="puntero_no_disponible", access_code_matches_base=False)
        return result
    code = rom[pointer_location - 16 : pointer_location]
    base_code = base_rom[pointer_location - 16 : pointer_location]
    pointer = struct.unpack_from("<I", rom, pointer_location)[0]
    result.update(
        pointer_value=f"0x{pointer:08X}",
        access_code_hex=code.hex(),
        base_access_code_hex=base_code.hex(),
        access_code_matches_base=code == base_code,
    )
    try:
        table = rom_offset(pointer, rom, 28)
    except ValueError as exc:
        result.update(status="puntero_invalido")
        result["errors"].append(str(exc))
        return result
    result.update(
        candidate_table_offset=table,
        candidate_table_offset_hex=f"0x{table:X}",
        table_relocated=table != layout["table_offset"],
    )
    first = table + 28
    window_end = min(table + layout["entry_count"] * 28, len(rom))
    result["reference_window_hex"] = rom[first:window_end].hex()
    result["following_bytes_not_validated"] = rom[
        window_end : min(table + MAX_DIAGNOSTIC_ENTRIES * 28, len(rom))
    ].hex()
    result["diagnostic_span_max_entries"] = MAX_DIAGNOSTIC_ENTRIES
    if code != base_code:
        result["status"] = "codigo_de_acceso_distinto"
        return result
    records = {record["offset"]: record for record in air["resources"]}
    cache = {}
    component_counts = Counter()
    nonempty = 0
    for fid in range(1, layout["entry_count"]):
        start = table + fid * 28
        if start + 28 > len(rom):
            result["errors"].append(f"La entrada 0x{fid:03X} queda fuera de la ROM.")
            break
        entry = rom[start : start + 28]
        row = {
            "face_id": fid,
            "face_id_hex": f"0x{fid:03X}",
            "entry_hex": entry.hex(),
            "table_entry_offset": start,
            "components": [],
            "errors": [],
        }
        pointers = {kind: struct.unpack_from("<I", entry, field)[0] for field, kind in FIELDS}
        if not any(pointers.values()):
            row["status"] = "sin_componentes"
            result["entries"].append(row)
            continue
        nonempty += 1
        try:
            palette_pointer = struct.unpack_from("<I", entry, 8)[0]
            palette_offset = rom_offset(palette_pointer, rom, 32)
            palette = rom[palette_offset : palette_offset + 32]
            row.update(
                palette_offset=palette_offset, palette_hex=palette.hex(), palette_sha256=digest(palette)
            )
        except ValueError as exc:
            row["errors"].append("Paleta: " + str(exc))
        for field, kind in FIELDS:
            pointer = pointers[kind]
            if pointer == 0:
                continue
            component = {"kind": kind, "pointer": f"0x{pointer:08X}", "pointer_location": start + field}
            try:
                offset = rom_offset(pointer, rom, 4)
                component["source_offset"] = offset
                if offset not in cache:
                    cache[offset] = decode_component(rom, offset, api)
                raw, consumed, compression = cache[offset]
                if len(raw) not in EXPECTED_BYTES[kind]:
                    raise ValueError(f"Tamaño {len(raw)} incompatible con el {kind} estándar.")
                record = records.get(offset)
                if record is not None:
                    if (
                        record["sha256"] != digest(raw)
                        or record["decompressed_bytes"] != len(raw)
                        or record["compressed_bytes"] != consumed
                        or record["encoded_sha256"] != digest(rom[offset : offset + consumed])
                    ):
                        raise ValueError("El componente leído no coincide con el registro del AIR.")
                component.update(
                    status="estructura_compatible",
                    compression=compression,
                    size_bytes=len(raw),
                    stored_bytes=consumed,
                    source_sha256=digest(raw),
                    present_in_air=record is not None,
                )
                component_counts[kind] += 1
            except (ValueError, IndexError, struct.error) as exc:
                component.update(status="requiere_revision", error=str(exc))
                row["errors"].append(kind + ": " + str(exc))
            row["components"].append(component)
        row["status"] = "requiere_revision" if row["errors"] else "estructura_compatible"
        result["errors"].extend(f"{row['face_id_hex']}: {error}" for error in row["errors"])
        result["entries"].append(row)
    if not nonempty:
        result["errors"].append("La ventana candidata no contiene entradas con gráficos.")
    result.update(
        status="requiere_revision" if result["errors"] else "candidata_sin_errores_en_ventana",
        observed_component_counts=dict(component_counts),
        nonempty_entries=nonempty,
        inspected_entries=len(result["entries"]),
    )
    return result
