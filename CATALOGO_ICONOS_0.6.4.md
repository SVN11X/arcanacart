# Catálogo consolidado de iconos

La consolidación reúne una sola copia de cada PNG, raw y paleta distintos de un
lote terminado de variantes. Conserva todas las apariciones con juego, variante,
ID, tipo, offsets, hashes y origen. No lee ROM ni AIR originales ni repite la
extracción. Se mantiene ArcanaCart 0.6.4 y no se instalan dependencias nuevas.

## Lote real comprobado

Entrada: `iconos-variantes-20261023-221844-35c28d-indice-portable.zip`.
SHA-256: `499ec0c8bd96e8bea8ed58e00162b07feb1e0415bcd1f082e6fda8b366a99c4e`.
Coincide exactamente con el ZIP generado en Windows y con la referencia auditada.

| Resultado | Cantidad |
| --- | ---: |
| Variantes | 43 |
| Apariciones conservadas | 9.224 |
| PNG únicos | 400 |
| Raw distintos | 400 |
| Paletas RGB555 distintas | 1 |
| PNG visibles / transparentes | 400 / 0 |
| Copias PNG adicionales evitadas | 8.824 |

Se verificaron los manifiestos completos de entrada, hashes, identidades y
definiciones; las filas de CSV locales y globales; rangos, IDs y conteos. Cada
PNG se decodifica y contrasta con los píxeles de su raw y paleta. Los bytes de los
recursos se copian sin recodificar. La deduplicación se basa en SHA-256 exacto
del archivo PNG, no en parecido visual. Un mismo PNG puede conservar varias
combinaciones de raw y paleta, todas con su procedencia.

El lector PNG admite RGBA8 16×16 no entrelazado con los cinco filtros del método
estándar, CRC de chunks y un límite fijo de descompresión. La referencia de
filtros es la [especificación PNG del W3C](https://www.w3.org/TR/PNG-Filters.html).
No se descomprimen nuevos bloques de ROM.

## Aplicación y uso

Aplica `arcanacart-0.6.4-consolidar-iconos.patch` mediante `git am` después del
parche de índice portable. Ejecuta desde el repositorio:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    & '.\scripts\windows\Consolidar-Iconos.ps1' `
        -Lote 'C:\FireEmblem\resultados\iconos-variantes-20261023-221844-35c28d-indice-portable.zip' `
        -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
        -OutputParent 'C:\FireEmblem\resultados' `
        -CrearZip `
        -Abrir
}
```

`-Lote` también acepta la carpeta del lote original o la copia con índice. Cada
ejecución crea `catalogo-iconos-<fecha>-<id>` y, con `-CrearZip`, un ZIP portable
con CRC comprobado. Se conserva la entrada. Una selección parcial mantiene en
el resumen el número esperado de variantes y las omitidas; nunca se presenta
como una extracción completa del conjunto original.

| Archivo o carpeta | Contenido |
| --- | --- |
| `index.html` | Galería local con filtros, búsqueda y paginación. |
| `catalogo.json` | Imágenes agrupadas y todos los campos de cada aparición. |
| `resumen.json` | Conteos, alcance e identidad de la entrada. |
| `imagenes.csv` | Una fila por PNG único y su número de apariciones. |
| `ocurrencias.csv` | Una fila por variante/ID, con enlaces a recursos consolidados. |
| `imagenes/`, `raw/`, `paletas/` | Copias exactas, nombradas por hash. |
| `fuentes/` | Resumen y manifiesto originales, más definiciones, resúmenes y manifiestos por variante. |
| `catalog-state.json` | Estado y SHA-256 de todos los archivos generados. |

Los campos `source_png`, `source_raw_file`, `source_palette_file` y
`source_catalog` se refieren a rutas del lote de entrada. Los campos `file`,
`raw_file` y `palette_file` apuntan a las copias del catálogo. Los manifiestos
guardados en `fuentes/` describen el lote original, cuyo contenido completo se
conserva en su ubicación o ZIP anterior. Sus inventarios AIR y galerías individuales
no se duplican dentro del catálogo; sus hashes y resúmenes quedan registrados.

## Galería

Los filtros de juego, variante y búsqueda se aplican sobre una misma procedencia.
Una imagen compartida entre FE7 y FE8 no satisface una combinación de filtros a
partir de dos apariciones distintas. Los IDs decimales o hexadecimales se buscan
de forma exacta; el resto del texto busca variantes y hashes.

Se muestran hasta 64 imágenes por página. Las procedencias se cargan al abrir
sus detalles, en grupos de 100, con botón para continuar hasta verlas todas.
Los transparentes se ocultan inicialmente y pueden mostrarse. Los CSV y JSON
siempre conservan todas las apariciones. La página funciona sin servidor y sin
solicitudes de red; los enlaces de descarga son relativos.

## Validación y límites

Se ejecutaron 111 pruebas de iconos: las 86 existentes y 25 de consolidación y
galería. Incluyen conservación de bytes y campos, PNG compartidos con raw o
paletas diferentes, transparencia, ZIP y carpetas, filtros correlacionados por
procedencia y eventos de DOM. El fixture con los cinco filtros PNG se contrastó
independientemente con Pillow al prepararlo; las pruebas Python no requieren
Pillow. Cinco pruebas de galería usan Node si está disponible, solo en desarrollo.

La comprobación independiente del lote real confirmó 400 PNG, 400 raw, una
paleta, 9.224 procedencias y 938 archivos en el catálogo. Se contrastaron todas
las procedencias y bytes de recursos contra el ZIP de entrada. Los resultados
están en `docs/VALIDACION_CATALOGO_ICONOS_0.6.4.json`.

Sigue pendiente comprobar la presentación en un navegador real. Los lanzadores
PowerShell no se ejecutaron en el entorno de desarrollo. Los rangos continúan
siendo FE7 0–172 y FE8 0–223, usando la primera paleta documentada: no prueban la
capacidad completa de las tablas ni la totalidad de recursos del juego. Los
hashes ROM/AIR son los preservados del lote; no se recalculan aquí sus originales.

Si solo falla el ZIP, conserva el catálogo y usa `python -m arcanacart.icon_catalog
pack --input CARPETA_CATALOGO --out ZIP_NUEVO`. No repitas la extracción ni la
consolidación para resolver un fallo de empaquetado.
