# Auditoría del lote de iconos de variantes

El ZIP `iconos-variantes-20261023-221844-35c28d.zip` superó la auditoría de datos:
1.108.835 comprobaciones, cero errores. Su SHA-256 es
`f2f109eecefc05dcf2a7ac2720292ace31bf853869264a0f62889feed2764b99`.
El informe estructurado está en `AUDITORIA_LOTE_ICONOS_VARIANTES_0.6.4.json`.

## Resultado validado

| Concepto | Resultado |
| --- | ---: |
| Variantes | 43: ocho FE7 y 35 FE8 |
| Apariciones | 9.224 |
| PNG almacenados entre carpetas de variantes | 9.224 |
| Imágenes distintas entre variantes | 400 |
| Imágenes distintas FE7 / FE8 | 179 / 258 |
| Imágenes compartidas entre juegos | 37 |
| Recursos raw distintos | 400 |
| Paletas RGB555 distintas | 1 |
| Apariciones totalmente transparentes | 0 |
| Archivos del ZIP | 18.839 |
| Filas de inventario AIR contrastadas | 479.144 |

Se comprobaron CRC, rutas del ZIP, manifiestos completos y hashes exactos de
todos los archivos, ambas copias de las 43 definiciones, los rangos e IDs,
offsets, tamaños, identidades, conteos y procedencias. Los bancos raw reconstruidos
coinciden byte por byte con la evidencia previamente aprobada. La referencia al
informe de revisión coincide con su SHA-256, no solo con el hash declarado.

Los 400 PNG distintos se decodificaron y verificaron como RGBA de 16×16.
Cada una de las 9.224 apariciones coincide con la reconstrucción independiente
desde su raw 4bpp y paleta RGB555. Las filas de CSV locales y globales coinciden
con los catálogos JSON; no faltan IDs ni procedencias. Las filas AIR se contrastaron
por offset, compresión, tamaño decodificado, hash y número de referencias contra
la comparación anterior de las variantes. Permanecen sin reclasificar.

La extracción usa FE7 IDs 0–172 y FE8 IDs 0–223, ambos inclusive, y la primera
paleta documentada. No demuestra el tamaño total de las tablas. No se recibieron
ROM ni AIR completos para recalcular aquí sus hashes; sus identidades registradas
coinciden con el plan y la revisión. Los .bin externos de AIR no se recibieron ni
se revalidaron. La presentación en navegador real sigue pendiente.

## Corrección de navegación

Los archivos del ZIP ya tienen rutas portables y las 43 galerías individuales
referencian correctamente sus recursos. Sin embargo, `galerias.csv` contiene
rutas absolutas `C:\FireEmblem\...` y falta un índice HTML en la raíz. Esas rutas
describen la ubicación original; no permiten navegar por una copia trasladada.

El parche añade `index.html` con enlaces relativos a las galerías y cambia la
columna `gallery` del CSV a rutas como `fe7-001/index.html`. Conserva la ruta de
procedencia en `gallery_original` y en el resumen original. Las futuras extracciones
generan este índice automáticamente.

El comando `index` prepara una carpeta nueva desde el lote terminado. Comprueba
su manifiesto y conserva exactamente los bytes de los recursos, catálogos y
procedencias. Solo añade el índice, regenera el CSV de galerías y su manifiesto.
No abre ROM, AIR ni vuelve a extraer o codificar imágenes. El lote original y su
ZIP se conservan.

Después de aplicar `arcanacart-0.6.4-indice-iconos-portable.patch`:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Entrada = 'C:\FireEmblem\resultados\iconos-variantes-20261023-221844-35c28d'
    $Salida = $Entrada + '-indice-portable'

    & $Python -m arcanacart.icon_variants index `
        --input $Entrada --out $Salida --zip ($Salida + '.zip')
    if ($LASTEXITCODE -ne 0) {
        throw 'No se pudo preparar el índice portable. Copia la salida completa.'
    }

    Start-Process -FilePath (Join-Path $Salida 'index.html')
}
```

Si falla únicamente el ZIP después de completarse la copia, empaqueta esa
carpeta mediante `python -m arcanacart.icon_variants pack --input CARPETA --out
ZIP_NUEVO`. No repitas la extracción. Se rechazan salidas existentes o ubicadas
dentro del lote original.

## Comprobación del cambio

Se ejecutaron 86 pruebas de iconos: las 76 anteriores y diez de navegación.
Comprueban la conservación de recursos y del original, las referencias tras
trasladar un ZIP, el escape de nombres y el rechazo de entradas incompletas,
alteradas o incoherentes. No hay PowerShell instalado para ejecutar el lanzador
en este entorno; se probaron las funciones Python y su CLI.

La copia del lote real generó 18.840 archivos: 18.837 archivos originales
conservados byte por byte, el CSV de galerías y manifiesto actualizados, y un
índice nuevo. Se comprobaron los 46 enlaces relativos del HTML y las 43 filas
del CSV, conservando las rutas originales como procedencia.

La deduplicación de archivos entre variantes sigue siendo un paso independiente:
hay 8.824 copias PNG adicionales respecto de las 400 imágenes distintas. La
corrección del índice conserva esas carpetas y sus procedencias. Se mantiene 0.6.4.
