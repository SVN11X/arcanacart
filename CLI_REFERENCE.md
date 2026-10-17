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

`completed` puede contener etapas `skipped` o escaneo `truncated`: consulta estados,
razones y métricas. Nunca significa extracción completa de una campaña.

## Comandos

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
| `--budget` | 67108864 | Suma de tamaños declarados de los intentos |
| `--limit` | 1000 | Resultados, no una predicción sobre el juego |
| `--max-candidates` | 100000 | Intentos de decodificación |

Admiten números enteros; tamaños/step permiten `0x...`. `scan-lz10` conserva su
valor histórico `--limit 100`; su paso ahora también es 1. Para diagnósticos de
truncamiento completos utiliza `scan`; el alias antiguo conserva su manifiesto.
Los límites ZIP se configuran en la API `ArchiveLimits`; no todos se exponen en CLI.

### Pipeline

```powershell
arcanacart pipeline --rom private/fe8.gba --profile fe8-us --tables private/fe8-tables.json --out workspace/fe8
arcanacart pipeline --rom private/fe8.gba --profile fe8-us --tables private/fe8-tables.json --out workspace/fe8 --resume
```

`--no-scan` omite recursos. `--symbols symbols.json` agrega correlación de referencias.
`--with-ghidra --ghidra-home DIR --loader-dir DIR` activa la herramienta opcional;
si no está disponible se registra la omisión. Un fallo real produce `partial`.
La reanudación sin cambios reutiliza el bundle; un archivo corrupto se regenera.

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
