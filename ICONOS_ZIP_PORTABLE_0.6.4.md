# ZIP portable y revisión de los iconos de las bases

Este parche mantiene ArcanaCart en **0.6.4**. Corrige el empaquetado del
lanzador y añade `python -m arcanacart.icon_package` para empaquetar resultados
existentes sin volver a leer ROM, extraer iconos ni modificar las entradas.

## Revisión del lote real

Se examinó `iconos-ambos-20261023-161457-6f7353.zip`, de 471.398 bytes.
SHA-256: `acd88505bf1ef97ec6533a20dc2f7a5a9dd1d12f4b4c95489883092c6711bb27`.

| Juego | IDs | PNG únicos dentro del juego | Raw únicos | Totalmente transparentes |
| --- | ---: | ---: | ---: | ---: |
| FE7 | 173 | 171 | 171 | 0 |
| FE8 | 224 | 212 | 212 | 0 |

Se conservan los 397 IDs. Hay 383 archivos PNG, que corresponden a **213
contenidos PNG distintos entre ambos juegos**; 170 se comparten. La paleta es
idéntica en ambos juegos y se conserva una copia en cada carpeta. La
deduplicación de cada catálogo evita 14 copias dentro de sus respectivos
juegos. Este parche conserva esa organización y todas las procedencias.

Comprobaciones realizadas:

- CRC de los 782 archivos interiores y hashes de todos los artefactos de los
  dos manifiestos.
- PNG RGBA 16 × 16; raw 4bpp de 128 bytes y paleta RGB555 de 32 bytes.
- Reconstrucción independiente de los píxeles de los 397 IDs a partir de los
  raw y paletas del ZIP, sin importar el renderizador de ArcanaCart. Todos
  coinciden con sus PNG.
- CSV frente a JSON, rangos completos, offsets, IDs, conteos y procedencias.
- Definiciones frente a sus hashes canónicos, coherencia de resúmenes y
  datos embebidos/CSP/enlaces de las galerías.
- Inspección de una lámina con todos los IDs de cada juego. Las imágenes con
  una X roja coinciden también con los raw incluidos; no son un fallo de
  decodificación del PNG.

No se recibieron ROM completas. Aquí no se recalcularon sus hashes ni se
releyeron los punteros: se cotejaron los registros de la ejecución local.
La presentación HTML en un navegador real y las variantes siguen fuera de
esta revisión. No se certifica extracción total del juego.

La evidencia estructurada se incluye en `docs/AUDITORIA_ICONOS_BASE_0.6.4.json`.

## Defecto del ZIP y corrección

780 nombres de archivo del ZIP original usan `\` como separador interno.
En una extracción con Python sobre POSIX, `fe7\index.html` se conserva como
un nombre literal y no produce `fe7/index.html`. Esto impide que las rutas
relativas de la galería funcionen en ese caso.

Se sustituye `Compress-Archive` por un empaquetador Python que:

1. Lee una instantánea del lote terminado, con límites de archivos y bytes.
2. Comprueba los resúmenes, estados y SHA-256 de los artefactos.
3. Escribe nombres relativos con `/`, conservando el contenido byte por byte.
4. Verifica los CRC antes de publicar el ZIP mediante escritura atómica.

Rechaza salidas existentes, archivos modificados, entradas incompletas,
artefactos no registrados, enlaces simbólicos y ZIP dentro de la entrada.
No interpreta ni normaliza el contenido de los archivos, ni sus LF/CRLF.

## Reempaquetar este lote sin repetir su extracción

Después de aplicar el parche:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Entrada = 'C:\FireEmblem\resultados\iconos-ambos-20261023-161457-6f7353'
    $Salida = $Entrada + '-portable.zip'

    & $Python -m arcanacart.icon_package --input $Entrada --out $Salida
    if ($LASTEXITCODE -ne 0) {
        throw 'No se pudo crear el ZIP portable. Conserva la carpeta de entrada y copia la salida.'
    }
    Write-Host "ZIP portable: $Salida"
}
```

El ZIP antiguo y la carpeta extraída permanecen intactos. Los 782 contenidos
del ZIP nuevo coinciden con los del original; cambian los nombres internos y
el empaquetado. Por ello, el SHA-256 del ZIP completo cambia y no se debe
confundir con los hashes de sus archivos interiores.

Las futuras ejecuciones de `Extraer-Iconos.ps1 -CrearZip` utilizan el nuevo
empaquetador automáticamente.

## Validación del cambio

- 14 pruebas nuevas: rutas portables y extracción POSIX, bytes conservados,
  CRC, entradas inmutables, conteos y manifiestos, modificaciones de raw,
  archivos faltantes/adicionales, salidas existentes, enlaces y CLI.
- Reempaquetado del lote real de 782 archivos: contenido idéntico en todos
  los casos, rutas sin `\`, CRC válidos y `fe7/index.html` extraíble como ruta.
- Aplicación del parche con `git am` sobre el estado 0.6.4 generado en esta
  conversación, con `core.autocrlf=false` y `true`.

El ejecutable PowerShell no está disponible en este entorno. El empaquetador
Python sí se ejecutó con los datos reales del ZIP proporcionado.
