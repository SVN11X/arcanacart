# Referencia de CLI

Todos los resultados de datos se imprimen como JSON en stdout. `--json` hace
explícito ese contrato. Los errores JSON van a stderr. `--verbose` agrega diagnóstico
en stderr. `--help` está disponible en cada comando; `--version` en la raíz.
Los comandos terminan antes de informar éxito. Un dry-run informa `planned`.

| Código | Significado |
|---|---|
| 0 | Operación completada, diagnóstico disponible o plan sin escritura |
| 2 | Entrada, argumentos, escritura o ejecución externa inválidos/incompletos |
| 3 | Pipeline parcial o lote con trabajos fallidos/bloqueados |
| 4 | Ghidra opcional ausente o instalación no verificable por el wrapper |
| 130 | Interrupción de teclado |

Desde 0.4.1, `scan`, `extract --scan` y `pipeline` devuelven `partial` y código 3
si se interrumpe el escaneo por una cuota. `completed` puede tener etapas no
solicitadas como `skipped`; nunca significa extracción completa de una campaña.

## Comandos

El lote de retratos de las 43 variantes se ejecuta con
`scripts/windows/Extraer-Retratos-Variantes.ps1` o con
`python scripts/variantes/extraer_retratos_variantes.py --repo . --resume-latest`.
Este programa imprime progreso legible y escribe el resultado estructurado en
`resumen.json`; su contrato de salida es independiente de la CLI JSON principal.
Devuelve 0 al completar los rangos, 2 si requieren revisión y 130 ante `Ctrl+C`.
Consulta [RETRATOS_VARIANTES_0.6.2.md](RETRATOS_VARIANTES_0.6.2.md).

| Comando | Entrada y resultado |
|---|---|
| `doctor` | Diagnóstico básico y disponibilidad opcional de Java/Ghidra/layout ARMv4T |
| `inspect FILE [--member NAME]` | .gba, .zip o UPS1; huellas/cabecera o metadatos del parche |
| `prepare --rom FILE --out FILE` | Copia validada y manifiesto; admite ZIP; exige hash conocido por defecto |
| `patch --rom BASE --patch UPS --out RESULT` | UPS1 con dirección auto/forward/reverse y CRC completo |
| `scan --rom FILE --out DIRECTORY` | Manifiesto de recursos y blobs únicos por SHA-256 |
| `extract --rom FILE --out AIR.json` | AIR, tablas si hay definición, escaneo optativo `--scan` |
| `pipeline --rom FILE --out DIRECTORY` | AIR, CSV, informes, recursos y estado reanudable |
| `symbols --reference DIR --file MAP --out symbols.json` | Símbolos de referencia local, commit y hash del mapa |
| `compare --left FILE --right FILE --out diff.json` | Cambios binarios; con `--air`, comparación de campos AIR |
| `compare-resources --left BASE.json --right MOD.json --out DIRECTORY` | Hashes de candidatos descomprimidos; resumen JSON y catálogo CSV |
| `interpret --input AIR.json --out DIRECTORY` | Reutiliza bloques, verifica hashes y genera galería, PNG, catálogo y recetas |
| `layouts` | Enumera layouts incorporados, tamaños, campos y fuentes |
| `tables-define --rom ROM --table Tipo:OFFSET:CONTEO:PRIMER_ID --evidence TEXTO --out FILE` | Define rangos ligados a la ROM; símbolos/layouts opcionales |
| `code-index --input AIR.json --out DIRECTORY` | Documenta rangos; con `--ghidra-summary` verifica e incorpora exports reales |
| `export --input AIR.json --format json/csv --out FILE` | Valida AIR y exporta |
| `export --format schema --out air.schema.json` | Copia del esquema distribuido |
| `report --input AIR.json --format markdown/html --out FILE` | Informe local verificable |
| `disasm --rom FILE.gba --out DIRECTORY` | Wrapper Ghidra experimental; requiere instalación externa |
| `batch-import --fe7-rom ZIP --fe8-rom ZIP --fe7-mods ZIP --fe8-mods ZIP` | Valida entradas y crea copias con nombres formales; admite subconjuntos |
| `batch --init` | Crea estructura y configuración privada sin analizar |
| `batch --resume` | Procesa ambas bases y las variantes elegidas; crea índice común |

### Opciones compartidas

- `--member`: nombre exacto dentro del ZIP cuando hay varias ROMs.
- `--profile auto/generic-gba/fe7-us/fe8-us`: en extract/pipeline. Auto usa SHA-1 exacto,
  no Game Code. `--tables FILE.json` liga ubicación/conteo al SHA-256 de esa variante.
- `--force`: prepare, patch, extract, symbols, compare, export, report y dump;
  permite sustituir salidas regulares, nunca entradas ni enlaces a ellas.
- `--dry-run`: todas las operaciones que producen resultados; lee y valida entradas
  y puede realizar el cálculo para verificarlo, pero no escribe resultados.
