# Completar la evidencia de sprites de mapa

La revisión inicial `revision-sprites-mapa-20261024-100718-0df611.zip` pasó la
auditoría independiente: 24.956 comprobaciones y cero errores. Sus 873 archivos,
ventanas de tabla, contextos, paletas de referencia, CSV y hashes son coherentes.
Las 238 hojas comprimidas producen 193 contenidos descomprimidos distintos; los
hashes de las 5.184 referencias de variantes coinciden con el inventario AIR
anterior. El registro detallado está en
`docs/AUDITORIA_REVISION_SPRITES_MAPA_0.6.4.json`.

## Por qué falta esta ampliación

| Grupo | Entradas de hojas recopiladas por ROM | Evidencia del índice |
| --- | ---: | --- |
| Base FE7 y ocho variantes FE7 | 88, IDs 0–87 | Máscara observada `0x7F` |
| Base FE8 | 107, IDs 0–106 | Máscara observada `0x7F` |
| 35 variantes FE8 | 128, IDs 0–127 | Máscara observada `0xFF` |

En las 35 variantes FE8, las 128 entradas son válidas y se alcanzó el presupuesto
de observación sin encontrar siquiera una señal de final. La instrucción Thumb
en el acceso principal cambió de `MOVS r4,#127` a `MOVS r4,#255`, seguida del
enmascarado y multiplicación por ocho para acceder al registro. También se
observan los cambios de máscara en los demás contextos recogidos. El prefijo de
128 no basta para revisar ese acceso de ocho bits.

Los contextos de 68 bytes incluidos en el primer paquete no cubren el código de
carga de paletas. Que los siete bloques de referencia coincidan con los de las
bases no demuestra qué bloque carga el motor modificado.

Estas son razones concretas para ampliar la evidencia antes de habilitar un
extractor. La versión sigue siendo **0.6.4**.

## Alcance del parche

- Acepta únicamente el contenido exacto de la revisión inicial auditada, por
  SHA-256 del informe y de su manifiesto completo. Puede recibir ZIP o carpeta.
- Conserva todos sus archivos, byte a byte, dentro de `revision-anterior/`.
- Vuelve a comprobar el SHA-256 exacto de las 45 ROM antes de leer nuevos rangos.
- Recoge una ventana de código de 1.024 bytes por ROM: 512 antes y 512 después
  del literal principal de acceso a la tabla. Se conserva como evidencia para
  revisar la carga de paletas; no se aprueba automáticamente su interpretación.
- Reutiliza las entradas ya recopiladas. No vuelve a medir sus hojas LZ10.
- Solo para las 35 variantes FE8 continúa desde el ID 128 hasta el 255, dentro
  de una ventana de tabla de hasta 2.048 bytes. Comprueba de nuevo los AIR de
  esas variantes para relacionar los nuevos offsets con su análisis existente.
- Continúa después de entradas nulas o punteros no válidos, conservando la
  primera señal de límite y marcando las posiciones siguientes con
  `post_boundary_hint`. Un hueco no se toma como demostración del final de tabla.
- Conserva como candidatos los tamaños o flujos no compatibles. Una entrada
  posterior a una señal de límite puede ser un hueco, datos ajenos o un recurso
  legítimo: requiere revisar la evidencia, no basta su posición en la ventana.
- Reutiliza las hojas comprimidas anteriores cuando coinciden por bytes; solo
  incorpora un archivo adicional por cada nueva secuencia comprimida distinta.

**256 es el límite de observación de esta ampliación, no una capacidad de tabla
aprobada.** No se producen PNG, no se descomprimen hojas en el equipo del usuario
y no se ejecuta ningún escáner de ROM. Las ROM y AIR completos no se incluyen en
el paquete generado.

## Ejecutar con Python desde PowerShell

Aplica el parche mediante `git am` y ejecuta el bloque completo. Usa la ruta de
Python directamente; no requiere cargar auxiliares `.ps1`.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Revision = 'C:\FireEmblem\resultados\revision-sprites-mapa-20261024-100718-0df611.zip'
    $Nombre = 'revision-sprites-mapa-ampliada-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
        [guid]::NewGuid().ToString('N').Substring(0, 6)
    $Salida = Join-Path 'C:\FireEmblem\resultados' $Nombre

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "No se encuentra Python: $Python"
    }
    if (-not (Test-Path -LiteralPath $Revision -PathType Leaf)) {
        throw "No se encuentra la revisión: $Revision"
    }

    Write-Host 'Reutilizando la revisión; completando la cola FE8 y el contexto de paletas.'
    & $Python -m arcanacart.map_sprite_followup extend `
        --review $Revision `
        --datos 'C:\FireEmblem' `
        --out $Salida `
        --zip ($Salida + '.zip')

    if ($LASTEXITCODE -ne 0) {
        throw "La ampliación informó errores. Copia la salida y conserva $Salida."
    }
    Write-Host "ZIP para revisar: $($Salida + '.zip')"
}
```

El resultado esperado tiene 45 ROM pendientes, cero errores, 35 ampliaciones de
cola terminadas, 45 contextos de paleta y `old_entries_remeasured: 0`. Las
paletas continúan con `runtime_use_verified: false` y
`ready_for_extraction` sigue siendo `false` hasta auditar esta evidencia nueva.

El ZIP completo conserva la revisión inicial y los archivos adicionales.
`revision.json` y `entradas.csv` en su raíz describen el estado ampliado. Si
solo falla el empaquetado, `python -m arcanacart.map_sprite_followup pack --input
CARPETA --out NUEVO_ZIP` permite reintentarlo sin volver a abrir ROM ni AIR.

## Validación del desarrollo

- 42 pruebas de revisión de sprites: 25 anteriores y 17 nuevas. Verifican que no
  se repita el prefijo, que se conserve un recurso posterior a un hueco, los
  hashes exactos ROM/AIR, las rutas seguras y la conservación íntegra del paquete.
- Las 111 pruebas de iconos existentes siguen pasando.
- Se reprodujeron las 45 ventanas iniciales con los bytes capturados: 5.864
  comparaciones de evidencias sin diferencias tras compartir el lector por
  intervalos. No se usaron ROM completas para esta reproducción.
- Se verificó la admisión del ZIP real auditado y la selección exacta de sus 35
  variantes FE8 antes de abrir ROM.
- Aplicación probada mediante `git am` en modos LF y CRLF. La revisión ampliada
  real queda pendiente de la ejecución local; no se dispone aquí de las ROM
  completas ni se ha ejecutado Windows PowerShell en este entorno.
