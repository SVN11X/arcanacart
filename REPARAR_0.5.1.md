# Reparar las previsualizaciones de ArcanaCart 0.5.0

La versión 0.5.1 corrige el error `La imagen supera el límite de 1048576 píxeles.`
en hojas de tiles grandes. Los bloques de 1.114.112 bytes producen 2.228.224 píxeles
al interpretarlos como 4 bpp. A 16 tiles de ancho, ahora se exportan como 17 páginas
de 128 × 1024 píxeles. Cada página registra su primer tile, cantidad de tiles,
offset y cantidad de bytes. No se recorta el bloque ni se aumenta el límite de
memoria de cada imagen. La galería permite seleccionar y descargar cada página.

Esto sigue siendo una interpretación gráfica: no demuestra que el bloque sea
un gráfico real ni descarta falsos positivos del escáner.

## Ejecutar desde el ZIP en C:

Descarga **arcanacart-0.5.1.zip** en Descargas. El comando extrae el código en una
carpeta local nueva de C:, comprueba la versión y repara las galerías parciales
referenciadas por tu CSV. No necesita Git ni instalar dependencias. Utiliza
explícitamente el Python que ya funciona.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Zip = Join-Path $env:USERPROFILE 'Downloads\arcanacart-0.5.1.zip'
    $Csv = 'C:\FireEmblem\resultados\resumen-interpretacion-20261018-203337-146-ab2de3.csv'
    $Destino = Join-Path 'C:\FireEmblem' (
        'codigo-arcanacart-0.5.1-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    )

    foreach ($Archivo in @($Python, $Zip, $Csv)) {
        if (-not (Test-Path -LiteralPath $Archivo -PathType Leaf)) {
            throw "No se encuentra: $Archivo"
        }
    }
    Expand-Archive -LiteralPath $Zip -DestinationPath $Destino
    $Repo = Join-Path $Destino 'arcanacart'
    Set-Location -LiteralPath $Repo
    $Version = (& $Python -c 'import arcanacart; print(arcanacart.__version__)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -ne '0.5.1') {
        throw "Version inesperada en el ZIP: $Version"
    }
    Write-Host "ArcanaCart $Version; codigo en $Repo"

    & .\scripts\windows\Reparar-Previsualizaciones.ps1 `
        -ResumenCsv $Csv -PythonExe $Python
}
```

El reparador utiliza la columna `Galeria` del CSV y busca el AIR original en el
directorio superior de cada interpretación. En cada galería comprueba los hashes
del AIR, el inventario de candidatos y los metadatos originales. Solo vuelve a
leer los bloques con el error de tamaño indicado y sus dependencias de paleta.
Conserva los PNG que ya estaban generados sin releerlos ni sobrescribirlos; las
recetas y decisiones manuales permanecen. No ejecuta el escáner, comparaciones,
tablas ni Ghidra.

Muestra `[n/total]` por galería y el bloque que está reparando. El tiempo depende
de cuántos bloques grandes haya entre las galerías parciales y de tu equipo;
el listado previo de selección de las 45 ROMs no permitía estimarlo.

Al finalizar, muestra la ruta de un **CSV nuevo** `resumen-reparacion-*.csv`.
Conserva las 45 filas y añade `Elegibles`, `Reparados`, `PNGNuevos` y `Respaldo`.
El CSV original se mantiene como registro de la ejecución anterior. Abre de
nuevo la galería o recarga la pestaña para ver sus nuevas páginas.

## Qué se repara y qué queda pendiente

- Repara exclusivamente errores de imagen demasiado grande en recetas `tiles`
  verificadas y no rechazadas. Mantiene el modo, ancho, bpp, transparencia y
  paleta usados en la interpretación original.
- Los errores de lectura, paleta, mapa u otras causas permanecen registrados.
  Una galería sigue como `partial` si quedan errores, vistas omitidas, un escaneo
  truncado o una comparación parcial. No se fuerza su estado a `completed`.
- `generated_previews` cuenta **bloques con vista**. `generated_png_files` cuenta
  **archivos PNG**, incluidas todas las páginas. El CSV nuevo utiliza archivos
  PNG en su columna `PNG`.
- `pending_interpretation` cuenta bloques aún sin interpretación aceptada o
  rechazada. No es una cola de ejecución ni baja automáticamente por generar PNG.
- Cada reparación admite por defecto 20.000 **nuevos PNG**, 512 MiB de lectura y
  512 Mi píxeles nuevos **por galería**. Los PNG previos no consumen ese presupuesto.
  Se comprueba el presupuesto del bloque completo antes de dibujar sus páginas.
  Si no alcanza, se conserva el error con un `repair_error` explicativo y puede
  reintentarse con límites mayores. Aumentar el presupuesto global en 0.5.0 no
  corregía el límite de una sola imagen.
- Se guardan respaldos de metadatos en `repairs/<identificador>/before` dentro de
  cada galería modificada. Las páginas y metadatos nuevos se preparan antes de
  publicarse. Un error durante la publicación restaura los metadatos originales
  y retira únicamente las páginas de esa reparación. Una interrupción abrupta se
  recupera al volver a ejecutar el reparador, siempre que nadie haya modificado
  después esos archivos. Si un cierre abrupto dejó `.arcanacart.lock`, comprueba
  que no siga activo ningún proceso sobre esa galería antes de retirar ese bloqueo
  residual y reintentar.
- Volver a ejecutar el mismo comando omite los bloques ya reparados. Si cambiaste
  manualmente `catalog.json`, `recipes.json` u otro metadato original, el reparador
  lo detecta y conserva esos cambios en lugar de mezclarlos.

## Plan opcional y reparación de una sola galería

Desde la carpeta de código 0.5.1, este comando cuenta el trabajo sin cambiar las
galerías. Produce un CSV de planificación aparte:

```powershell
& .\scripts\windows\Reparar-Previsualizaciones.ps1 `
    -ResumenCsv 'C:\FireEmblem\resultados\resumen-interpretacion-20261018-203337-146-ab2de3.csv' `
    -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    -SoloPlan;
```

Si conservas las variables `$Carpeta` y `$Csv` de tu diagnóstico, puedes reparar
solamente la galería elegida con:

```powershell
& {
    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Air = Join-Path (Split-Path -Parent $Carpeta) 'air.json'
    & $Python -m arcanacart repair-previews `
        --input $Air --review $Carpeta --verbose
}
```

El CLI devuelve 0 si el estado final es `completed`, 3 si es `partial` y 2 ante
un error que impida ejecutar la reparación. Los detalles por bloque están en
`catalog.json`; el resumen actualizado está en `summary.json`.

## Alternativa con Git

El parche `arcanacart-0.5.0-a-0.5.1.patch` requiere los archivos exactos del ZIP
0.5.0 entregado anteriormente, con un repositorio Git inicializado y limpio.
No es necesario usar esta alternativa si ya extraíste el ZIP 0.5.1. No ejecutes
estos comandos en una carpeta sin `.git`.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $Patch = Join-Path $env:USERPROFILE 'Downloads\arcanacart-0.5.0-a-0.5.1.patch'
    & git rev-parse --is-inside-work-tree
    if ($LASTEXITCODE -ne 0) { throw 'Esta carpeta no es un repositorio Git. Usa el ZIP.' }
    $State = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $State.Count -gt 0) { throw 'Se necesita un repositorio limpio.' }
    & git apply --check --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) { throw 'El parche no coincide. Usa el ZIP 0.5.1.' }
    & git switch -c ('correccion/previews-0.5.1-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la rama.' }
    & git -c core.whitespace=cr-at-eol am --keep-cr --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) { throw 'Revisa git status. git am --abort revierte este intento.' }
    & 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' -m arcanacart --version
}
```

El respaldo y la reparación se ejecutan en C:; este procedimiento no depende de
copiar metadatos de archivos desde la carpeta de Drive que produjo `Incorrect function`.