- `--resume`: pipeline, batch y disasm. No es un permiso para cambiar entradas en el mismo
  workspace. El pipeline comprueba configuración y hashes; Ghidra usa el proyecto existente.

### Lote FE7/FE8

```powershell
py -3 -m arcanacart batch-import --fe7-rom "C:\FE\fe7.zip" --fe8-rom "C:\FE\fe8.zip" --fe7-mods "C:\FE\FE7Remastered.zip" --fe8-mods "C:\FE\Sacred Trilogy.zip"
py -3 -m arcanacart batch --init
py -3 -m arcanacart batch --resume --verbose
```

Se ejecutan desde la raíz del código; `--root DIR` permite indicar otra carpeta.
`--config private/fire-emblem.json` es el valor por defecto. La configuración
de ejemplo está en `examples/fire-emblem-batch.json`; `--init` preserva una
configuración existente válida.

| Opción de `batch` | Efecto |
|---|---|
| `--game all/fe7/fe8` | Ambos juegos por defecto; permite procesar uno |
| `--all-variants` | Todos los UPS catalogados, incluidas versiones legacy |
| `--catalog-only` | Escribe catálogo e índice; no prepara ni necesita las bases |
| `--dry-run` | Valida entradas y UPS seleccionados sin escribir ni aplicar salidas |
| `--no-scan` | Omite recursos comprimidos y usa un namespace de análisis propio |
| `--resume` | Reutiliza ROMs e informes si sus huellas siguen coincidiendo |

El catálogo conserva miembro original, ID formal y metadatos del ZIP. Selecciona
IDs exactos en `selection.fe7` y `selection.fe8`. Una lista vacía omite los mods
de ese juego; el paquete debe seguir disponible para catalogarlo. Los hashes
cortos añadidos a nombres de salidas evitan mezclar parches de distinto contenido.
Los UPS se aplican en dirección forward a su base limpia y se comprueban sus CRC.
Si una variante falla, se conserva el diagnóstico y continúan las demás.
`tables` asigna IDs de trabajo a definiciones JSON privadas, una por SHA-256 de ROM.
La guía [EJECUTAR_FE7_FE8.md](EJECUTAR_FE7_FE8.md) detalla rutas y PowerShell.

### Límites de escaneo configurables

`scan`, `extract` y `pipeline` admiten:

| Opción | Valor por defecto | Unidad |
|---|---|---|
| `--step` | 1 | Bytes entre candidatos |
| `--max-bytes` | 2097152 | Máximo descomprimido de un bloque |
| `--budget` | 67108864 | Bytes realmente producidos al descomprimir |
| `--limit` | 1000 | Resultados, no una predicción sobre el juego |
| `--max-candidates` | 100000 | Intentos de decodificación |
| `--compression` | `lz10 rle` | Formatos seleccionados, también en `batch` |

`--compression lz10` permite terminar la búsqueda LZ10 aunque el barrido RLE
encuentre candidatos especulativos costosos. RLE sigue disponible de forma
explícita con `--compression rle` o junto con LZ10. La selección queda registrada
en el AIR y en la identidad de caché. El alias antiguo `scan-lz10` conserva su
contrato y no usa esta opción; para métricas completas usa `scan --compression lz10`.

### Comparación de candidatos comprimidos

```powershell
python -m arcanacart compare-resources --left base/air.json --right mod/air.json --out comparacion
```

Acepta AIR o `resources.json` con ROM, candidatos y estadísticas. También acepta
los manifiestos independientes que registran `methods` en el nivel superior.
No vuelve a escanear ni abre rutas de archivos incluidas en el JSON. Compara por
SHA-256 de salida descomprimida, con independencia de la posición en la ROM.

Genera `resumen.json` y `catalogo-comparado.csv`. El catálogo incluye nombre de
blob por hash; los blobs están en `resources/` para pipeline y junto al manifiesto
para scan. Prioriza salidas sin coincidencia, aparta patrones 00/FF conocidos y
ordena por referencias detectadas. Una celda vacía en `patron_uniforme` no implica
un tipo conocido: esa comprobación tiene un presupuesto propio de 128 MiB de
hashing y un máximo de 2 MiB por patrón.

Una comparación de escaneos truncados, muestreados o con selecciones distintas o
desconocidas devuelve `partial` y código 3. `--dry-run` valida y calcula sin escribir.
La salida debe ser una carpeta vacía o nueva. Ausencia de coincidencia no prueba
que exista un recurso nuevo ni identifica su función en el juego.

Admiten números enteros; tamaños/step permiten `0x...`. `scan-lz10` conserva su
valor histórico `--limit 100`; su paso ahora también es 1. Para diagnósticos de
truncamiento completos utiliza `scan`; el alias antiguo conserva su manifiesto.
Los límites ZIP se configuran en la API `ArchiveLimits`; no todos se exponen en CLI.

