# Sprites de mapa en reposo: extracción revisada

La extracción utiliza el paquete
`revision-sprites-mapa-ampliada-20261024-141014-87975f.zip`, ya auditado. Su informe
pasó 43.268 comprobaciones independientes y conserva íntegramente la revisión
inicial. El código de carga de paletas coincide, byte a byte, con el de la base
correspondiente en las 45 identidades.

Las definiciones incorporadas están en `arcanacart/map_sprite_definitions.json`.
Vinculan el informe y su manifiesto a cada ROM, tabla, rango y cargador de
paletas. Su identidad canónica admite LF/CRLF en este archivo de definiciones;
los hashes de ROM, AIR, LZ10, 4bpp, paletas y PNG corresponden a bytes exactos.

La versión permanece **0.6.4**. No se necesitan dependencias de imagen, ROM ni
AIR para esta extracción: todas las hojas comprimidas y paletas necesarias ya
están en el paquete revisado. El programa no ejecuta un escáner.

## Rangos y resultado verificados

| Grupo | ROM | IDs incluidos por ROM |
| --- | ---: | --- |
| Base FE7 y variantes FE7 | 9 | 0–87 |
| Base FE8 | 1 | 0–106 |
| Variantes FE8 con 255 hojas | 23 | 0–254 |
| Variantes FE8 con 254 hojas | 12 | 0–253 |

Las 12 variantes del último grupo son FE8 022, 024 y 026–035. Cada definición
guarda explícitamente su rango y su hash; los registros nulos o no válidos
posteriores quedan fuera de la exportación. Estos rangos no demuestran la
capacidad reservada ni la totalidad de recursos del juego.

El resultado de referencia contiene:

- **9.812 apariciones**: 792 de FE7 y 9.020 de FE8. Incluye dos bases y 43
  variantes; 9.617 apariciones pertenecen a las variantes.
- **346 flujos LZ10 originales y 254 hojas 4bpp distintas**, conservados por hash.
- **Siete paletas RGB555** del cargador revisado. Los cuatro primeros bancos
  corresponden a jugador, enemigo, aliado y gris. Los otros tres bloques tienen
  rutas de carga condicionales o separadas; se conservan como cuarto grupo,
  runa de luz y sepia.
- **6.923 PNG distintos**: 1.767 hojas completas y 5.156 fotogramas. Cada hoja
  conserva sus tres fotogramas con cada paleta, aunque algunos PNG sean
  compartidos por varias relaciones.
- Una de las 254 hojas es totalmente transparente y conserva sus 54
  apariciones. La galería la oculta inicialmente y ofrece mostrarla.

Los tamaños por fotograma son 16×16, 16×32 y 32×32. El archivo PNG conserva su
tamaño; la galería amplía su presentación tres veces con píxeles visibles.

## Continuar en main

La rama principal remota es `main`. Ya contiene el desarrollo anterior por el
merge de la PR número 1; la rama de trabajo añade la ampliación de evidencia.
La incorporación de esa rama a `main` se probó sin conflictos en una copia
aislada del historial publicado. Se conserva el historial con un merge normal.

