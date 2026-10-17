> **Registro histórico del starter.** Esta validación fue relatada por v0.2;
> no se repitió en el encargo actual, que no adjuntó ROMs comerciales. No se usa
> como evidencia de los nuevos extractores. Consulta TECHNICAL_REPORT.md.

# Verificación local de archivos proporcionados (15 de octubre de 2026)

Se inspeccionaron **dos ZIP**, cada uno con un único archivo `.gba` de 16 MiB. Esta información identifica la versión; no contiene el juego ni su código.

| ZIP | Entrada interna | Game ID | SHA-1 | Base pública de símbolos |
|---|---|---|---|---|
| Fire Emblem (U) [!].zip | Fire Emblem (U) [!].gba | AE7E | `c735fdbb9e8abe19e0c6a44708df19acc962e204` | `StanHash/fe7_us` |
| Fire Emblem - the Sacred Stones GBA.zip | Fire Emblem - the Sacred Stones # GBA.GBA | BE8E | `c25b145e37456171ada4b0d440bf88a19f4d509f` | `FireEmblemUniverse/fireemblem8u` |

Ambas cabeceras GBA pasaron checksum y `0x96`. Las dos huellas SHA-1 se compararon con los valores publicados por sus repositorios de referencia. También se verificó el comando `prepare-zip` con ambos archivos usando una carpeta temporal eliminada inmediatamente después de las pruebas.

**No se empaquetan las ROMs ni sus bytes extraídos en este repositorio.**