El escáner valida primero la estructura de un candidato sin expandir sus datos.
La validación tiene una cuota independiente de tokens: el mayor entre dos veces
`--max-bytes` y 64 veces `--max-candidates`. Si se alcanza, el motivo es
`validation-budget`. Una declaración falsa de 2 MiB no consume automáticamente
2 MiB de `--budget`. Los decodificadores siguen limitando el trabajo y la memoria.

En ROMs con cabecera válida se priorizan cabeceras apuntadas por valores ROM de
32 bits alineados, ordenadas por tamaño declarado y offset. Estas coincidencias
son heurísticas. Después se recorre linealmente el resto, incluidos offsets sin
referencias. `--step` aplica a ambas fases; no se eliminan offsets impares con el
valor por defecto 1. El inventario de destinos también está acotado por candidatos.
`search_progress_percent` solo mide la fase lineal. Los contadores
`referenced_header_targets*` miden la fase priorizada; ninguno mide comprensión
semántica ni cobertura de funciones. Los recursos se mantienen como candidatos.

### Pipeline

```powershell
arcanacart pipeline --rom private/fe8.gba --profile fe8-us --tables private/fe8-tables.json --out workspace/fe8
arcanacart pipeline --rom private/fe8.gba --profile fe8-us --tables private/fe8-tables.json --out workspace/fe8 --resume
```

`--no-scan` omite recursos. `--symbols symbols.json` agrega correlación de referencias.
`--with-ghidra --ghidra-home DIR --loader-dir DIR` activa la herramienta opcional;
si no está disponible se registra la omisión. Un fallo real produce `partial`.
La reanudación sin cambios reutiliza el bundle, incluso un escaneo parcial con
sus límites explícitos; un archivo corrupto se regenera. No continúa un recorrido
desde el último offset. Para cambiar cuotas o versión, usa otra carpeta de salida.

### Símbolos y variantes

```powershell
arcanacart symbols --reference private/referencias/fireemblem8u --file fireemblem8.map --rom private/fe8.gba --out workspace/symbols.json
arcanacart compare --left workspace/base/air.json --right workspace/hack/air.json --air --out workspace/semantic-diff.json
```

El mapa debe existir dentro de la referencia; ArcanaCart no compila el repositorio.
Se admiten líneas nm (`08000100 T Function`), mapa simple, asignaciones de linker,
`.equ`/`.set` y `SET_DATA`/`SET_FUNC` con direcciones hexadecimales literales. No se
interpretan expresiones del linker ni se ejecuta código. `reference_commit` puede
ser null si no es Git; el hash del archivo siempre identifica el contenido leído.
Un símbolo en la misma dirección es una coincidencia inferida, no equivalencia C.

### Compatibilidad starter

Siguen disponibles con `feunpack` o `python -m feunpack`:

```powershell
feunpack inspect private/base.gba
feunpack inspect-zip private/base.zip
feunpack prepare-zip --zip private/base.zip --out workspace/base.gba
feunpack apply-ups --rom private/base.gba --patch private/mod.ups --out workspace/mod.gba
feunpack scan-lz10 --rom private/base.gba --out workspace/lz10 --limit 50
feunpack dump --rom private/base.gba --offset 0xA0 --size 0x20 --out workspace/header.bin
feunpack inventory private/listing.txt
```

`--allow-unknown` permite preparar una variante con cabecera válida. El comando
inspect puede describir una cabecera dañada sin prohibir investigación genérica;
prepare requiere checksum y constante válidos. `inventory` solo inventaría el texto
code2text: un listado no contiene los binarios omitidos que menciona.

## Interpretación de resultados existentes (0.5.0)

`interpret` acepta AIR o `resources.json` con `rom`, `resources` y `scan`.
Detecta `resources/` junto al AIR o usa la misma carpeta del manifiesto de scan.
`--resources` lo selecciona explícitamente. `--recipes` carga decisiones manuales;
`--palette` añade paletas binarias externas (repetible); `--base` compara candidatos.
Los límites predeterminados son 500 previsualizaciones, 512 MiB de lectura y
64 Mi píxeles por trabajo. `--max-previews`, `--byte-budget` y `--pixel-budget`
aceptan sus límites explícitos. La salida debe ser una carpeta nueva.

`report --review summary.json` incorpora las métricas de una interpretación que
coincida en ROM e inventario de candidatos.

`tables-define` admite `--layouts layouts.json` declarativos y `--symbols symbols.json`.
No hereda ubicaciones de otra ROM. `extract` sin `--scan` no repite el barrido.

`code-index --ghidra-summary functions/summary.json` verifica hashes de exports y
registra rangos reales de instrucciones. `--symbols` solo añade pistas de referencia.
Sin resumen Ghidra devuelve parcial y deja la cobertura de código sin inventar.

Consulta [CONTINUAR_0.5.0.md](CONTINUAR_0.5.0.md) para comandos Windows y formatos.
