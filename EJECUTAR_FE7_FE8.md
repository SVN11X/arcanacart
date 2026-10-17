# FE7, FE8 y sus mods — nombres y ejecución

ArcanaCart 0.4.0 organiza tus archivos, prepara las ROMs modificadas y genera
informes locales para ambos juegos. Requiere **Python 3.10 o posterior**.
Descomprime el ZIP del código en una carpeta sencilla, por ejemplo
`C:\ArcanaCart`, y abre PowerShell dentro de la carpeta que contiene `README.md`.

## 1. Los cuatro archivos de entrada

Usa los ZIP originales. Los TXT de code2text son inventarios: los binarios UPS
omitidos en ellos no se pueden reconstruir a partir del texto.
El importador conserva tus archivos y crea estas copias con nombres formales:

| Archivo que eliges | Nombre formal | Carpeta de destino |
|---|---|---|
| ROM Fire Emblem FE7 USA, ZIP | `fe7-usa-base.zip` | `private/inputs/roms/` |
| ROM Fire Emblem: The Sacred Stones FE8 USA, ZIP | `fe8-usa-base.zip` | `private/inputs/roms/` |
| ZIP completo FE7 Remastered con sus UPS | `fe7-remastered-patches.zip` | `private/inputs/mods/` |
| ZIP completo Sacred Trilogy con sus UPS | `fe8-sacred-trilogy-patches.zip` | `private/inputs/mods/` |

No cambies las extensiones. No hace falta renombrar nada dentro de los ZIP ni
extraerlos antes. Sacred Trilogy puede incluir `Legacy Versions Sacred Trilogy/`;
el catálogo contempla subcarpetas y paquetes de hasta 2 GiB.

## 2. Elegir los archivos en Windows

Desde la carpeta del proyecto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Prepare-Inputs.ps1 -PickFiles
```

Se abrirán cuatro selectores, en este orden: FE7 base, FE8 base, FE7 Remastered,
Sacred Trilogy. El programa comprueba las entradas y crea los nombres y carpetas.
Si cancelas la selección, todavía no se habrá copiado ningún archivo.
`ExecutionPolicy Bypass` solo se aplica al proceso que estás iniciando.

Si prefieres indicar rutas, puedes usar:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Prepare-Inputs.ps1 -Fe7Rom "C:\Mis archivos\FE7.zip" -Fe8Rom "C:\Mis archivos\FE8.zip" -Fe7Mods "C:\Mis archivos\FE7Remastered.zip" -Fe8Mods "C:\Mis archivos\Sacred Trilogy.zip"
```

Sustituye esos cuatro ejemplos por tus rutas reales. Los espacios y `[!]` se
admiten. También puedes copiar manualmente los ZIP a los destinos de la tabla,
usando exactamente sus nombres formales, y continuar con el siguiente paso.

## 3. Ejecutar los dos juegos y los dos mods

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Run-ArcanaCart.ps1 -OpenReport
```

La selección inicial produce cuatro trabajos:

| Trabajo | Entrada aplicada |
|---|---|
| FE7 USA base | Base FE7 sin modificar |
| FE7 Remastered | `FE7URemaster X QoL Final - Paladin Special.PATCH.20251026165125.ups` |
| FE8 USA base | Base FE8 sin modificar |
| Sacred Trilogy | `Sacred Trilogy 2.1.3 Full Version.ups` |

Son las variantes de las capturas usadas para preparar la configuración. Si
tu paquete no las contiene, genera el catálogo y elige otra en el paso 5.
Cada UPS se aplica directamente a su base limpia; las variantes no se encadenan.
La compatibilidad se decide con tamaños y CRC, además del SHA-1 de la base.

Para todas las versiones de ambos paquetes, incluidas Full, Lite y legacy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Run-ArcanaCart.ps1 -AllVariants -OpenReport
```

Puede ocupar bastante más espacio y tiempo: se crea una ROM y un análisis por
variante. Un UPS que requiera otra base queda registrado como fallido; continúan
los trabajos restantes. Para solo un juego añade `-Game fe7` o `-Game fe8`.
Para omitir el escaneo de recursos comprimidos, añade `-NoScan`.

Los lanzadores ya incluyen reanudación. Repite el comando para reutilizar archivos
verificados; si cambias las opciones de análisis se genera otra carpeta.

## 4. Dónde queda cada resultado

