# Revisión de sprites de movimiento en FE7 y FE8

Este paso continúa desde los catálogos terminados de retratos, iconos y sprites
de mapa en reposo. Reúne la evidencia necesaria para revisar los sprites de
movimiento de las dos bases y las 43 variantes registradas. La versión se
mantiene en **0.6.4** y el parche se prepara sobre **main**.

El comando vuelve a comprobar la identidad de los archivos locales por sus
bytes exactos y consulta las tablas de movimiento señaladas por accesos
documentados. El inventario de candidatos se toma de los AIR existentes. No se
ejecuta el escáner ni se repiten las extracciones anteriores.

## Ejecutar en Windows

Aplica primero `arcanacart-0.6.4-revision-sprites-movimiento-main.patch` con
`git am` en `main`, conservando cualquier cambio local antes de hacerlo.

Ejecuta este bloque completo en PowerShell desde el repositorio. Se invoca
Python directamente y no se cargan scripts `.ps1`:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false

    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Datos = 'C:\FireEmblem'
    $Nombre = 'revision-sprites-movimiento-' + (Get-Date -Format 'yyyyMMdd-HHmmss') +
        '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    $Salida = Join-Path 'C:\FireEmblem\resultados' $Nombre

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "No se encuentra Python: $Python"
    }
    if (-not (Test-Path -LiteralPath $Datos -PathType Container)) {
        throw "No se encuentra la carpeta de datos: $Datos"
    }

    Write-Host 'Revisando tablas y datos AP de dos bases y 43 variantes.'

    & $Python -m arcanacart.moving_sprite_review review `
        --datos $Datos `
        --out $Salida `
        --zip ($Salida + '.zip')

    if ($LASTEXITCODE -ne 0) {
        throw "La revisión informó errores. Conserva $Salida y copia la salida completa."
    }

    Write-Host "ZIP para revisar: $($Salida + '.zip')"
}
```

El resultado normal de esta primera captura es `pending: 45`, `error: 0` y
`approved: 0`. Significa que las identidades fueron comprobadas y se recogió
la evidencia para revisarla; todavía no se habilita una extracción. Los
problemas de punteros o formatos se conservan como incidencias dentro de cada
candidata. Los errores de identidad o lectura producen código de salida 2.

Adjunta el ZIP generado y la salida JSON. Ese paquete contiene los datos
comprimidos y AP necesarios para continuar el examen fuera de las ROM.

## Contenido del paquete

- `revision.json`: resumen y resultado por ROM, con identidades, accesos,
  tablas, entradas e incidencias.
- `entradas.csv`: una fila por posición observada y vista de tabla. Dos tablas
  diferentes pueden contener la misma entrada; las filas no se anuncian como
  recursos distintos ni como clases utilizadas en una partida.
- `candidatas/`: una ficha por identidad leída correctamente. Ninguna ficha es
  una definición aprobada de extracción.
- `evidencias/`: ventanas binarias de cada acceso conocido y de cada tabla
  distinta a la que apuntan esos accesos.
- `hojas-comprimidas/`: flujos LZ10 originales, medidos y guardados por SHA-256.
- `movimientos/`: datos AP acotados y su interpretación estructural en JSON.
- `ventanas-ap/`: ventanas incompletas de hasta 16 KiB cuando el formato AP no
  puede interpretarse dentro de los límites del lector.
- `cabeceras/`: hasta 64 bytes de evidencia cuando la hoja no es LZ10 compatible.
- `identidades-usadas.json`, `fuentes.json` y
  `moving-sprites-review-state.json`: registro utilizado, fuentes y hashes de
  todos los archivos publicados.

Las hojas y datos AP iguales comparten archivo, pero todas sus posiciones,
tablas y ROM de origen permanecen en las fichas y el CSV. La correlación AIR
conserva el hash descomprimido previamente registrado, tamaños y referencias;
el hash descomprimido no se presenta como recalculado en esta revisión.

## Accesos y formato que se observan

