# ArcanaCart 0.5.0 — continuar desde los resultados 0.4.2

Esta actualización interpreta los bloques existentes. No requiere volver a importar
ZIP, renombrar entradas, aplicar UPS ni repetir los 45 barridos LZ10. La selección
de bloques y los resultados originales permanecen disponibles en sus carpetas.

## Instalar desde el ZIP del código

El archivo contiene una carpeta `arcanacart/`, sin `.git`, entornos virtuales,
ROMs ni resultados privados. El siguiente bloque conserva una copia de los archivos
del código que va a reemplazar y copia la nueva versión al repositorio existente.
El respaldo se guarda fuera del repositorio, dentro de `C:\FireEmblem\respaldos`.
Si has editado archivos desde el ZIP entregado para esta actualización, conserva
también esos cambios antes de instalar. La alternativa con parche verifica el
contexto y rechaza los cambios incompatibles.

Descarga el ZIP como `arcanacart.zip` en Descargas y ejecuta:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $Repo = 'G:\My Drive\Portafolio\arcanacart'
    $Zip = Join-Path $env:USERPROFILE 'Downloads\arcanacart.zip'
    $Stage = Join-Path $env:TEMP ('arcanacart-0.5.0-' + [guid]::NewGuid().ToString('N'))
    $Backup = Join-Path 'C:\FireEmblem\respaldos' ('codigo-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    if (-not (Test-Path -LiteralPath $Repo -PathType Container)) { throw "No existe $Repo" }
    Expand-Archive -LiteralPath $Zip -DestinationPath $Stage
    $Source = Join-Path $Stage 'arcanacart'
    if (-not (Test-Path -LiteralPath (Join-Path $Source 'pyproject.toml'))) { throw 'El ZIP no contiene el proyecto esperado.' }
    $SourceRoot = (Resolve-Path -LiteralPath $Source).ProviderPath.TrimEnd('\')
    $Files = @(Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force)
    # Completar el respaldo antes de comenzar las sustituciones.
    foreach ($File in $Files) {
        $Relative = $File.FullName.Substring($SourceRoot.Length + 1)
        $Target = Join-Path $Repo $Relative
        if (Test-Path -LiteralPath $Target -PathType Leaf) {
            $Saved = Join-Path $Backup $Relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $Saved) -Force | Out-Null
            Copy-Item -LiteralPath $Target -Destination $Saved
        }
    }
    foreach ($File in $Files) {
        $Relative = $File.FullName.Substring($SourceRoot.Length + 1)
        $Target = Join-Path $Repo $Relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
        Copy-Item -LiteralPath $File.FullName -Destination $Target -Force
    }
    Set-Location -LiteralPath $Repo
    & 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' -m arcanacart --version
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar la version instalada.' }
    Write-Host "Respaldo de archivos anteriores: $Backup"
}
```

## Alternativa: aplicar el parche con git am

Usa esta alternativa en lugar de copiar el ZIP. El parche está construido contra
el contenido del ZIP 0.4.2 adjunto a esta conversación, incluido cualquier cambio
que este contenía respecto del commit original `e18e3545a5ea8efe90dc7ce35d7b630a449c3986`.
El SHA de cabecera del parche pertenece al snapshot de preparación; el contexto
y los blobs, no una supuesta igualdad de historial, controlan su aplicación.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'G:\My Drive\Portafolio\arcanacart'
    $Patch = Join-Path $env:USERPROFILE 'Downloads\arcanacart-0.4.2-a-0.5.0.patch'
    $State = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Git no pudo leer el repositorio; utiliza la alternativa ZIP.' }
    if ($State.Count -gt 0) { throw 'Hay cambios locales. Conservalos en un commit antes de aplicar el parche.' }
    & git apply --check --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) { throw 'El parche no coincide con el contenido actual. No se aplico.' }
    & git switch -c ('mejora/arcanacart-0.5.0-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la rama.' }
    & git -c core.whitespace=cr-at-eol am --keep-cr --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) { throw 'git am no finalizo. Revisa git status; git am --abort revierte ese intento.' }
    & 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' -m arcanacart --version
}
```

