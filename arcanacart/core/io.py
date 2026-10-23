"""Bounded reads and atomic, no-clobber publication in user-selected directories."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO


def read_bounded(path: str | Path, limit: int, minimum: int = 0) -> bytes:
    if limit < minimum or minimum < 0:
        raise ValueError("Límites de lectura inválidos.")
    if not Path(path).is_file():
        raise ValueError("La entrada debe ser un archivo regular existente.")
    with Path(path).open("rb") as src:
        info = os.fstat(src.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("La entrada debe ser un archivo regular.")
        if not minimum <= info.st_size <= limit:
            raise ValueError(f"Tamaño fuera de rango: {info.st_size}; permitido {minimum}..{limit}.")
        data = src.read(limit + 1)
    if not minimum <= len(data) <= limit:
        raise ValueError("El tamaño cambió o excede el límite durante la lectura.")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def protect_inputs(out: Path, *inputs: Path) -> None:
    for source in inputs:
        if out.resolve() == source.resolve() or (out.exists() and source.exists() and out.samefile(source)):
            raise ValueError("La salida coincide con una entrada; se conserva el original.")


def check_destination(out: Path, force: bool = False) -> None:
    # No generated relative paths or symlink directories are accepted for writes.
    for part in (out, *out.parents):
        if part.is_symlink():
            raise ValueError("No se permite escribir mediante enlaces simbólicos.")
    if out.exists() and (not force or not out.is_file()):
        raise ValueError(f"Ya existe {out.name}; no se sobrescribe sin --force.")


@contextmanager
def staged_file(out: Path, force: bool = False) -> Iterator[tuple[BinaryIO, Path]]:
    """Publish only after the caller validates and closes its temporary file.

    Hard-link publication gives atomic no-clobber semantics on POSIX and NTFS.
    Unsupported filesystems fail closed. Atomicity applies to each file separately.
    """
    check_destination(out, force)
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".arcana-", suffix=".tmp", dir=out.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w+b") as stream:
            yield stream, temp
            stream.flush()
            os.fsync(stream.fileno())
        check_destination(out, force)
        if force:
            os.replace(temp, out)
        else:
            # Never replace a file created concurrently after the exists check.
            os.link(temp, out)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write(out: str | Path, data: bytes, *, force: bool = False) -> None:
    with staged_file(Path(out), force) as (stream, _):
        stream.write(data)


def atomic_json(out: str | Path, value: Any, *, force: bool = False) -> None:
    atomic_write(out, json_bytes(value), force=force)


def read_json(path: str | Path, limit: int = 32 * 1024 * 1024) -> Any:
    try:
        return json.loads(read_bounded(path, limit).decode("utf-8-sig"))
    except RecursionError as exc:
        raise ValueError("JSON excede profundidad segura.") from exc


@contextmanager
def workspace_lock(directory: Path) -> Iterator[None]:
    """Exclude concurrent writers; crash leftovers require explicit local removal."""
    lock = directory / ".arcanacart.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "Este workspace tiene un proceso activo o un bloqueo residual (.arcanacart.lock)."
        ) from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)
