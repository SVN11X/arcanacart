# Flujo integrado de ArcanaCart 0.4.2

Esta versión incorpora lo comprobado en las pruebas de terminal. La búsqueda
LZ10 completa de Sacred Trilogy 2.1.3 Full produjo 12.384 candidatos y 11.706
salidas únicas. La comparación de manifiestos con FE8 USA registró 3.815 salidas
coincidentes y 7.891 sin coincidencia. Esos números describen candidatos de esa
ROM, no tipos de recursos identificados ni una reconstrucción del juego.

## Actualizar desde 0.4.1

Desde PowerShell en tu repositorio:

```powershell
$parche = Join-Path $env:USERPROFILE 'Downloads\arcanacart-0.4.1-a-0.4.2.patch'
git apply --check $parche
if ($LASTEXITCODE -ne 0) { throw 'El parche no coincide; no se aplicaron cambios.' }
git apply $parche
if ($LASTEXITCODE -ne 0) { throw 'No se pudo aplicar el parche.' }
& 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' -m arcanacart --version
```

Los comandos usan el entorno local que ya funcionó. El indicador de una terminal
activada no garantiza que su `.venv` tenga una configuración válida. Puedes usar
la ruta completa del intérprete desde la raíz del repositorio.

## Analizar una ROM con informe completo del alcance solicitado

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    $python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $carpeta = 'C:\FireEmblem\resultados\fe8\034-sacred-trilogy-2.1.3-full-version'
    $argumentos = @(
        '-m', 'arcanacart', 'pipeline', '--compression', 'lz10'
        '--rom', (Join-Path $carpeta 'fe8-mod.gba')
        '--out', (Join-Path $carpeta 'analisis-0.4.2-lz10-b64-r20000-c500000')
        '--budget', '67108864', '--limit', '20000', '--max-candidates', '500000'
        '--resume'
    )
    & $python @argumentos | Out-Null
    if ($LASTEXITCODE -notin @(0, 3)) { throw 'El pipeline fallo.' }
}
```

Produce `air.json`, `entities.csv`, recursos únicos, estado por hashes e informes
HTML/Markdown. El informe indica que RLE queda fuera de este barrido. Tablas,
textos, mapas, eventos y código requieren parsers o referencias específicos.
El 100 % cuenta posiciones revisadas bajo los límites elegidos. La validación
estructural no convierte automáticamente cada candidato en un recurso real.

## Comparar los manifiestos que ya generaste

No hace falta volver a descomprimirlos para comparar:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    $python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $scan = 'C:\FireEmblem\resultados\fe8\034-sacred-trilogy-2.1.3-full-version\escaneo-lz10-20261017-212615-161'
    $argumentos = @(
        '-m', 'arcanacart', 'compare-resources'
        '--left', (Join-Path $scan 'comparacion-base-20261017-213458-881\base-lz10.json')
        '--right', (Join-Path $scan 'resources.json')
        '--out', (Join-Path $scan 'comparacion-integrada-0.4.2')
    )
    & $python @argumentos
    if ($LASTEXITCODE -notin @(0, 3)) { throw 'La comparacion fallo.' }
}
```

Este comando acepta el `base-lz10.json` anterior y el manifiesto del mod. Los
resultados se escriben en una carpeta nueva. El catálogo conserva hashes,
offsets, tamaños y referencias, y marca patrones uniformes conocidos. `False`
en `coincide_base` significa no observado en los candidatos de la base.

## Reanalizar las 45 ROMs preparadas y comparar con sus bases

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\scripts\windows\Reanalizar-Resultados.ps1 `
    -Datos 'C:\FireEmblem' -Compression lz10 -CompareBase `
    -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
```

La selección `-Game fe8 -Variant '034-*' -CompareBase` analiza la base FE8 y esa
variante. Los valores por defecto son 64 MiB, 20.000 resultados y 500.000 intentos.
Algunas ROMs pueden seguir alcanzando una cuota; se informan como parciales.
`-Compression lz10,rle` solicita ambos formatos. Cada ejecución guarda un CSV
con fecha para conservar los resúmenes anteriores. El script prioriza el entorno
`Datos\entorno-arcanacart\Scripts\python.exe` si existe y no indicas `-PythonExe`.

Las ROMs ya preparadas son las entradas de este flujo. La organización previa de
ZIP y la aplicación de los UPS siguen siendo pasos independientes. `--resume`
reutiliza una carpeta verificada con las mismas opciones, incluso si es parcial;
no continúa desde el último byte. Cambiar formatos exige otra carpeta.