## Interpretar los resultados existentes de ambos juegos

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Set-Location -LiteralPath 'G:\My Drive\Portafolio\arcanacart'

& .\scripts\windows\Interpretar-Resultados.ps1 `
    -Datos 'C:\FireEmblem' `
    -Game all `
    -Variant '*' `
    -MaxPreviews 20000 `
    -ByteBudgetMiB 512 `
    -PixelBudgetMi 512 `
    -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
```

El script selecciona **un análisis existente por ROM**: prefiere barridos no
truncados con paso 1, después el mayor número de candidatos y finalmente el más
reciente. Imprime la carpeta elegida. Eso no compara semántica entre formatos;
si necesitas controlar exactamente la selección, usa `-AirPath`.

Cada ejecución produce una carpeta `interpretacion-0.5.0-...` nueva junto al AIR.
Abre su `index.html`. El resumen CSV muestra su ruta, los PNG, los errores y los
pendientes. No se ejecuta ningún escáner en este paso. Las ROMs preparadas solo
se utilizan para reconocer las carpetas de variantes al descubrir los análisis.

El código de salida `3` significa parcial: algún bloque faltó o cambió, hubo un
error de interpretación, un límite dejó vistas pendientes o el escaneo/comparación
de origen era parcial. El catálogo conserva las entradas pendientes y su motivo.
`0` significa que terminó el procesamiento solicitado, no que todo sea identificado.

Límites: 2 MiB por bloque leído, 1.048.576 píxeles por imagen; presupuestos de
lectura y píxeles por ROM. Los límites son de trabajo, no porcentajes de comprensión.

## Revisar y corregir una interpretación

1. Busca un hash, offset (`0x...`) o hipótesis y abre la ficha del bloque.
2. Selecciona tiles 4/8 bpp, ancho, paleta, primer color y transparencia.
3. Para mapas BG selecciona también tileset, alto y distribución. Los bancos y
   flips se leen de cada entrada. `screenblocks` admite 32/64 tiles por dimensión.
4. Documenta evidencia si aceptas el recurso; también puedes descartarlo.
5. Guarda ajustes, descarga `recipes-revisadas.json` y vuelve a interpretar
   **el mismo AIR** en una carpeta nueva mediante `--recipes` o `-Recipes`.

Los ajustes se conservan en memoria de la pestaña hasta descargarlos. Los PNG de
la página corresponden a la ejecución original; el editor no promete regenerarlos
sin ejecutar Python. `catalog.json` registra la receta usada, offsets, hashes,
hipótesis, paleta y errores. Las recetas se vinculan al hash de la ROM y del bloque.