| Ruta desde la raíz del proyecto | Contenido |
|---|---|
| `private/inputs/` | Cuatro copias con nombres formales y registro de importación |
| `private/fire-emblem.json` | Configuración editable de entradas y variantes |
| `private/prepared/fire-emblem/fe7/` | Base FE7, UPS seleccionados y ROMs modificadas |
| `private/prepared/fire-emblem/fe8/` | Base FE8, UPS seleccionados y ROMs modificadas |
| `workspace/fire-emblem/index.html` | Índice común: abre este archivo en el navegador |
| `workspace/fire-emblem/catalog.json` | Nombres originales e IDs de todos los UPS |
| `workspace/fire-emblem/batch-report.json` | Estado, errores y rutas exactas de cada trabajo |
| `workspace/fire-emblem/fe7/` y `fe8/` | Informes HTML/Markdown, AIR JSON, CSV y comparaciones |

Los nombres internos usan minúsculas y guiones, conservan versión/fecha cuando
están presentes y añaden una huella corta al parche y ROM preparados. Ejemplos:

- `fe7-usa-remastered-x-qol-final-paladin-special-20251026t165125--<hash12>.gba`
- `fe8-usa-sacred-trilogy-2.1.3-full--<hash12>.gba`

`<hash12>` representa doce caracteres calculados por el programa; no lo escribas
literalmente. Las ROMs modificadas están dentro de la subcarpeta `roms/` de cada
juego; el campo `prepared` del registro JSON da la ruta exacta.
Para **jugar**, abre esa `.gba` en tu emulador de GBA habitual. ArcanaCart prepara
y analiza los archivos; no incluye ni inicia un emulador.

## 5. Elegir otra versión del mod

Genera el catálogo sin aplicar parches:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Run-ArcanaCart.ps1 -CatalogOnly -OpenReport
```

Abre `workspace/fire-emblem/catalog.json`, busca el miembro original que deseas y
copia su `id`. Edita `selection` en `private/fire-emblem.json`, sin cambiar el
resto de campos. Para la selección inicial tiene esta forma:

```json
"selection": {
  "fe7": ["fe7-usa-remastered-x-qol-final-paladin-special-20251026t165125"],
  "fe8": ["fe8-usa-sacred-trilogy-2.1.3-full"]
}
```

Puedes poner varios IDs separados por comas, o `[]` para analizar solo la base de
ese juego. Repite el comando normal del paso 3. `-AllVariants` ignora esta selección.

## 6. Ejecutar directamente con Python

Sin lanzadores, desde la carpeta del código y después de copiar las entradas:

```powershell
py -3 -m arcanacart batch --init
py -3 -m arcanacart batch --resume --verbose
py -3 -m arcanacart batch --resume --all-variants --verbose
```

La tercera línea es alternativa a la segunda para procesar todas las variantes.
En Linux/WSL sustituye `py -3` por `python3`. No hay dependencias de ejecución,
descargas durante el análisis ni instalación obligatoria con pip.
Para validar sin generar resultados, usa `batch --dry-run` después de importar.
La plantilla completa está en `examples/fire-emblem-batch.json`.

## Errores y alcance

| Mensaje o resultado | Acción |
|---|---|
| Python no encontrado | Instala Python 3.10+ o indica `-PythonExe "C:\ruta\python.exe"` al lanzador |
| SHA-1 no coincide | Revisa que elegiste la base USA limpia del juego correcto |
| El ZIP no contiene UPS | Selecciona el paquete original de parches, no su TXT convertido |
| Variante no encontrada | Usa el catálogo y copia un ID existente en `selection` |
| El UPS requiere otra base | Consulta las instrucciones de esa versión; el CRC indica incompatibilidad |
| Ya existe con otro contenido | Conserva esa copia y usa otra carpeta de proyecto para las nuevas entradas |
| `partial` / código 3 | Consulta los errores de `batch-report.json`; los otros resultados siguen disponibles |
| Escaneo `truncated` | Se alcanzó una cuota; el informe detalla límites y métricas, no cobertura total |

El flujo identifica, aplica UPS, busca recursos LZ10/RLE y genera informes y
comparaciones binarias. Para extraer personajes, clases u objetos necesitas
definiciones de tablas investigadas para el SHA-256 de **cada** variante. En
`tables`, la clave es el ID del trabajo (`fe7-base`, `fe8-base` o ID de mod) y el
valor la ruta de su definición dentro de `private/`. Consulta `EXTRACTION_FORMATS.md`.
Sin ellas se registra la omisión. Ghidra y la extracción completa de campañas no
forman parte de este lote.

Verificación de esta entrega: 153 pruebas automatizadas correctas en Linux;
bases reales FE7U/FE8U preparadas y analizadas con UPS sintéticos. Los ZIP reales
de los mods solo se mostraron en capturas y no se probaron aquí. Los lanzadores
PowerShell se revisaron, pero no se ejecutaron en Windows en este entorno.
