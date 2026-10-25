# Catálogo de hojas y datos AP de movimiento

Esta entrega usa el paquete local ya auditado
`revision-sprites-movimiento-20261024-210125-a427ae.zip`. La auditoría pasó
44.027 comprobaciones sin errores: CRC, manifiesto, hashes, tablas, CSV,
descompresión independiente y datos AP. La versión se mantiene en **0.6.4** y
los cambios se aplican en **main**, después de la revisión de movimiento.

El catálogo conserva las hojas LZ10 originales, su contenido 4bpp y los datos
AP. Reutiliza las siete paletas del catálogo terminado de reposo para generar
vistas de las hojas completas de tiles. La composición de los fotogramas AP,
la selección real de bancos de paleta y la reproducción de animaciones siguen
pendientes de validar.

## Rangos incluidos

| Grupo | Identidades | IDs nativos propuestos por tabla |
| --- | ---: | --- |
| Base FE7 y ocho variantes FE7 | 9 | 1-99 |
| Base FE8 | 1 | 1-127 |
| Variantes FE8 002-009 | 8 | 1-255 |
| FE8 001 y FE8 010-035 | 27 | 1-254 |

Son prefijos explícitos, vinculados por hash a cada ROM/AIR y ventana de tabla.
Los contextos de acceso coinciden con sus bases al excluir todos los literales
documentados de tabla relocalizados. Esto respalda la asociación con el layout
nativo; no prueba que todas las clases se utilicen en una partida ni la
capacidad total reservada de cada tabla.

Las dos ventanas AP que no interpretaba el lector aparecen en las posiciones
198 y 199 de FE7, después del prefijo incluido. Se conservan en el ZIP original
como evidencia y quedan fuera de esta exportación. No se amplían rangos para
convertir esos datos posteriores en recursos aprobados.

## Resultado de referencia

- **45 identidades**: dos bases y 43 variantes.
- **9.916 apariciones**: 891 de FE7 y 9.025 de FE8; 9.690 pertenecen a variantes.
- **351 flujos LZ10 distintos**, **256 hojas 4bpp distintas** y **27 datos AP**.
- **259 combinaciones de hoja y AP**. Una misma hoja puede estar asociada a
  distintos datos AP; esas relaciones se conservan por separado.
- **1.785 PNG distintos** de hojas completas con siete paletas de referencia.
  No se modifican los píxeles para mejorar su calidad ni se generan fotogramas
  compuestos a partir de OAM en esta fase.
- Una hoja totalmente transparente con **45 apariciones**. La galería la
  oculta inicialmente: muestra 258 recursos y 9.871 apariciones. Al activar
  «Mostrar transparentes» se muestran los 259 recursos y 9.916 apariciones.

El raw conserva todos sus bytes, incluidos los tiles adicionales de algunas
hojas. Las vistas usan cuatro columnas de tiles de 8x8. Una última fila
incompleta se rellena con transparencia; cada vista registra `tile_count` y
`padding_tiles`. Ese relleno no se añade al archivo 4bpp. Los PNG mantienen sus
dimensiones y la galería amplía solo su presentación.

## Usar el catálogo preparado

El ZIP descargable `arcanacart-0.6.4-catalogo-recursos-movimiento.zip` ya incluye
las imágenes y archivos de datos auditados. Descomprímelo en una carpeta nueva
y abre `index.html`. El código del repositorio se entrega por separado como
`arcanacart-0.6.4-catalogo-movimiento-main.patch`, compatible con `git am`.

La galería permite filtrar por juego, ROM, ID o hash, cambiar la paleta de
referencia y consultar todas las procedencias. Las fichas enlazan raw, LZ10,
AP binario, descripción AP, definición y paleta. Una vista parcial de la hoja
se puede desplazar dentro de su panel o descargar como PNG completo.

## Reproducir desde los paquetes existentes