| Juego | Ubicaciones de referencia a la tabla en ROM |
| --- | --- |
| FE7 USA | `0x6D574` |
| FE8 USA | `0x79584`, `0x79598`, `0xBAC2C`, `0xBAC40` |

La entrada nativa ocupa ocho bytes: puntero de hoja y puntero de datos AP.
En el código nativo, el índice es el ID de clase menos uno. El informe conserva
por separado `table_index` y `class_id`; esta relación queda marcada como
suposición hasta revisar los contextos de acceso de cada motor modificado.

Se observan **hasta 255 posiciones por tabla**, correspondientes a IDs nativos
propuestos 1-255. Este límite es un presupuesto de revisión. No confirma la
capacidad de una tabla, su final ni que todas sus posiciones sean clases reales.
Una entrada vacía o un puntero inválido se marca como indicio y la revisión
continúa. Las entradas posteriores tienen `post_boundary_hint: true`.

Si los accesos conocidos apuntan a tablas diferentes, se conservan todas sus
ventanas y se inspeccionan todas sus entradas dentro del mismo presupuesto.
El programa no busca nuevos punteros por la ROM. Un acceso perdido o un motor
que amplíe los IDs requiere revisar la evidencia antes de ampliar el alcance.

El lector de AP interpreta offsets relativos, tablas de fotogramas, datos OAM,
índices de tiles y comandos lineales, incluyendo sus finales y bucles como
datos. No ejecuta esos comandos. La tabla de animaciones nativa no lleva un
contador: se registra expresamente la inferencia usada para acotarla. El tamaño
de AP capturado cubre los datos referenciados reconocidos, no la reserva total
de memoria ni contenido adicional sin referencias.

Los límites del lector son 128 KiB por AP, 512 fotogramas, 64 animaciones,
4.096 comandos en total, 32 transformaciones y 128 objetos por fotograma. Las
hojas LZ10 se miden con un presupuesto de 32 KiB de salida, sin descomprimirlas.
El ancho de 32 píxeles registrado es una pista del editor, no una composición
de fotogramas aprobada. La geometría, paletas y apariencia en el juego siguen
pendientes de revisión.

## Integridad y repetición

Los hashes de ROM, AIR, tablas, LZ10, AP y ventanas se calculan sobre sus bytes
exactos. Solo la identidad del registro del repositorio se calcula con su JSON
canónico, para admitir sus finales LF/CRLF sin alterar identidades de recursos.

Se publican carpetas y ZIP nuevos. Un resultado existente no se sobrescribe.
El ZIP generado verifica el manifiesto, conserva rutas portables y comprueba
CRC. Para volver a empaquetar una revisión terminada, se puede usar:

```powershell
& 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    -m arcanacart.moving_sprite_review pack `
    --input 'C:\FireEmblem\resultados\CARPETA_DE_REVISION' `
    --out 'C:\FireEmblem\resultados\NUEVO_ARCHIVO.zip'
```

Ese subcomando utiliza los archivos ya guardados y sus hashes. La publicación
se limita a 100.000 archivos, 32 MiB por archivo y 256 MiB por paquete. Si se
excede un presupuesto, se informa el error y no se publica un paquete parcial.

## Validación del desarrollo

La suite usa ROM y datos AP sintéticos para comprobar identidades exactas,
rangos, punteros relocalizados y contradictorios, colas posteriores a huecos,
bounds de ROM/AP, corrupción y presupuestos, CSV, manifiestos, ZIP y ausencia
de escáner, descompresión y mutaciones de entradas.

También se contrastó el lector con 107 definiciones AP reconstruidas desde el
ensamblado público de FE8: se interpretaron las 107, con 2.038 fotogramas y 538
scripts. Esa comprobación se refiere al formato de las fuentes publicadas,
no a la ejecución ni a las ROM locales del usuario.

Los registros están en `docs/FUENTES_SPRITES_MOVIMIENTO_0.6.4.json` y
`docs/VALIDACION_SPRITES_MOVIMIENTO_0.6.4.json`. El siguiente paso es auditar el
ZIP local, fijar hashes y rangos explícitos y preparar la extracción de los
recursos admitidos mediante otro parche para `main`.
