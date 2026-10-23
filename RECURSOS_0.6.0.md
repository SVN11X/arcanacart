# ArcanaCart 0.6.0: extracción organizada de retratos

El paquete real de la base FE7 permitió vincular y reconstruir **195 entradas de
retrato, 191 miniaturas y 33 tarjetas de clase**. Son 419 componentes por ID,
procedentes de **304 bloques únicos**; algunas entradas comparten gráficos.
Los otros 3.463 bloques del inventario siguen sin clasificación en esta etapa.

El ZIP de validación contiene AIR, bloques LZ10 descomprimidos y metadatos de
interpretación. Las paletas de estos retratos se leen sin compresión desde la
ROM y no están incluidas como recursos comprimidos en ese paquete. Por eso la
entrega de muestra usa grises de diagnóstico. El índice de color de un píxel no
es su brillo: las caras pueden verse oscuras hasta aplicar su paleta real.

## Generar los recursos en color en Windows

Descarga **arcanacart-0.6.0.zip** en Descargas y pega el siguiente bloque.
Utiliza tu CSV de reparación para localizar el AIR de la base FE7 y busca la ROM
preparada en `C:\FireEmblem\resultados\fe7\fe7-usa-base.gba`.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Zip = Join-Path $env:USERPROFILE 'Downloads\arcanacart-0.6.0.zip'
    $Destino = Join-Path 'C:\FireEmblem' (
        'codigo-arcanacart-0.6.0-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    )

    if (-not (Test-Path -LiteralPath $Zip -PathType Leaf)) { throw "No se encuentra $Zip" }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "No se encuentra $Python" }
    Expand-Archive -LiteralPath $Zip -DestinationPath $Destino
    Set-Location -LiteralPath (Join-Path $Destino 'arcanacart')

    $Version = (& $Python -c 'import arcanacart; print(arcanacart.__version__)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -ne '0.6.0') { throw "Version inesperada: $Version" }

    & .\scripts\windows\Extraer-Retratos.ps1 `
        -ResumenCsv 'C:\FireEmblem\resultados\resumen-reparacion-20261022-192904-698-0731b4.csv' `
        -PythonExe $Python -CrearZip -Abrir
};
```

El programa comprueba que la ROM local coincida con el SHA-256 y tamaño del AIR.
Después verifica la tabla, el contenido de cada bloque comprimido utilizado y
su descompresión puntual. Recupera la paleta de 16 colores correspondiente a cada
entrada y genera los componentes en una carpeta nueva junto al AIR, llamada
`retratos-0.6.0-...`. Imprime su ubicación y abre `index.html`. La opción
`-CrearZip` crea además un ZIP de los resultados exportados.

La ROM se lee localmente y **no se incluye en el ZIP de resultados**. El
procedimiento reutiliza el inventario existente. No vuelve a ejecutar el escáner
LZ10, ni sustituye la galería anterior, los bloques o las recetas manuales.

Si tu ROM está en otra ruta, desde la carpeta de código 0.6.0 añade
`-RomPath 'C:\ruta\fe7-usa-base.gba'` al comando del script. También puedes
seleccionar directamente un AIR con `-AirPath` en lugar del CSV.

## Archivos generados

| Ruta | Contenido |
| --- | --- |
| `retratos/face-XXX.png` | Retrato de 96 × 80 ensamblado con el layout estándar. |
| `miniaturas/face-XXX.png` | Miniatura de 32 × 32. |
| `tarjetas-clase/face-XXX.png` | Tarjeta ordenada con 10 tiles de ancho; el alto depende del bloque. |
| `paletas/<sha256>.bin` | Paleta RGB555 original de 32 bytes, cuando se proporciona la ROM. |
| `paletas/<sha256>.png` | Muestra de los colores de la paleta. |
| `catalog.json` y `catalog.csv` | ID, tipo, ubicación del campo de tabla, offset y hash de bloque y paleta. |
| `summary.json` y `report.md` | Cifras, alcance, verificaciones y limitaciones. |
| `index.html` | Galería local con filtros y descarga de PNG. |
| `faces-state.json` | Estado de ejecución e inventario de hashes de los archivos generados. |

`XXX` es el ID hexadecimal de la entrada; **no es el ID de personaje** ni su
nombre. El catálogo no asigna nombres por parecido visual. Un mismo gráfico
puede aparecer en varias entradas y utilizar distintas paletas.

## Alcance de la identificación

El layout automático está ligado exclusivamente a la base FE7 USA con SHA-256:

```text
f1200d19771b366b6ead15dec0eee4a7785b538d894c069c36f7592321ee799b
```

- Tabla en el offset `0xC96584`; puntero a la tabla en `0x6B30`.
- Entradas de 28 bytes; intervalo configurado de 229 entradas, incluida la 0
  reservada. La reconstrucción procesa los ID `0x001` a `0x0E4`.
- Campos `+0`: retrato; `+4`: miniatura; `+8`: paleta; `+16`: tarjeta de clase.
- El vínculo usa las referencias del AIR y los hashes de los bloques. Con
  `--rom`, se comprueban también los valores reales de los punteros y los bytes
  originales. El conteo del intervalo se ha contrastado con las entradas
  observadas de esta base; no se reutiliza automáticamente en variantes.
- La clasificación se registra como `documented-table-link`. Es independiente
  de `identified_by_user_review`: no modifica decisiones de aceptación manual.
- Esta etapa produce imágenes estáticas. Los fragmentos originales permanecen
  en `resources`; todavía no se reconstruyen animaciones de ojos o boca,
  asociaciones con personajes, fondos, mapas ni animaciones de combate.

## Uso del CLI y otras ROMs

```powershell
& 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' -m arcanacart faces `
    --input 'C:\ruta\air.json' `
    --rom 'C:\ruta\fe7-usa-base.gba' `
    --out 'C:\FireEmblem\retratos-nuevos' --verbose;
