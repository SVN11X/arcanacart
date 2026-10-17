"""Read *listing* text exported by code2text; it contains no omitted binary assets."""

from pathlib import Path
from xml.etree import ElementTree as ET

from arcanacart.core.io import read_bounded


def inventory(path: Path) -> dict:
    raw = read_bounded(path, 8 * 1024 * 1024).decode("utf-8-sig")
    if "<!DOCTYPE" in raw.upper() or "<!ENTITY" in raw.upper():
        raise ValueError("No se admiten DTD ni entidades XML.")
    try:
        root = ET.fromstring("<root>" + raw + "</root>")
    except ET.ParseError as exc:
        raise ValueError("El inventario XML no es válido.") from exc
    entries = []
    for node in root.findall(".//entrada"):
        p = node.attrib.get("ruta", "")
        entries.append(
            {
                "path": p,
                "suffix": Path(p).suffix.lower(),
                "declared_bytes": int(node.attrib.get("tamano_bytes", "0")),
            }
        )
    return {
        "source": str(path),
        "inventory_only": True,
        "warning": "Este TXT no contiene bytes de los .ups ni de ninguna ROM que figure omitida.",
        "entries": entries,
        "count": len(entries),
        "patches": sum(e["suffix"] == ".ups" for e in entries),
    }
