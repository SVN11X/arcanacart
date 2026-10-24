"""Consolidate an existing completed portrait batch, keeping all variant/ID origins."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import struct
import sys
import tempfile
import uuid
import zlib
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import extraer_retratos_variantes as batch
import validacion_retratos as check
from catalogo_retratos_galeria import render_gallery

MAX_FILE = 4 * 1024 * 1024
MAX_OCCURRENCES = 100_000
LABELS = {"portrait": "Retrato", "miniature": "Miniatura", "classcard": "Tarjeta de clase"}


def relative_name(name: str) -> str:
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or ":" in name:
        raise ValueError("Ruta de resultado inválida: " + name)
    return path.as_posix()


class ResultSource:
    """Read known members without unpacking ZIPs or modifying an input directory."""

    def __init__(self, path: Path):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("La entrada debe ser una ruta sin enlaces simbólicos.")
        self.path = path.resolve()
        self.zip = None
        self.members = {}
        self.roots = {}
        self.read_hashes = {}
        if self.path.is_file():
            archive = ZipFile(self.path)
            try:
                entries = archive.infolist()
                if len(entries) > 100_000 or sum(e.file_size for e in entries) > 2 * 1024**3:
                    raise ValueError("El ZIP supera los límites del catálogo.")
                for entry in entries:
                    if entry.is_dir():
                        continue
                    name = relative_name(entry.filename)
                    if name in self.members:
                        raise ValueError("El ZIP contiene rutas duplicadas: " + name)
                    self.members[name] = entry
            except BaseException:
                archive.close()
                raise
            self.zip = archive
        elif not self.path.is_dir():
            raise ValueError("No se encuentra la carpeta o ZIP del lote: " + str(path))

    def close(self):
        if self.zip:
            self.zip.close()

    def read(self, name: str, expected: str | None = None) -> bytes:
        name = relative_name(name)
        if self.zip:
            entry = self.members.get(name)
            if entry is None:
                raise ValueError("Falta un archivo en el ZIP: " + name)
            if entry.file_size > MAX_FILE:
                raise ValueError("Archivo del lote demasiado grande: " + name)
            data = self.zip.read(entry)
        else:
            path = batch.inside(self.path, name)
            if path.stat().st_size > MAX_FILE:
                raise ValueError("Archivo del lote demasiado grande: " + name)
            data = path.read_bytes()
        digest = check.digest(data)
        if expected is not None and digest != expected:
            raise ValueError("Un archivo del lote no coincide con su hash: " + name)
        if name in self.read_hashes and digest != self.read_hashes[name]:
            raise ValueError("El archivo cambió durante la consolidación: " + name)
        self.read_hashes[name] = digest
        return data

    def document(self, name: str, expected: str | None = None) -> dict:
        value = json.loads(self.read(name, expected))
        if not isinstance(value, dict):
            raise ValueError("Informe JSON inválido: " + name)
        return value

    def root_document(self, name: str) -> dict:
        value = self.document(name)
        self.roots[name] = self.read_hashes[name]
        return value

    def recheck_roots(self):
        for name, digest in self.roots.items():
            self.read(name, digest)


def png_info(data: bytes) -> dict:
    """Validate ArcanaCart's bounded RGBA8 PNG output, including CRC and alpha."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Firma PNG inválida.")
    at, width, height, payload, ended = 8, 0, 0, [], False
    while at < len(data):
        if at + 12 > len(data):
            raise ValueError("PNG truncado.")
        size = struct.unpack_from(">I", data, at)[0]
        if size > MAX_FILE or at + 12 + size > len(data):
            raise ValueError("Chunk PNG fuera de límite.")
        kind, chunk = data[at + 4 : at + 8], data[at + 8 : at + 8 + size]
        crc = struct.unpack_from(">I", data, at + 8 + size)[0]
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != crc:
            raise ValueError("CRC de PNG inválido.")
        if kind == b"IHDR":
            if at != 8 or size != 13 or width:
                raise ValueError("Cabecera PNG inválida.")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunk)
            if not 0 < width * height <= 1_048_576 or min(width, height) < 1:
                raise ValueError("Dimensiones PNG fuera de límite.")
            if (depth, color, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise ValueError("El PNG no usa el formato RGBA8 de ArcanaCart.")
        elif kind == b"IDAT":
            if not width:
                raise ValueError("PNG sin cabecera.")
            payload.append(chunk)
        elif kind == b"IEND":
            if size or at + 12 != len(data):
                raise ValueError("Final PNG inválido.")
            ended = True
        else:
            raise ValueError("Chunk ajeno al PNG generado por ArcanaCart.")
        at += size + 12
    if not width or not payload or not ended:
        raise ValueError("PNG incompleto.")
    stride = width * 4 + 1
    expected = stride * height
    decoder = zlib.decompressobj()
    raw = decoder.decompress(b"".join(payload), expected + 1)
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Los píxeles PNG no coinciden con sus dimensiones.")
    visible = False
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        if row[0] != 0:
            raise ValueError("Filtro ajeno al PNG generado por ArcanaCart.")
        visible = visible or any(row[4::4])
    return {"width": width, "height": height, "visible": visible}


def collect(source: ResultSource) -> tuple[dict, list[dict], dict[str, bytes], dict[str, bytes]]:
    summary = source.root_document("resumen.json")
    state = source.root_document("run-state.json")
    plan = source.root_document("planes-usados.json")
    # The batch stores the original plan file hash, then writes a JSON copy.
    # Re-serializing that copy need not preserve its original byte formatting.
    plan_hash = state.get("plan_sha256", "")
    if (
        summary.get("format") != "arcanacart-bounded-face-batch-result-1"
        or plan.get("format") != "arcanacart-bounded-face-batch-1"
        or summary.get("run_status") != "completed"
        or state.get("run_status") != "completed"
        or not re.fullmatch(r"[0-9a-f]{64}", plan_hash)
        or summary.get("plan_sha256") != plan_hash
    ):
        raise ValueError("Selecciona el resultado completo y verificado del lote de retratos.")
    jobs = plan["jobs"]
    if (
        not 1 <= len(jobs) <= 100
        or len(state["jobs"]) != len(jobs)
        or summary["completed_variants"] != len(jobs)
    ):
        raise ValueError("El lote contiene variantes pendientes o repetidas.")
    assets, pngs, palettes, occurrences, counts, variants = {}, {}, {}, [], Counter(), []
    for number, job in enumerate(jobs, 1):
        key = job["id"]
        if not re.fullmatch(r"fe[78]-[0-9]{3}", key) or key in variants or job["game"] != key[:3]:
            raise ValueError("Identificador de variante inválido o repetido.")
        variants.append(key)
        checkpoint = state["jobs"][key]
        directory = relative_name(checkpoint["directory"])
        print(f"[{number}/{len(jobs)}] Verificando {key} y sus imágenes...", flush=True)
        if checkpoint.get("status") != "completed" or not checkpoint.get("inputs_reverified"):
            raise ValueError("La variante no está verificada: " + key)
        result = source.document(directory + "/resultado.json", checkpoint["report_sha256"])
        validation = source.document(directory + "/validacion.json", result["validation_sha256"])
        prefix = directory + "/galeria/"
        files = source.document(prefix + "faces-state.json", result["faces_state_sha256"])
        catalog = source.document(prefix + "catalog.json", files["artifacts"]["catalog.json"])
        face_summary = source.document(prefix + "summary.json", files["artifacts"]["summary.json"])
        if (
            result.get("status") != "completed"
            or result.get("id") != key
            or result.get("variant") != job["variant"]
            or result.get("problems")
            or result.get("plan_sha256") != plan_hash
            or not validation.get("range_components_validated")
            or validation.get("errors")
            or validation.get("rom_sha256") != job["rom_sha256"]
            or validation.get("inspected_entries") != job["last_id"]
            or result["summary"] != face_summary
            or catalog["summary"] != face_summary
            or not batch.assess_result(job, face_summary)[0]
        ):
            raise ValueError("Los informes de la variante no son coherentes: " + key)
        if any(result[field] != job[field] for field in ("rom_sha256", "air_sha256", "layout_sha256")):
            raise ValueError("La identidad de la variante no coincide con su plan: " + key)
        table = bytes.fromhex(validation["reference_window_hex"])
        if check.digest(table) != job["table_bytes_sha256"]:
            raise ValueError("La tabla no coincide con el plan: " + key)
        evidence = {(e["face_id"], c["kind"]): (e, c) for e in validation["entries"] for c in e["components"]}
        rows = catalog["resources"]
        if len(rows) != sum(job["expected_counts"].values()) or len(evidence) != len(rows):
            raise ValueError("Faltan componentes de la variante: " + key)
        seen, job_counts = set(), Counter()
        for row in rows:
            identity = row["face_id"], row["kind"]
            if identity in seen or identity not in evidence or row["kind"] not in LABELS:
                raise ValueError("Componente repetido o desconocido: " + key)
            seen.add(identity)
            entry, component = evidence[identity]
            if (
                row["status"] != "generated"
                or row["colors"] != "rgb555-rom"
                or component.get("status") != "estructura_compatible"
                or any(row[f] != component[f] for f in ("source_sha256", "source_offset", "size_bytes"))
                or row["palette_sha256"] != entry["palette_sha256"]
            ):
                raise ValueError("Componente sin evidencia consistente: " + key)
            relative = relative_name(row["png"])
            png_hash = files["artifacts"][relative]
            data = source.read(prefix + relative, png_hash)
            if png_hash not in assets:
                info = png_info(data)
                assets[png_hash] = {
                    "png_sha256": png_hash,
                    "file": "imagenes/" + png_hash + ".png",
                    **info,
                    "kinds": [],
                    "games": [],
                    "origins": [],
                }
                pngs[png_hash] = data
            asset = assets[png_hash]
            if (asset["width"], asset["height"]) != (row["width"], row["height"]):
                raise ValueError("Las dimensiones no coinciden con el catálogo: " + key)
            palette_hash = row["palette_sha256"]
            palette = source.read(prefix + "paletas/" + palette_hash + ".bin", palette_hash)
            if len(palette) != 32 or palette.hex() != entry["palette_hex"]:
                raise ValueError("Paleta inválida: " + key)
            palettes[palette_hash] = palette
            origin = {
                "game": job["game"],
                "variant_id": key,
                "variant": job["variant"],
                "face_id": row["face_id"],
                "face_id_hex": row["face_id_hex"],
                "kind": row["kind"],
                "source_png": prefix + relative,
                "rom_sha256": job["rom_sha256"],
                "air_sha256": job["air_sha256"],
                "source_offset": row["source_offset"],
                "source_sha256": row["source_sha256"],
                "palette_sha256": palette_hash,
                "data_origin": row["data_origin"],
            }
            if row["kind"] not in asset["kinds"]:
                asset["kinds"].append(row["kind"])
            if job["game"] not in asset["games"]:
                asset["games"].append(job["game"])
            asset["origins"].append(origin)
            occurrences.append(
                {"png_sha256": png_hash, "file": asset["file"], "visible": asset["visible"], **origin}
            )
            counts[row["kind"]] += 1
            job_counts[row["kind"]] += 1
            if len(occurrences) > MAX_OCCURRENCES:
                raise ValueError("El lote supera 100.000 componentes.")
        if dict(job_counts) != job["expected_counts"]:
            raise ValueError("Los conteos no coinciden con el plan: " + key)
    if dict(counts) != summary["generated_counts"] or len(occurrences) != summary["generated_component_pngs"]:
        raise ValueError("El total de componentes no coincide con el resumen.")
    source.recheck_roots()
    images = [assets[key] for key in sorted(assets)]
    stats = {
        "format": "arcanacart-consolidated-face-catalog-1",
        "status": "completed",
        "source": str(source.path),
        "source_kind": "zip" if source.zip else "directory",
        "source_plan_sha256": plan_hash,
        "source_root_hashes": dict(source.roots),
        "variants": len(jobs),
        "component_occurrences": len(occurrences),
        "component_counts": dict(counts),
        "unique_images": len(images),
        "visible_images": sum(a["visible"] for a in images),
        "transparent_images": sum(not a["visible"] for a in images),
        "transparent_occurrences": sum(not o["visible"] for o in occurrences),
        "duplicate_png_copies_avoided": len(occurrences) - len(images),
        "unique_palettes": len(palettes),
        "verified_input_files": len(source.read_hashes),
        "rescanned": False,
        "inputs_modified": False,
        "deduplication": "Exact PNG SHA-256; every variant/ID origin is retained.",
        "scope": plan["scope"],
    }
    return {"summary": stats, "images": images}, occurrences, pngs, palettes


def csv_data(rows: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def save_zip(out: Path) -> Path:
    archive = out.with_name(out.name + ".zip")
    if archive.exists():
        raise FileExistsError("Se conserva el ZIP existente: " + str(archive))
    temporary = archive.with_name("." + archive.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with ZipFile(temporary, "x", ZIP_DEFLATED, compresslevel=6) as z:
            for path in sorted(out.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(out).as_posix())
        os.rename(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def run(
    source_path: Path,
    out: Path | None = None,
    *,
    create_zip: bool = False,
    dry_run: bool = False,
    tool_version: str = "0.6.3",
) -> dict:
    if out is None:
        out = source_path.resolve().parent / (
            "catalogo-retratos-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        )
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("La salida debe ser una ruta sin enlaces simbólicos.")
    out = out.resolve()
    if out.exists() or (create_zip and out.with_name(out.name + ".zip").exists()):
        raise FileExistsError("Elige una salida nueva para conservar los resultados existentes.")
    source = ResultSource(source_path)
    try:
        if out.is_relative_to(source.path) or source.path.is_relative_to(out):
            raise ValueError("La salida debe estar separada del lote original.")
        with batch.heartbeat("Verificación y consolidación"):
            catalog, occurrences, pngs, palettes = collect(source)
        catalog["summary"].update(tool_version=tool_version, output=str(out))
        if dry_run:
            return {**catalog["summary"], "status": "planned"}
        out.parent.mkdir(parents=True, exist_ok=True)
        print("Guardando el catálogo, las imágenes únicas y sus paletas...", flush=True)
        with (
            batch.heartbeat("Escritura del catálogo"),
            tempfile.TemporaryDirectory(prefix=".catalogo-retratos-", dir=out.parent) as temporary,
        ):
            staging = Path(temporary) / "catalogo"
            staging.mkdir()
            for digest, data in pngs.items():
                check.atomic_bytes(staging / "imagenes" / (digest + ".png"), data)
            for digest, data in palettes.items():
                check.atomic_bytes(staging / "paletas" / (digest + ".bin"), data)
            check.atomic_json(staging / "catalogo.json", catalog)
            check.atomic_json(staging / "resumen.json", catalog["summary"])
            check.atomic_bytes(staging / "ocurrencias.csv", csv_data(occurrences))
            image_rows = [
                {
                    "png_sha256": a["png_sha256"],
                    "file": a["file"],
                    "visible": a["visible"],
                    "width": a["width"],
                    "height": a["height"],
                    "kinds": ";".join(a["kinds"]),
                    "games": ";".join(a["games"]),
                    "occurrences": len(a["origins"]),
                }
                for a in catalog["images"]
            ]
            check.atomic_bytes(staging / "imagenes.csv", csv_data(image_rows))
            check.atomic_bytes(staging / "index.html", render_gallery(catalog).encode("utf-8"))
            check.atomic_bytes(
                staging / "LEEME.txt",
                (
                    "Abre index.html. Cada PNG se guarda una vez por SHA-256.\n"
                    "La galeria oculta las imagenes transparentes por defecto; todas las apariciones se conservan en catalogo.json y ocurrencias.csv.\n"
                    "Las paletas RGB555 originales se guardan por SHA-256 en paletas. Los bloques raw y comprimidos permanecen en el analisis original.\n"
                    + catalog["summary"]["scope"]
                    + "\n"
                ).encode("utf-8"),
            )
            artifacts = {
                p.relative_to(staging).as_posix(): batch.file_hash(p)
                for p in staging.rglob("*")
                if p.is_file()
            }
            check.atomic_json(staging / "catalog-state.json", {"status": "completed", "artifacts": artifacts})
            source.recheck_roots()
            if out.exists():
                raise FileExistsError("La salida apareció durante la consolidación; se conserva intacta.")
            os.rename(staging, out)
        result = {**catalog["summary"], "gallery": str(out / "index.html")}
        if create_zip:
            with batch.heartbeat("Empaquetado del catálogo"):
                result["archive"] = str(save_zip(out))
        return result
    finally:
        source.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path, help="Carpeta del lote o su ZIP de resultados.")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--crear-zip", action="store_true")
    parser.add_argument("--abrir", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        api = check.load_api(args.repo.resolve())
        result = run(
            args.input.resolve(),
            args.out,
            create_zip=args.crear_zip,
            dry_run=args.dry_run,
            tool_version=api.version,
        )
        print(
            f"Imágenes visibles distintas: {result['visible_images']}; PNG únicos totales: {result['unique_images']}."
        )
        print(
            f"Apariciones conservadas: {result['component_occurrences']}; paletas únicas: {result['unique_palettes']}."
        )
        if not args.dry_run:
            print("Galería: " + result["gallery"])
            if result.get("archive"):
                print("ZIP: " + result["archive"])
            if args.abrir and os.name == "nt":
                os.startfile(result["gallery"])
        return 0
    except KeyboardInterrupt:
        print("\nInterrumpido; el lote original permanece intacto.", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, struct.error, zlib.error) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