```

Sin `--rom`, se reconstruyen los componentes observados con una escala de gris.
El estado será `partial` porque faltan paletas reales, aunque `errors` sea cero.
`--dry-run` valida y planifica sin crear la carpeta de salida. El CLI devuelve 0
para `completed`, 3 para `partial` y 2 ante un error que impida la ejecución.

Las variantes y otras ROMs requieren `--definition` con un JSON
`arcanacart-face-layout-1` ligado a su hash, ubicación de tabla y número de
entradas. La definición no se puede trasladar entre ROMs cambiando solamente el
hash: hay que comprobar la ubicación, los campos y la distribución gráfica.
El ensamblado implementado es el layout estándar; ampliaciones de retratos y
componentes sin compresión necesitan un parser propio y se reportan pendientes.

## Continuación

Primero se comprobarán los colores y se documentarán las asociaciones entre ID y
personajes. Después podrán trasladarse las identificaciones por contenido a las
variantes, validando cada tabla y su paleta. El trabajo posterior incluye fondos
con sus mapas de tiles, gráficos de mapa, tablas de personajes/clases/objetos y
el índice de código. Las cifras de esta etapa no representan desensamblado
completo ni identificación de todo el juego.

## Referencias del formato

- [StanHash/fe7_us, código del acceso a la tabla](https://github.com/StanHash/fe7_us/blob/5c8b3c5e254e00f0f3458b9772c27e1a5a326e3b/asm/code_1.s): `func_08006B20` calcula `base + id × 28`; el literal en `0x08006B30` apunta a `0x08C96584`.
- [FEBuilderGBA, estructura y distribución de retratos](https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ImagePortraitForm.cs): campos de entrada, dimensiones y regiones gráficas.

La implementación nueva utiliza estas descripciones del formato y las
referencias presentes en el AIR. No se incluyen fuentes de esos proyectos ni
ROMs en el ZIP del código.

## Parche alternativo

`arcanacart-0.5.1-a-0.6.0.patch` parte del ZIP de código 0.5.1 entregado en esta
conversación. Si ya usas el ZIP 0.6.0, no necesitas aplicar el parche. En un
repositorio Git limpio cuyo contenido corresponda a 0.5.1:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $Patch = Join-Path $env:USERPROFILE 'Downloads\arcanacart-0.5.1-a-0.6.0.patch'
    & git rev-parse --is-inside-work-tree
    if ($LASTEXITCODE -ne 0) { throw 'Esta carpeta no es un repositorio Git. Usa el ZIP.' }
    $State = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $State.Count -gt 0) { throw 'Se necesita un repositorio limpio.' }
    & git apply --check --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) { throw 'El parche no coincide. Usa el ZIP 0.6.0.' }
    & git switch -c ('mejora/recursos-0.6.0-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la rama.' }
    & git -c core.whitespace=cr-at-eol am --keep-cr --ignore-space-change $Patch
    if ($LASTEXITCODE -ne 0) { throw 'Revisa git status; git am --abort revierte este intento.' }
}
```
