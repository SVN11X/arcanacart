# Reanálisis de tus ROMs existentes con ArcanaCart 0.4.1

El informe de Sacred Trilogy 2.1.3 Full mostró 123 intentos, 0 bloques y un
recorrido detenido en el offset 8988 de 33291636 bytes: aproximadamente 0,027 %.
La versión 0.4.0 descontaba tamaños declarados de candidatos, incluso al fallar.
El estado global podía decir `completed` aunque la etapa de recursos era parcial.

Esta corrección valida referencias y paquetes antes de expandir, separa la cuota
de validación de los bytes producidos y prioriza cabeceras con referencias ROM.
Los topes de resultados, candidatos, trabajo y memoria siguen activos. Puede
seguir habiendo resultados parciales; ahora aparecen como tales con código 3.
La fase priorizada puede encontrar bloques lejos del inicio antes de que avance
la fase lineal. Sus métricas se presentan por separado.

## Aplicar el parche desde PowerShell

Para una copia del código 0.4.0 sin cambios incompatibles:

```powershell
Set-Location -LiteralPath 'G:\My Drive\Portafolio\arcanacart'
git apply --check "$env:USERPROFILE\Downloads\arcanacart-0.4.0-a-0.4.1.patch"
if ($LASTEXITCODE -ne 0) { throw 'El parche no coincide. No se aplicaron cambios.' }
git apply "$env:USERPROFILE\Downloads\arcanacart-0.4.0-a-0.4.1.patch"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo aplicar el parche.' }
& .\.venv\Scripts\python.exe -m arcanacart --version
```

Es un parche de commit: también admite `git am` desde un árbol limpio. La
comprobación anterior no modifica archivos. El paquete ZIP completo permite
usar una carpeta separada si tu código local ya diverge de 0.4.0.

No se repite la importación, no se renombran entradas, ni se vuelven a aplicar
los UPS. Las ROMs existentes de `C:\FireEmblem\resultados` son las entradas.

## Probar primero el mod de tu informe

En la misma terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\scripts\windows\Reanalizar-Resultados.ps1 -Datos 'C:\FireEmblem' -Game fe8 -Variant '034-*'
```

Invoca el script directamente: no necesita el comando `powershell` en PATH.
Usa el Python de `.venv` del proyecto; no necesita reinstalación ni descargas
durante el análisis. Requiere Python 3.10+.

El informe nuevo de ese mod queda en:

`C:\FireEmblem\resultados\fe8\034-sacred-trilogy-2.1.3-full-version\analisis-0.4.1-b64-r1000-c100000\report.html`

## Reanalizar las 45 ROMs preparadas

```powershell
& .\scripts\windows\Reanalizar-Resultados.ps1 -Datos 'C:\FireEmblem'
```

Recoge las dos bases y las variantes que existan en la estructura del
FireEmblem-Terminal anterior. No inventa resultados si faltan archivos.
El CSV `C:\FireEmblem\resultados\resumen-reanalisis-0.4.1.csv` incluye estado,
bloques, avance lineal, referencias revisadas y ruta del informe.
`parcial` indica que una cuota interrumpió el análisis, sin confundirlo con
un fallo al crear la ROM. Un código final 3 señala resultados parciales;
el código 2 señala errores. El resto de trabajos continúa cuando es posible.

Para cambiar cuotas de forma acotada:

```powershell
& .\scripts\windows\Reanalizar-Resultados.ps1 -Datos 'C:\FireEmblem' -Game fe8 -Variant '034-*' -BudgetMiB 128 -ResultLimit 2000 -CandidateLimit 200000
```

Los parámetros forman parte del nombre de la carpeta nueva. Aumentar cuotas
puede aumentar tiempo y espacio; no promete completar la ROM ni identificar
el significado de los bloques. La validación previa también tiene límite.

`--resume` reutiliza un bundle comprobado con las mismas opciones; no continúa
la búsqueda desde un offset intermedio. Los informes originales se conservan.

## Interpretación y acentos

Sin `--tables` se omiten las tablas semánticas. Los tres registros básicos son
Game, ROMVariant y cabecera; no son personajes ni mapas. Los bloques LZ10/RLE
son candidatos estructurales, aunque tengan referencias. No se exporta una
campaña LT-Maker ni se reconstruye automáticamente código fuente C.

El perfil automático de un hack puede seguir siendo `generic-gba`: la cabecera
no basta para confirmar una versión ni aplicar offsets de la ROM original.

Para leer AIR en Windows PowerShell 5.1 sin caracteres como `definiciÃ³n`:

```powershell
$informe = Get-Content -LiteralPath $ruta -Raw -Encoding UTF8 | ConvertFrom-Json
```

La codificación del informe es UTF-8; el parámetro evita que PowerShell 5.1
lo interprete como la página de códigos antigua del sistema.