El siguiente bloque es opcional si se utiliza el ZIP ya preparado. Genera una
carpeta nueva desde la revisión de movimiento y el catálogo local de reposo;
no abre ROM ni AIR y no repite los escaneos o las extracciones anteriores.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Revision = 'C:\FireEmblem\resultados\revision-sprites-movimiento-20261024-210125-a427ae.zip'
    $Paletas = 'C:\FireEmblem\resultados\catalogo-sprites-mapa-20261024-192200-971d70'
    $Nombre = 'catalogo-recursos-movimiento-' + (Get-Date -Format 'yyyyMMdd-HHmmss') +
        '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    $Salida = Join-Path 'C:\FireEmblem\resultados' $Nombre

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "No se encuentra Python: $Python" }
    if (-not (Test-Path -LiteralPath $Revision -PathType Leaf)) { throw "No se encuentra la revisión: $Revision" }
    if (-not (Test-Path -LiteralPath $Paletas -PathType Container)) { throw "No se encuentra el catálogo de reposo: $Paletas" }

    & $Python -m arcanacart.moving_sprite_catalog extract `
        --review $Revision --palettes $Paletas --out $Salida --zip ($Salida + '.zip')
    if ($LASTEXITCODE -ne 0) { throw 'La exportación se detuvo. Copia la salida completa.' }

    Invoke-Item -LiteralPath (Join-Path $Salida 'index.html')
    Write-Host "ZIP: $($Salida + '.zip')"
}
```

Ambas entradas pueden ser carpetas verificadas, ZIP con los archivos en la
raíz o ZIP con una sola carpeta contenedora. Los hashes de informe y manifiesto
deben coincidir con las fuentes auditadas; cambiar la compresión o envolver
los archivos en una carpeta no altera sus identidades internas. Los datos
adicionales, ausentes o modificados se rechazan.

Para volver a empaquetar una salida terminada:

```powershell
& 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    -m arcanacart.moving_sprite_catalog pack `
    --input 'C:\FireEmblem\resultados\CARPETA_DEL_CATALOGO' `
    --out 'C:\FireEmblem\resultados\NUEVO_ARCHIVO.zip'
```

## Archivos y controles

`catalogo.json` conserva perfiles, combinaciones de hoja/AP, vistas e imágenes y
todas las apariciones por identidad e ID. `ocurrencias.csv`, `recursos.csv` e
`imagenes.csv` permiten trabajar con esos niveles por separado. Los orígenes
incluyen hashes ROM/AIR, índice, registro, offsets de hoja y AP, longitudes y
hashes de los datos originales.

`definiciones/` y `evidencias/` conservan los rangos y accesos utilizados;
`fuentes/` guarda los informes y manifiestos de entrada. Los recursos están en
`raw/`, `comprimidos/`, `ap/`, `paletas/` e `imagenes/`.
`moving-resource-catalog-state.json` contiene los hashes de toda la salida.

Se verifican las fuentes completas y sus manifiestos antes de exportar. Las
hojas se descomprimen una vez por flujo distinto y se cotejan con los hashes
AIR registrados. Los AP se vuelven a interpretar estructuralmente y sus bytes
permanecen intactos. Las paletas se copian del catálogo de reposo, con sus
identidades y offsets de procedencia; su asociación con movimiento se marca
expresamente como no verificada en el juego.

Los hashes de ROM, AIR y recursos se basan en bytes exactos. Solo se utiliza
JSON canónico para identificar las definiciones del repositorio con LF/CRLF.
Se conservan entradas y resultados anteriores, y se requieren salidas nuevas.

Los registros de auditoría y desarrollo están en
`docs/AUDITORIA_REVISION_MOVIMIENTO_0.6.4.json` y
`docs/VALIDACION_CATALOGO_MOVIMIENTO_0.6.4.json`. Se comprobaron los píxeles PNG
con un renderizador independiente y el DOM con los datos completos. La
presentación de esta nueva galería en un navegador real queda pendiente.

El siguiente trabajo será reconstruir fotogramas desde los objetos AP y
contrastar bancos de paleta y comportamiento temporal con el motor. Las
posiciones fuera de estos rangos y otros bancos siguen fuera del alcance.