Antes de aplicar el nuevo parche, ejecuta:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Estado = @(& git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Git no pudo consultar el repositorio.' }
    if ($Estado.Count -gt 0) { throw 'Conserva los cambios locales antes de continuar.' }

    & git fetch origin
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar la información del remoto.' }

    & git show-ref --verify --quiet refs/heads/main
    $ExisteMain = $LASTEXITCODE
    if ($ExisteMain -eq 0) {
        & git switch main
    } elseif ($ExisteMain -eq 1) {
        & git switch --create main --track origin/main
    } else {
        throw 'No se pudo consultar la rama main.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo cambiar a main.' }

    & git merge --ff-only origin/main
    if ($LASTEXITCODE -ne 0) { throw 'La sincronización de main se detuvo. Copia la salida.' }

    & git merge --no-edit 'mejora/arcanacart-0.6.1-20261022-230319'
    if ($LASTEXITCODE -ne 0) { throw 'La integración se detuvo. Copia la salida completa.' }

    & git status
}
```

Aplica el parche mediante `git am` con `main` activa. Publica el resultado con
`git push --set-upstream origin main` después de comprobar su aplicación.

## Reproducir el catálogo en PowerShell

Si se utiliza el catálogo ZIP ya generado y validado, basta descomprimirlo y
abrir `index.html`. El siguiente bloque reproduce la extracción desde la
evidencia para obtener otro resultado local independiente:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
    $Revision = 'C:\FireEmblem\resultados\revision-sprites-mapa-ampliada-20261024-141014-87975f.zip'
    $Nombre = 'catalogo-sprites-mapa-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
        [guid]::NewGuid().ToString('N').Substring(0, 6)
    $Salida = Join-Path 'C:\FireEmblem\resultados' $Nombre

    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "No se encuentra Python: $Python" }
    if (-not (Test-Path -LiteralPath $Revision -PathType Leaf)) { throw "No se encuentra la revisión: $Revision" }

    & $Python -m arcanacart.map_sprite_catalog extract `
        --review $Revision --out $Salida --zip ($Salida + '.zip')
    if ($LASTEXITCODE -ne 0) { throw 'La extracción se detuvo. Copia la salida completa.' }

    Invoke-Item -LiteralPath (Join-Path $Salida 'index.html')
    Write-Host "ZIP: $($Salida + '.zip')"
}
```

Para volver a empaquetar un catálogo terminado, usa el subcomando `pack --input
CARPETA --out NUEVO_ZIP`. Verifica el manifiesto y CRC sin abrir la evidencia de
entrada ni volver a dibujar imágenes.

## Archivos y procedencias

`catalogo.json` contiene perfiles de ROM, apariciones por ID, conjuntos de
renderizado y activos PNG. Cada aparición enlaza su definición, ROM/AIR, registro
de tabla, offset, LZ10 y raw 4bpp. El conjunto de renderizado conserva las siete
paletas y el orden de sus tres fotogramas; un PNG compartido mantiene todas esas
relaciones.

Los CSV ofrecen una fila por aparición y por PNG distinto. `definiciones/`
conserva las 45 definiciones utilizadas; `evidencias/` conserva las tablas y los
cargadores de paleta. `fuentes/` conserva el informe, manifiesto y registro de
definiciones que respaldan la extracción. Los hashes de cada salida están en
`map-sprite-catalog-state.json`.

La galería funciona desde archivos locales y permite filtrar por juego, ROM,
tamaño, ID o hash y cambiar de paleta. Sus filtros se correlacionan sobre la
misma aparición. Las procedencias se muestran de cien en cien para conservar el
acceso a todas sin crear una página inicial enorme.

## Validación y pendientes

Se compararon todas las hojas y fotogramas con un decodificador y renderizador
independientes, además de comprobar PNG, CSV, manifiestos y referencias. El
registro está en `docs/VALIDACION_SPRITES_MAPA_0.6.4.json` y la auditoría del
paquete ampliado en `docs/AUDITORIA_SPRITES_MAPA_AMPLIADA_0.6.4.json`.

Se probaron el DOM de la galería, sus filtros, paletas, paginación y acceso a
todas las procedencias. Sigue pendiente comprobar su presentación en un
navegador real y contrastar una muestra con el juego. Se exportan fotogramas
completos; no se infieren recortes del editor, tiempos de animación ni uso de
cada sprite en una partida. Los sprites de movimiento y otros bancos siguen
fuera de este alcance.

La misma entrega corrige los avisos anteriores de Ruff y las anotaciones de
tipos de iconos/revisión que impedían superar CI, y ajusta con Ruff el formato de esos
archivos de código. La identidad de ROM, AIR y recursos continúa usando sus
bytes exactos.
