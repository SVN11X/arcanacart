# Iconos de objetos y armas — ArcanaCart 0.6.4

Este cambio añade `icons` y el lanzador `scripts/windows/Extraer-Iconos.ps1`.
Extrae el banco de iconos raw 4bpp de las dos bases USA identificadas por sus
SHA-256 exactos. Reutiliza el lector de ROM, el renderizador y las escrituras
atómicas existentes. No añade dependencias, repite extracciones de retratos ni
vuelve a ejecutar el escáner de compresión.

El código de partida corresponde al ZIP local del commit
`3866b32c504204c08754c1ab8a7473014c222c35`. El parche modifica únicamente los
archivos recibidos que necesita integrar y añade archivos nuevos.

## Alcance de la primera extracción

| Base exacta | IDs inclusivos | Posiciones | Bytes por icono | Tamaño PNG |
| --- | --- | ---: | ---: | --- |
| FE7 USA | `0x00`–`0xAC` | 173 | 128 | 16 × 16 |
| FE8 USA | `0x00`–`0xDF` | 224 | 128 | 16 × 16 |

Son rangos documentados del banco de iconos. No significan que se hayan extraído
todos los recursos, nombres, animaciones o iconos adicionales de una variante.
Los límites se obtienen de fuentes fijadas por commit: `icon_orignal_max` es
el último índice inclusivo en FEBuilder, no el número de posiciones.

La extracción automática requiere los hashes de las bases ya utilizados por
ArcanaCart. Un Game Code `AE7E` o `BE8E` no habilita por sí mismo el extractor.
Se comprueba el puntero al banco y se obtiene la paleta raw RGB555 por su
puntero documentado. El banco debe caber en la ROM y no solaparse con la paleta.
Se utiliza la primera paleta de iconos; otros bancos/contextos de paleta quedan
fuera de esta primera exportación.

Para verificar la identidad se lee y calcula el hash de la ROM completa. Esto
no recorre cabeceras de compresión ni busca nuevas tablas. Después se leen los
slots documentados y la paleta; el programa conserva sus bytes exactos.

## Ejecutar ambas bases en Windows

Rutas predeterminadas:

- Python: `C:\FireEmblem\entorno-arcanacart\Scripts\python.exe`.
- FE7: `C:\FireEmblem\resultados\fe7\fe7-usa-base.gba`.
- FE8: `C:\FireEmblem\resultados\fe8\fe8-usa-base.gba`.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    & '.\scripts\windows\Extraer-Iconos.ps1' `
        -Game ambos `
        -Datos 'C:\FireEmblem' `
        -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
        -CrearZip
}
```

Antes de escribir resultados se comprueban ambas entradas. El lanzador crea
una carpeta nueva `C:\FireEmblem\resultados\iconos-ambos-FECHA-HORA-SUFIJO`.
Dentro habrá una carpeta por juego, `resumen.json` y `run-state.json`. Con
`-CrearZip` se genera un ZIP al lado de esa carpeta. El lanzador no modifica
las entradas ni las extracciones anteriores. `-Abrir` abre las galerías al
terminar y es opcional.

Si una base está en otra ubicación, usa `-Game fe7` o `-Game fe8` con `-RomPath`.
Las opciones `-RomPath`, `-AirPath` y `-Definition` se usan con un solo juego.

## Archivos de cada juego

| Archivo/carpeta | Contenido |
| --- | --- |
| `index.html` | Galería local, búsqueda por ID/hash, paginación y filtro de transparentes |
| `catalog.json` | Todos los IDs con procedencia; mantiene los duplicados como apariciones |
| `icons.csv` | Mismos IDs y campos en CSV UTF-8 con BOM |
| `summary.json` | Conteos, hashes de entradas, alcance y limitaciones |
| `definition.json` | Definición utilizada con offsets resueltos y hash de la ROM |
| `icons-state.json` | Estado y SHA-256 de todos los artefactos, excepto del propio manifiesto |
| `imagenes/SHA256.png` | PNG únicos por bytes exactos |
| `raw/SHA256.bin` | Slots originales 4bpp de 128 bytes, únicos por hash |
| `paletas/SHA256.bin` | Paleta RGB555 original de 32 bytes |

