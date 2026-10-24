# Revisión de iconos de las 43 variantes

Este cambio amplía ArcanaCart 0.6.4 después del parche de ZIP portable.
No cambia el número de versión. Añade una revisión local y un lote que exige
definiciones verificadas. No ejecuta el escáner ni repite los retratos o los
iconos de las bases que ya se exportaron.

La revisión del paquete real de las 43 variantes y los comandos para reutilizarlo
están en [Rangos de iconos revisados](docs/REVISION_ICONOS_VARIANTES_APROBADA_0.6.4.md).

El lote terminado y su navegación portable están documentados en la
[auditoría de iconos de variantes](docs/AUDITORIA_LOTE_ICONOS_VARIANTES_0.6.4.md).

La [consolidación de iconos](CATALOGO_ICONOS_0.6.4.md) conserva las procedencias
y reúne los PNG, raw y paletas únicos en una galería local.

## Evidencia recuperada

El plan `scripts/variantes/iconos/variantes.json` identifica ocho variantes FE7
y 35 FE8 mediante su nombre, ruta relativa, SHA-256 de ROM y SHA-256 exacto de
AIR. Las 43 identidades se contrastaron con el catálogo de retratos auditado.

La fuente es `comparacion-variantes-20261023-090537-664e5b-completo-20261023-093239-4b8f67.zip`,
SHA-256 `b06ea5b773421fa1396c23eaa3cc0c290d21e2dda5c6f790640aa650ab030f35`.
Ese análisis revisaba las tablas de retratos: no contiene los bytes ni los
límites revisados de los bancos de iconos. Por eso el plan inicial no incluye
rangos aprobados de tablas modificadas. Se deben obtener de la revisión local.

## Qué comprueba la revisión

1. Comprueba las dos bases locales por sus hashes exactos y resuelve sus tablas.
2. Comprueba cada ROM y AIR contra los hashes del plan. La identidad y el tamaño
   del AIR deben coincidir con la ROM. No normaliza bytes de ROM, AIR o recursos.
3. Lee los punteros de iconos y paleta documentados, comprueba su ventana ROM,
   límites y posibles solapamientos. Sigue un puntero reubicado; no conserva
   silenciosamente el offset de la base.
4. Guarda un rango candidato de 128 bytes por ID, la paleta de 32 bytes, contextos
   de acceso, una ventana acotada de código y 128 bytes posteriores como evidencia.
   Los bytes posteriores no se clasifican como iconos ni amplían el rango.
5. Genera una definición verificada automáticamente solo cuando el prefijo de
   iconos y la paleta son idénticos a la base y ambos contextos de 64 bytes
   anteriores a los punteros coinciden, excluyendo el valor del propio puntero.
   El contexto por sí solo nunca aprueba un rango. Esta prueba confirma ese
   prefijo idéntico; no demuestra el tamaño total de una tabla reubicada.
6. Los bancos o contextos modificados quedan `pending`. Un fallo de identidad,
   lectura o estructura queda `error`, sin habilitar una definición para el lote.

La ventana candidata inicial es 0–172 en FE7 y 0–223 en FE8. Son ventanas de
comparación con las bases, no límites atribuidos a todas las variantes. Tampoco
se adopta automáticamente el máximo 0xFE que muestra FEBuilder para bancos
reubicados. La identidad exacta de la ROM no demuestra por sí sola el rango.

En FE7 con tabla en el offset original, si aparece la firma `0x18404902` en
`0xCB51A`, se excluye el ID 0xAC: esa posición contiene código de FEditorAdv.
La ventana pasa a terminar en 0xAB. Esta excepción está documentada en
[`ImageItemIconForm.cs`](https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ImageItemIconForm.cs).
Los punteros y formatos usan las fuentes fijadas en
`docs/ICON_SOURCE_EVIDENCE_0.6.4.json`; el motor no consulta Internet.

Leer la ROM completa para calcular su hash es necesario para verificar su
identidad. No equivale a buscar nuevos candidatos comprimidos. La revisión solo
interpreta las ventanas declaradas; no descomprime, exporta PNG ni modifica ROM.

## Ejecutar la revisión

Después de aplicar `arcanacart-0.6.4-revision-iconos-variantes.patch`:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    & '.\scripts\windows\Revisar-Iconos-Variantes.ps1' `
        -Datos 'C:\FireEmblem' `
        -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
        -OutputParent 'C:\FireEmblem\resultados' `
        -CrearZip
}
```

Se crea una carpeta nueva `revision-iconos-variantes-<fecha>-<id>` y su ZIP
portable, con CRC y hashes comprobados. El informe termina aunque algunas
variantes queden pendientes o tengan errores: `status: completed` significa que
terminó la revisión; `ready_for_full_batch` y `counts` indican qué está habilitado.
Adjunta el ZIP generado para revisar las tablas modificadas. No contiene ROM
completas, archivos AIR completos ni los recursos comprimidos del análisis.

