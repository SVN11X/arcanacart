# Revisión de sprites de unidades en reposo

Esta etapa recoge evidencia acotada de las dos bases y las 43 variantes ya
registradas. Mantiene la versión 0.6.4. Los retratos e iconos ya extraídos no se
vuelven a procesar.

El comando utiliza Python directamente. No carga `ArcanaCart.Common.ps1`, no
necesita activar otro entorno ni cambiar la política de ejecución de PowerShell.

## Qué hace

- Comprueba sobre bytes exactos las dos ROM base y las 43 ROM variantes.
- Comprueba los 43 AIR contra los hashes del registro existente y verifica que
  identifiquen la misma ROM y tamaño. Los AIR no se normalizan por LF/CRLF.
- Usa los accesos conocidos a la tabla de reposo; conserva sus valores y los
  64 bytes anteriores a cada literal. Las discrepancias entre accesos quedan
  registradas y no se sustituyen silenciosamente por otro puntero.
- Recoge una ventana de hasta 128 registros de ocho bytes desde la tabla
  candidata: patrón de dos bytes, tamaño de dos bytes y puntero de cuatro bytes.
- Aplica la heurística de límite de FEBuilderGBA: una entrada nula después de la
  inicial, o un puntero no nulo que no sea válido. Conserva la ventana completa
  aunque la enumeración se detenga antes. Las posiciones nulas con indicadores
  no nulos se conservan como reservadas.
- Mide LZ10 únicamente en offsets apuntados por las entradas. Valida el flujo
  sin producir la salida descomprimida; conserva los bytes comprimidos exactos
  y su SHA-256. Los duplicados de esas evidencias se almacenan una sola vez.
- Relaciona offsets y tamaños con los candidatos del AIR existente. Su hash
  descomprimido se identifica como metadato de AIR, nunca como recalculado.
- Recoge siete paletas de referencia de 32 bytes en las direcciones del motor
  original. Se etiquetan como candidatas: estas direcciones no demuestran que
  una variante siga utilizando esas paletas en tiempo de ejecución.
- Compara con la base los bytes comprimidos, los indicadores y los contextos de
  acceso. Estas coincidencias no habilitan una extracción.

## Límites importantes

**128 es un presupuesto de observación, no la capacidad de una tabla.** No se
aprueban automáticamente IDs 0–127. Una variante ampliada puede necesitar una
revisión posterior. Una entrada nula puede ser un hueco; un dato no válido puede
ser código o una modificación del motor. Ninguna de estas señales prueba por sí
sola dónde termina una tabla.

Los tamaños de referencia son 16×16, 16×32 y 32×32. Se informa la correspondencia
con tres fotogramas sin recortar imágenes ni interpretar aún sus tiempos. El
editor puede mostrar recortes distintos del tamaño reservado por el motor.

Este paso no produce PNG, no descomprime hojas, no busca nuevas cabeceras por
toda la ROM y no repite escaneos de recursos. Tampoco extrae sprites de
movimiento, animaciones de combate, clases ni nombres de unidades.

**Todos los resultados válidos quedan `pending`.** Que la revisión termine con
45 pendientes y cero errores es un resultado normal. `ready_for_extraction`
permanece `false`. No se generan definiciones utilizables por un extractor.

## Ejecutar en PowerShell

Después de aplicar el parche con `git am`, ejecuta el bloque completo:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Nombre = 'revision-sprites-mapa-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
        [guid]::NewGuid().ToString('N').Substring(0, 6)
    $Salida = Join-Path 'C:\FireEmblem\resultados' $Nombre

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "No se encuentra Python: $Python"
    }

    Write-Host 'Revisando dos bases y 43 variantes. No se repite el escaneo.'
    & $Python -m arcanacart.map_sprite_review review `
        --datos 'C:\FireEmblem' `
        --out $Salida `
        --zip ($Salida + '.zip')

    if ($LASTEXITCODE -ne 0) {
        throw "La revisión informó errores. Copia la salida completa y conserva $Salida."
    }
    Write-Host "ZIP para revisar: $($Salida + '.zip')"
}
```

El registro usado es `scripts/variantes/iconos/variantes.json`, reutilizado
únicamente para sus identidades y rutas. Los rangos aprobados de iconos de
objetos no se transfieren a los sprites de mapa. Los hashes de ese plan se
calculan mediante su representación JSON canónica para admitir LF/CRLF.

Las bases se buscan en `resultados/fe7/fe7-usa-base.gba` y
`resultados/fe8/fe8-usa-base.gba`, dentro de `--datos`. Las variantes utilizan las
rutas registradas. El informe no modifica ROM, AIR, planes ni resultados previos.

`--scope bases` permite limitar una revisión a las dos bases si se necesita
diagnosticar una incidencia. El alcance predeterminado es ambas bases más todas
las variantes.

## Archivos obtenidos y revisión posterior

- `revision.json`: identidades, errores, límites, entradas y comparaciones.
- `entradas.csv`: entradas enumeradas; los campos de listas usan JSON.
- `candidatas/`: fichas de evidencia sin aprobación de extracción.
- `evidencias/`: ventanas de tabla, contextos de acceso, paletas de referencia y
  cabeceras que requieran revisar un formato no compatible.
- `hojas-comprimidas/`: flujos LZ10 apuntados por la tabla, conservados como
  evidencia comprimida y deduplicados por bytes exactos.
- `identidades-usadas.json`, `fuentes.json` y
  `map-sprites-review-state.json`: registro, fuentes y hashes de los artefactos.

El ZIP usa separadores portables y comprueba CRC. Si solo falló la creación del
ZIP, el subcomando `pack --input CARPETA_REVISION --out NUEVO_ZIP` permite volver
a empaquetar la evidencia terminada sin releer ROM ni AIR.

El siguiente paso consiste en revisar ese ZIP, justificar los rangos y paletas
por juego/variante y preparar definiciones ligadas a hashes para la extracción
de hojas y fotogramas. No se debe habilitar el lote solo por obtener cero
errores en esta recopilación.

## Fuentes y comprobación del desarrollo

Se fijan las revisiones de FEBuilderGBA y de la descompilación de FE8 en
`docs/FUENTES_SPRITES_MAPA_0.6.4.json`. La tabla de referencia de FE8 contiene 107
entradas en esa fuente; este dato no se aplica como capacidad a sus variantes.

Pruebas: 25 casos nuevos con ROM sintéticas y las 111 pruebas existentes de
iconos. Incluyen una recopilación sintética con dos bases y 43 variantes,
punteros trasladados o contradictorios, límites de lectura, LZ10 inválido,
hashes ROM/AIR, conservación de entradas, publicación y ZIP. La aplicación del
parche se comprueba con `git am` y modos de checkout LF/CRLF.

No se dispone aquí de las ROM completas del usuario; la revisión real de los
45 archivos queda pendiente del comando anterior. No se ha ejecutado Windows
PowerShell en el entorno de desarrollo.
