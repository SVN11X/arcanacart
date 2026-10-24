"""Verify an existing icon batch and publish a ZIP with portable POSIX member names."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from arcanacart.core.io import check_destination, digest, read_bounded, staged_file
from arcanacart.icons import _safe

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILES = 20000


def _relative(name: object) -> str:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Nombre de artefacto no portable.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError("Ruta de artefacto fuera del paquete.")
    return name


def _document(payloads: dict[str, bytes], name: str) -> dict:
    if name not in payloads:
        raise ValueError("Falta el archivo del lote: " + name)
    try:
        result = json.loads(payloads[name].decode("utf-8-sig"))
    except RecursionError as exc:
        raise ValueError("JSON excede profundidad segura.") from exc
    if not isinstance(result, dict):
        raise ValueError("Se requiere un objeto JSON: " + name)
    return result


def _snapshot(source: Path) -> dict[str, bytes]:
    _safe(source)
    if not source.is_dir():
        raise ValueError("Indica la carpeta existente del lote de iconos.")
    payloads: dict[str, bytes] = {}
    names = set()
    total = 0
    for path in sorted(source.rglob("*")):
        _safe(path)
        if path.is_dir():
            continue
        name = _relative(path.relative_to(source).as_posix())
        if name.casefold() in names:
            raise ValueError("Nombres de archivo incompatibles con Windows: " + name)
        names.add(name.casefold())
        if len(names) > MAX_FILES:
            raise ValueError("El lote excede el límite de archivos.")
        raw = read_bounded(path, MAX_FILE_BYTES)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("El lote excede el presupuesto de lectura de 128 MiB.")
        payloads[name] = raw
    batch = _document(payloads, "resumen.json")
    state = _document(payloads, "run-state.json")
    results = batch.get("results")
    if (
        batch.get("format") != "arcanacart-item-icon-batch-1"
        or batch.get("status") != "completed"
        or state.get("status") != "completed"
        or not isinstance(results, list)
        or not 1 <= len(results) <= 2
        or type(batch.get("games")) is not int
        or batch["games"] != len(results)
    ):
        raise ValueError("Se requiere un lote de iconos terminado, con uno o dos juegos.")
    games = set()
    occurrences = 0
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("game"), str):
            raise ValueError("Resultado de juego inválido.")
        game = result["game"]
        if game not in {"fe7", "fe8"} or game in games:
            raise ValueError("Juego inválido o repetido en el resumen.")
        games.add(game)
        root = game + "/"
        summary = _document(payloads, root + "summary.json")
        manifest = _document(payloads, root + "icons-state.json")
        if (
            summary.get("format") != "arcanacart-item-icon-catalog-1"
            or summary.get("game") != game
            or summary.get("status") != "completed"
            or manifest.get("status") != "completed"
            or {key: result.get(key) for key in summary} != summary
            or type(summary.get("icon_occurrences")) is not int
            or summary["icon_occurrences"] < 1
        ):
            raise ValueError("Resumen o estado de juego incoherente: " + game)
        occurrences += summary["icon_occurrences"]
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValueError("Falta el manifiesto de artefactos de " + game)
        expected = {name[len(root) :] for name in payloads if name.startswith(root)} - {"icons-state.json"}
        if set(artifacts) != expected:
            raise ValueError("Faltan artefactos o hay archivos adicionales en " + game)
        for name, hash_ in artifacts.items():
            _relative(name)
            if not isinstance(hash_, str) or re.fullmatch(r"[0-9a-f]{64}", hash_) is None:
                raise ValueError("SHA-256 inválido en el manifiesto.")
            if digest(payloads[root + name]) != hash_:
                raise ValueError("El artefacto no coincide con su SHA-256: " + root + name)
    if (
        type(batch.get("icon_occurrences")) not in {int, float}
        or batch["icon_occurrences"] != occurrences
        or any(name.split("/", 1)[0] not in games | {"resumen.json", "run-state.json"} for name in payloads)
    ):
        raise ValueError("El resumen global no corresponde a los archivos del lote.")
    return payloads


def pack_icons(source: Path, out: Path) -> dict:
    """Snapshot verified output bytes; never read a ROM or rerender an icon."""
    _safe(source)
    _safe(out)
    if out.resolve().is_relative_to(source.resolve()):
        raise ValueError("Guarda el ZIP fuera de la carpeta de entrada.")
    check_destination(out)
    payloads = _snapshot(source)
    with staged_file(out) as (stream, _):
        with ZipFile(stream, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name, raw in sorted(payloads.items()):
                # writestr plus an explicit POSIX name avoids OS-dependent
                # separator rewriting by Windows archive providers.
                info = ZipInfo(_relative(name), date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, raw, compress_type=ZIP_DEFLATED, compresslevel=9)
        stream.seek(0)
        with ZipFile(stream) as archive:
            if set(archive.namelist()) != set(payloads) or archive.testzip() is not None:
                raise ValueError("La verificación del ZIP no terminó correctamente.")
        stream.seek(0)
        hasher = hashlib.sha256()
        while raw := stream.read(1024 * 1024):
            hasher.update(raw)
        zip_hash = hasher.hexdigest()
    return {
        "status": "completed",
        "output": str(out),
        "files": len(payloads),
        "sha256": zip_hash,
        "portable_paths": True,
        "crc_verified": True,
        "rescanned": False,
        "inputs_modified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Carpeta ya extraída con resumen.json.")
    parser.add_argument("--out", type=Path, required=True, help="ZIP nuevo fuera de la entrada.")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(pack_icons(args.input, args.out), ensure_ascii=False))
        return 0
    except (ValueError, OSError, BadZipFile, UnicodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