| Archivo | Uso |
| --- | --- |
| `revision.json`, `revision.csv` | Estado, punteros, rangos candidatos, hashes y motivos por variante. |
| `plan-usado.json` | Copia canónica del plan exacto utilizado. |
| `definiciones/` | Definiciones de rangos verificados y habilitados para el lote. |
| `candidatas/` | Definiciones pendientes, excluidas del lote. |
| `evidencias/<variante>/` | Bytes y contextos necesarios para la revisión independiente. |
| `variant-icons-state.json` | Estado y SHA-256 de cada artefacto generado. |

Un error de puntero conserva una ventana de código si la ROM tiene el hash
correcto. Un error de hash de ROM no captura evidencia de esa ROM desconocida.

## Completar la revisión de tablas modificadas

Tras revisar el ZIP, el siguiente parche puede añadir a `reviewed_ranges` la
definición de cada variante respaldada por evidencia: `first_id` (0), `last_id`,
`table_offset`, `palette_offset`, `bank_sha256`, `palette_sha256`,
`icon_context_sha256`, `palette_context_sha256` y `evidence` (fuentes de la revisión).
Todos esos campos se contrastan con los bytes locales. Un cambio de puntero,
contexto, rango o recurso invalida la aprobación. No se aprueban tablas mediante
el nombre del hack, el Game Code, el aspecto de unos tiles o su posición en la ROM.

Los hashes comprueban integridad e identidad de la evidencia; no sustituyen la
revisión de significado y límites. Un motor de iconos sustituido por hooks, tablas
múltiples, iconos comprimidos u otra geometría necesita su definición o soporte
específico. La evidencia capturada no implica que todos esos casos sean compatibles.

## Extracción por lote después de la revisión

El lote completo se bloquea si queda alguna variante `pending` o `error`. Antes
de crear una salida, vuelve a comprobar ROM, AIR, evidencia y definiciones de todas
las variantes elegidas. Copia las definiciones verificadas al resultado y conserva
cada ID y su procedencia. No es posible aprobar una candidata editando únicamente
su estado y recalculando el manifiesto: la comprobación se reconstruye desde el
plan actual y los bytes originales.

Este ejemplo selecciona la revisión más reciente y solo continúa si están
verificadas las 43 variantes:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Revisiones = @(Get-ChildItem -LiteralPath 'C:\FireEmblem\resultados' `
        -Directory -Filter 'revision-iconos-variantes-*' | Sort-Object Name -Descending)
    if ($Revisiones.Count -eq 0) { throw 'No hay una revisión de iconos.' }
    $Revision = $Revisiones[0].FullName
    $Informe = Get-Content -LiteralPath (Join-Path $Revision 'revision.json') `
        -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Informe.ready_for_full_batch -or $Informe.variants -ne 43) {
        throw 'Adjunta el ZIP de revisión para resolver las variantes pendientes.'
    }

    & '.\scripts\windows\Extraer-Iconos-Variantes.ps1' `
        -Revision $Revision `
        -Datos 'C:\FireEmblem' `
        -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
        -CrearZip
}
```

`-SoloVerificadas` permite una selección parcial explícita. El resumen registra
las variantes omitidas. No se ofrece como ejecución predeterminada.

Cada variante tiene su catálogo, galería, CSV, raw, PNG y paleta. `ocurrencias.csv`
conserva todas las apariciones con variante, juego, ID, offsets, hashes y rutas.
`galerias.csv` enlaza las galerías individuales. La deduplicación de archivos se
mantiene dentro de cada variante; el resumen también cuenta imágenes distintas
entre variantes sin eliminar sus procedencias. Un ID de icono no es un ID de objeto.

Si falla la creación del ZIP tras una revisión o extracción terminada, conserva
la carpeta y empaquétala con `python -m arcanacart.icon_variants pack --input
CARPETA --out ZIP_NUEVO`. No repitas la lectura o extracción para resolver un fallo
de empaquetado. Si falla una extracción, el estado queda `failed` y se conservan
los resultados completados; no se implementa reanudación automática de ese lote.

## Validación del desarrollo y límites

Se ejecutaron 64 pruebas de iconos: 29 nuevas y 35 existentes. Incluyen un flujo
completo sintético con ocho variantes FE7 y 35 FE8, procedencias de cada ID,
reubicaciones, hashes exactos de AIR, cambios de código y paleta, exclusión de
FEditorAdv, extracción parcial explícita, fallos de escritura y ZIP portables.
Las entradas sintéticas no son ROM comerciales. No sustituyen la revisión de
los bancos reales de las 43 variantes: sus bytes deben leerse en tu equipo.

No hay PowerShell instalado en el entorno de desarrollo para ejecutar los dos
lanzadores. La lógica Python y la CLI están probadas. Tampoco se certifica aquí
la presentación de las galerías en un navegador real ni la totalidad de recursos
del juego. Se mantiene la versión 0.6.4.
