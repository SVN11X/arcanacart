# ArcanaCart 0.6.1: retratos de FE7 y FE8

Esta actualización incorpora la base FE8 USA exacta al extractor de retratos.
Reutiliza el `air.json` y los bloques de tus análisis terminados. Lee desde la
ROM local los componentes sin compresión y las paletas que no pertenecen al
inventario LZ10. Crea una salida nueva sin modificar los análisis ni las galerías
anteriores.

## 1. Aplicar el parche en tu repositorio actualizado

Descarga `arcanacart-0.6.0-a-0.6.1.patch` en Descargas. El parche se genera sobre
el commit `fe26c622e98a82faa794838c58769fc01dd8cb5d`, que subiste a GitHub.
No requiere instalar paquetes adicionales. Usa el Python que ya funciona.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'
    $Patch = Join-Path $env:USERPROFILE 'Downloads\arcanacart-0.6.0-a-0.6.1.patch'

    if (-not (Test-Path -LiteralPath $Patch -PathType Leaf)) {
        throw "No se encuentra el parche: $Patch"
    }
    $State = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Git no pudo leer este repositorio.' }
    if ($State.Count -gt 0) {
        throw 'Conserva tus cambios locales en un commit antes de aplicar el parche.'
    }

    & git apply --check --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) {
        throw 'El parche no coincide con estos archivos. No se aplico.'
    }
    & git switch -c ('mejora/arcanacart-0.6.1-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la rama.' }
    & git -c core.whitespace=cr-at-eol am --keep-cr --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) {
        throw 'git am se detuvo. Revisa git status; git am --abort revierte este intento.'
    }

    & 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' -m arcanacart --version
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar la version.' }
};
```

También se entrega `arcanacart-0.6.1.zip` con el código completo bajo la carpeta
`arcanacart/`. Ese ZIP no contiene ROMs, bloques extraídos, entornos ni archivos
Git. Conserva la carpeta `.git` y tus archivos locales si usas el ZIP para
actualizar el código de un repositorio existente.

## 2. Extraer FE8 en color desde tu repositorio

Con el parche aplicado, copia este bloque. La ruta predeterminada de la ROM es
`C:\FireEmblem\resultados\fe8\fe8-usa-base.gba`. Si el archivo está en otra
carpeta, cambia solo `-RomPath`.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'
    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Version = (& $Python -c 'import arcanacart; print(arcanacart.__version__)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -ne '0.6.1') {
        throw "Se requiere ArcanaCart 0.6.1. Version detectada: $Version"
    }

    & .\scripts\windows\Extraer-Retratos.ps1 `
        -Game fe8 `
        -AirPath 'C:\FireEmblem\resultados\fe8\base-0.4.2-lz10-b128-r20000-c500000\air.json' `
        -RomPath 'C:\FireEmblem\resultados\fe8\fe8-usa-base.gba' `
        -PythonExe $Python `
        -CrearZip `
        -Abrir
};
```

Alternativa si prefieres seleccionar el AIR mediante tu CSV existente:

```powershell
& .\scripts\windows\Extraer-Retratos.ps1 `
    -Game fe8 `
    -ResumenCsv 'C:\FireEmblem\resultados\resumen-reparacion-20261022-192904-698-0731b4.csv' `
    -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    -CrearZip -Abrir
```

No necesitas activar la `.venv` del repositorio: el bloque llama directamente al
Python configurado. Los scripts se ejecutan con `&`, sin depender de
`powershell.exe` en PATH.

## 3. Qué resultados esperar

La tabla documentada de esta base FE8 contiene 172 entradas útiles:

| Componente | PNG esperados con la ROM local | Procedencia |
| --- | ---: | --- |
| Retratos | 115 | Datos raw con cabecera `00` |
| Miniaturas | 111 | Bloques LZ10 del AIR |
| Tarjetas de clase | 57 | Bloques LZ10 del AIR |
| Total | 283 | Conteos por ID, con posibles reutilizaciones |

En el ZIP de validación recibido se verificaron los 4.400 bloques y se
reprodujeron las 111 miniaturas y 57 tarjetas. Son 126 bloques únicos del AIR.
Los 115 retratos raw y las paletas necesitan leerse desde tu ROM local; no
estaban en el ZIP. Los conteos completos deben confirmarse en esa ejecución.

La base admitida tiene SHA-256:

```text
638cda9d9b72657220fbf7e7a500cd3b64d9686c36e8a56fca69d26d13886f2f
```

La salida se crea junto al AIR en una carpeta nueva `retratos-0.6.1-.../`:

- `index.html`: galería local con filtros y descargas.
- `retratos/`, `miniaturas/`, `tarjetas-clase/`: PNG por ID.
- `paletas/`: paletas reales de 32 bytes y sus muestras PNG.
- `raw-resources/`: payloads raw leídos de la ROM, nombrados por SHA-256.
- `catalog.json` y `catalog.csv`: origen, offsets, tamaños, hashes y paleta.
- `summary.json`, `report.md`, `faces-state.json`: resultados e integridad.

Los datos raw se contabilizan aparte: `unique_classified_blobs` cuenta solo
bloques del AIR; `unique_raw_rom_blobs` cuenta los raw exportados. La cabecera
raw `00` declara el tamaño **incluidos sus cuatro bytes**, y `source_offset`
apunta a esa cabecera; `payload_offset` apunta a los tiles. `compressed_bytes`
es cero para raw y `stored_bytes` incluye su cabecera. El hash `encoded_sha256`
cubre la representación almacenada completa y `source_sha256` cubre el payload.

`status: completed` describe esta extracción de componentes. No significa que
todos los recursos del juego estén identificados o que esté desensamblado.
Las animaciones de ojos y boca y los nombres de personajes quedan pendientes.

## 4. FE7, variantes y uso sin ROM

FE7 conserva su extracción. El parámetro predeterminado sigue siendo
`-Game fe7`; también puedes indicarlo explícitamente. Tus resultados de FE7
0.6.0 ya verificados siguen siendo válidos y no requieren repetirse.

Las variantes requieren una definición validada ligada a su propio SHA-256,
con ubicación y número de entradas confirmados. No se trasladan las
ubicaciones ni los conteos de la base a una modificación por compartir
cabecera o nombre. El formato `arcanacart-face-layout-1` continúa admitido;
puedes pasarlo con `-Definition` o `--definition`.

Sin ROM, `-SinRom` exporta en gris solo los componentes presentes en los
bloques. En FE8 se espera entonces `partial`, cero retratos, 111 miniaturas,
57 tarjetas y 115 componentes pendientes. Es una limitación del material de
entrada; aumentar el presupuesto LZ10 no recupera esos datos raw.

## Referencias y comprobaciones

Los offsets, el tamaño de entrada y el formato raw se contrastaron con fuentes
primarias fijadas a un commit. Consulta [docs/VERIFICACION_0.6.1.md](docs/VERIFICACION_0.6.1.md)
para conocer las referencias, las pruebas ejecutadas y sus límites.