Para escoger archivos exactos sin escribir rutas manualmente:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Set-Location -LiteralPath 'G:\My Drive\Portafolio\arcanacart'
Add-Type -AssemblyName System.Windows.Forms
$PickAir = New-Object System.Windows.Forms.OpenFileDialog
$PickAir.Title = 'Selecciona el air.json existente de la ROM'
$PickAir.Filter = 'AIR (air.json)|air.json'
if ($PickAir.ShowDialog() -eq 'OK') {
    $PickRecipes = New-Object System.Windows.Forms.OpenFileDialog
    $PickRecipes.Title = 'Selecciona recipes-revisadas.json'
    $PickRecipes.Filter = 'JSON (*.json)|*.json'
    if ($PickRecipes.ShowDialog() -eq 'OK') {
        & .\scripts\windows\Interpretar-Resultados.ps1 `
            -AirPath $PickAir.FileName `
            -Recipes $PickRecipes.FileName `
            -MaxPreviews 20000 -PixelBudgetMi 512 `
            -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    }
}
```

Si una paleta está sin comprimir en la ROM, primero extráela con `dump`, usando
un offset y tamaño documentados. `interpret --palette paleta.bin` incorpora esa
paleta al selector; registra su SHA-256 y conserva una copia en `palettes/`.
Suministra esa paleta de nuevo al regenerar las recetas. No se adivinan paletas por
proximidad, y los mapas FE con metatiles no se tratan como mapas BG de texto.

## Tablas sin repetir el barrido

`python -m arcanacart layouts` enumera los campos y tamaños incorporados:
FE7 Character/Class; FE8 Character/Class/Item. FE7 Item no se inventa: necesita una
definición documentada. `tables-define` construye un JSON ligado al hash de tu ROM:

```text
python -m arcanacart tables-define --rom ROM.gba --profile fe8-us --table Character:OFFSET:CONTEO:PRIMER_ID --evidence "Fuente y comprobación del rango" --out tablas.json
python -m arcanacart extract --rom ROM.gba --profile fe8-us --tables tablas.json --out tablas-air.json
```

Estos dos comandos muestran la sintaxis: sustituye ROM, OFFSET y CONTEO con los
valores de esa ROM; no son direcciones universales listas para aplicar a un hack.
`extract` sin `--scan` lee solo cabecera y tablas. `report`/`export` pueden generar
HTML y CSV desde ese AIR. Con `--symbols` puedes usar el nombre de un símbolo
importado en lugar de OFFSET; sigue siendo necesario validar su ubicación.

Las definiciones también aceptan `layouts`, un objeto por tipo AIR, para estructuras
adicionales o layouts alterados. Ejemplo **sintético**, no una estructura FE real:

```json
{
  "Unit": {
    "size": 4,
    "fields": [
      {"name": "character_id", "offset": 0, "fmt": "B"},
      {"name": "adjustment", "offset": 1, "fmt": "b"},
      {"name": "item_id", "offset": 2, "fmt": "H"}
    ],
    "source": "Definición sintética; reemplazar por documentación de la variante",
    "unknown": ["event_semantics"]
  }
}
```

Pasa ese objeto mediante `tables-define --layouts layouts.json`. El formato admite
enteros little-endian `b/B/h/H/i/I`, repeticiones acotadas, offsets y tamaño de
registro. Rechaza campos fuera de rango, solapamientos, formatos ejecutables,
tipos no permitidos y tablas de otro hash. Los layouts personalizados siguen
siendo inferencias. IDs incompatibles o punteros inválidos producen estado parcial.

## Código y referencias locales

Los comandos `symbols` y `disasm` siguen disponibles. `disasm` requiere una
instalación real de Ghidra, Java y el loader GBA compatible; no se instalan solos.
Consulta `GHIDRA_INTEGRATION.md`. El exportador nuevo registra rangos de
**instrucciones**, sin rellenar los huecos entre instrucciones con código supuesto.

```text
python -m arcanacart code-index --input air.json --ghidra-summary ghidra/functions/summary.json --symbols symbols.json --out indice-codigo
```

El índice verifica ROM y hashes de assembly/pseudocódigo; genera `functions/`,
`functions.json`, `code-map.json`, AIR con entidades Function e informes. Separa
rangos de instrucciones, datos/candidatos, conflictos y desconocidos. Un símbolo
de referencia no añade cobertura de código. Los exports antiguos siguen siendo
importables; si carecen de rangos, no se inventa su extensión a partir del tamaño.
Sin `--ghidra-summary` genera un mapa de pendientes con estado parcial y 0 funciones.
El pseudocódigo no se presenta como código C original ni como proyecto recompilable.

## Informes y prueba reproducible

`report --input air.json --review INTERPRETACION/summary.json --format html --out informe-nuevo.html`
agrega las métricas de interpretación al informe del escaneo sin cambiar el AIR
ni invalidar su estado/cache. Comprueba el hash de ROM y los contadores de origen.

Para probar todo el flujo gráfico sin datos de juegos:

```powershell
& 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' -m examples.generate_graphics_demo --out 'C:\FireEmblem\demo-grafica-0.5.0'
```

La carpeta debe ser nueva. El generador crea gráficos originales sintéticos, una
ROM de prueba, tablas, escaneo, recetas y galería. No contiene recursos comerciales.
Las pruebas incluidas verifican vectores de píxeles/PNG, paletas, bancos y flips,
estados de revisión, archivos faltantes/alterados, límites, definiciones personalizadas
y contratos del índice Ghidra. La validación real de tus recursos sigue pendiente:
el ZIP entregado contiene código, no tus `air.json`/`resources` ni una instalación Ghidra.