Un icono totalmente transparente se conserva en CSV, JSON y archivos; sólo se
oculta por defecto en la galería. El catálogo conserva ID, juego, offsets,
hashes de ROM/raw/PNG/paleta, dimensiones y procedencia. Un ID de icono no es
un nombre ni un ID de objeto: varios objetos pueden usar la misma posición.

## AIR existente, opcional

Los iconos de este banco se leen como raw desde la ROM; no necesitan aparecer
en el inventario de bloques comprimidos del AIR. Si indicas `-AirPath` para
un juego, se comprueba que el AIR identifica exactamente esa ROM y se calcula
el hash del archivo AIR sobre sus bytes originales, sin normalizar LF/CRLF.

Además se guarda `air-inventory.csv`, con offsets, tamaños, compresión, hashes
y recuentos de referencias del inventario ya existente. Los candidatos quedan
marcados como `unclassified-air-candidate`. Esta exportación no verifica los
archivos `.bin` externos, vuelve a descomprimir bloques ni los convierte en
iconos por su apariencia.

La misma opción en CLI es `--input RUTA_AL_AIR`. Un AIR truncado no impide leer
los slots raw documentados; su estado se conserva en `source_scan_truncated`.

## CLI, rangos y variantes

```text
python -m arcanacart icons --rom ROM.gba --out CARPETA_NUEVA
python -m arcanacart icons --rom ROM.gba --out CARPETA_NUEVA --dry-run
python -m arcanacart icons --rom ROM.gba --out CARPETA_NUEVA --first-id 0x10 --last-id 0x1F
python -m arcanacart icons --rom VARIANTE.gba --definition DEFINICION_REVISADA.json --out CARPETA_NUEVA
```

`--last-id` es inclusivo. Los filtros no pueden ampliar el rango de la
definición. No hay `--force`: se exige una salida nueva o vacía. `--dry-run`
verifica entradas, límites y renderizado sin crear resultados.

Una definición de variante requiere todos los campos siguientes:

- `format`: `arcanacart-item-icon-layout-1`.
- `rom_sha256`: hash exacto de esa ROM; `game`: `fe7` o `fe8`.
- `table_offset`: offset del primer slot descrito, asociado a `first_id`.
- `first_id`, `icon_count` (1–4096) e `icon_bytes` (128).
- `pointer_location`: ubicación del puntero al banco, o `null` si la lectura
  directa ha sido documentada.
- `palette_offset`: offset de 32 bytes de paleta, o `null` si se resolverá
  mediante `palette_pointer_location`.
- `palette_pointer_location`: ubicación del puntero, o `null` si se utiliza
  un offset explícito revisado. Si se indican ambos, deben coincidir.
- `sources`: entre una y 16 referencias documentales no vacías.

No reutilices una definición de base cambiando sólo su hash. Deben comprobarse
los accesos al banco, la geometría, la paleta y el rango de cada variante.
`definition_origin` distingue la definición automática de una definición del
usuario ligada a una ROM; esta última no constituye una validación documental
independiente. `review` permanece `unreviewed`.

## Verificación y siguiente paso

Se probaron colores, orden de los cuatro tiles, transparencia, duplicados,
rango inclusivo, hashes de bytes exactos, protección de entradas, punteros y
rechazo de variantes sin definición. Véase `docs/VERIFICACION_ICONOS_0.6.4.md`.

No se dispone de las ROM reales en el entorno que preparó este parche. El
siguiente paso es ejecutar el lanzador en las dos bases locales y revisar el
ZIP resultante antes de diseñar definiciones para las 43 variantes. La
presentación HTML en un navegador real continúa pendiente.

Fuentes fijadas y hashes de los archivos de referencia consultados:
`docs/ICON_SOURCE_EVIDENCE_0.6.4.json`. No se distribuyen gráficos de juegos ni
código de esas herramientas de referencia en el parche.
