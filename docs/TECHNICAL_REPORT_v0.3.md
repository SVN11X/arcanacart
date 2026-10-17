# ArcanaCart v0.3.0 — Informe técnico de entrega

Informe histórico de la entrega anterior. La validación y el alcance de la
versión actual están en [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md).

Fecha: 16 de octubre de 2026 UTC. Entrada utilizada:
`fe-gba-disasm-starter-v0.2(2).zip`, los 20 archivos del starter.
Se trabajó directamente sobre una copia del código adjunto y se conservó el
contenido original como commit base del parche.

## Resultado y alcance

Se entrega una herramienta ejecutable local con seguridad reforzada, API/CLI
compatible, núcleo GBA, escaneo de compresión, lectores de tablas con procedencia,
AIR, comparación y pipeline de informes. **118 pruebas pasan**, incluidas las
11 del starter. La instalación y el ejemplo funcionaron desde un wheel en un
entorno virtual aislado, sin dependencias de ejecución y fuera del árbol fuente.

La implementación completa la estabilización central P0 y una parte funcional
verificable de P1. P2 incluye importación de referencias y una integración Ghidra
experimental. No se presenta como un extractor completo de Fire Emblem, de sus
hacks, ni como conversor a campañas LT-Maker.

## Auditoría del starter antes de editar

`python -m unittest discover -s tests -v`: 11 pruebas correctas. Se revisaron README,
pyproject, todos los módulos, el script Ghidra, las pruebas y los tres documentos.
Se comprobó `python -m feunpack --help` y ayuda de inspect.

Se reprodujeron dos fallos en archivos temporales:

1. `patch_file(base, patch, base)` reemplazaba la propia base original.
2. `prepare_zip` aceptaba metadatos SHA-256 obsoletos del mismo tamaño porque solo
   comparaba longitud al volver a leer la ROM.

Además faltaban publicación atómica en varios comandos, controles de directorio
central ZIP/duplicados/ratio, límites de lecturas, manejo seguro de temporales para
Windows, estados por función Ghidra, tipos/CI, mapa de memoria y esquema semántico.
`.gitignore` ocultaba globalmente ensamblador y otros posibles archivos de código.
La versión del paquete no coincidía con la de distribución. El detalle previo a
correcciones está en `docs/AUDIT_v0.2.md`.

## Cambios implementados

| Área | Resultado verificable |
|---|---|
| I/O y privacidad | Lecturas limitadas, archivos regulares, publicación atómica sin clobber, protección por path/hardlink, rechazo de symlinks y limpieza de temporales |
| ZIP | Preflight antes de asignar objetos de miembros, límites configurables en API, selección de una ROM, CRC, integridad de contenido escrito y conservación de originales |
| UPS1 | CRC de parche/base/salida, reversibilidad, dirección explícita, dry-run, metadatos y escrituras atómicas |
| Núcleo GBA | Hashes, identidad por referencia exacta, cabecera/versiones/región orientativa, offsets, ventanas ROM y mirrors RAM/VRAM, lecturas LE y rangos |
| Referencias binarias | Búsqueda alineada hacia destinos seleccionados, ubicación/destino/evidencia y estado inferido; cobertura por unión de intervalos y solapamientos |
| Compresión | LZ10 conservado y RLE BIOS nuevo, paso 1, límites por bloque/agregados, hashes, rechazos, truncamiento explícito y outputs únicos |
| FE7/FE8 | Layouts Character/Class de ambos; Item de FE8. Lectura real de bytes en rangos definidos, estadísticas con signo, campos desconocidos y evidencia de fuente |
| AIR | Esquema 1.0.0, IDs deterministas, procedencia por variante, referencias, validación/confianza y validador sin dependencia de servicios |
| Exportación | JSON, CSV con protección de fórmulas, esquema e informes Markdown/HTML locales con escape |
| Referencias locales | Importador de nm/map/asignaciones/SET_DATA/SET_FUNC, hash de archivo, commit Git, conflictos y coincidencias inferidas |
| Comparación | Rangos binarios acotados y diferencias por tipo/clave/campo AIR, conservando offsets separados |
| Pipeline | Etapas/omisiones/errores, bloqueo de escritor, outputs verificables y reanudación por fingerprints y hashes |
| Ghidra | Detector y wrapper síncrono ARMv4T, Java exportador por función, filtros, lotes, reanudación e índice; experimental hasta ejecutarse realmente |
| Distribución | Paquete arcanacart 0.3.0, feunpack compatible, wheel con esquema/Java, CI Windows/Linux, Ruff, formato, mypy y pre-commit opcional |

Los cuerpos AST de las 11 pruebas originales se conservaron; sus archivos solo
recibieron formato/imports. No se descartó una prueba para obtener un resultado verde.
Los parsers fueron implementados a partir de estructuras documentadas, sin copiar
campañas, gráficos, diálogos, música ni código externo al proyecto.

## Cómo usar el extractor de tablas

Una ROM identificada por SHA-1 no determina automáticamente qué tablas extraer.
Se requieren ubicación, cantidad de registros y clave inicial documentadas en un
JSON `--tables`, ligado al SHA-256 concreto de esa imagen. Sin ese archivo el
pipeline conserva identificación/compresión/informes y marca tablas como omitidas.

Esta decisión impide aplicar offsets vanilla a variantes modificadas. Se consultaron
headers y convenciones públicas, pero no se adjuntaron ROMs comerciales a esta
solicitud para cotejar sus ubicaciones. Los registros de variantes desconocidas
permanecen `inferred`. El ejemplo muestra una configuración completa de datos
sintéticos; no se inventan tablas de FE7 Remastered ni Sacred Trilogy.

Los inventarios iniciales, eventos y promociones bifurcadas no se deducen de campos
que no los contienen. Esos campos aparecen como desconocidos/pedientes.

## Verificación ejecutada

Entorno local: Linux, Python 3.12.14. Java disponible, Ghidra ausente.

```bash
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build --no-isolation
```

Resultados: **118/118 pruebas, cero fallos, cero errores y cero omisiones**;
Ruff y formato correctos; mypy sin incidencias en 26 fuentes; generación de wheel
universal Python y sdist correcta. El extra jsonschema estuvo instalado para
validar AIR independientemente del validador propio.

Se instaló el wheel con `--no-index --no-deps` en otro entorno virtual. Desde fuera
del repositorio se comprobaron ambos ejecutables, doctor, esquema/Java empaquetados,
generador sintético, pipeline y reanudación. La prueba que bloquea sockets y procesos
externos confirma que el pipeline básico no necesita red ni herramientas externas.

| Métrica del ejemplo sintético | Resultado observado |
|---|---|
| Imagen | 4096 bytes |
| Registros de tablas | 6 |
| Entidades totales | 12 |
| Bloques / salidas únicas | 3 / 2 |
| Bytes clasificados / denominador | 560 / 4096 |
| Bytes desconocidos | 3536 |
| Caché al repetir | cache_hit: true |

Son métricas del fixture, **no cobertura de un juego comercial**. El fixture incluyó
un falso candidato RLE dentro de la cabecera; se detectó durante pruebas y se añadió
exclusión de cabecera válida y regresión correspondiente. Se probaron también ZIP
truncado/CRC/duplicados/traversal/symlink/ratio/conteo manipulado, carreras de publicación,
fallos de disco, UPS inválido/dirección/roundtrip, límites de lectura/descompresión,
AIR corrupto, HTML/CSV maliciosos, referencias y caché dañado. La prueba de memoria
comprueba rechazo de una salida LZ10 excesiva antes de una asignación grande;
no es un benchmark de memoria pico de todas las operaciones.

Evidencia: `docs/TEST_RESULTS.txt`, `docs/verification.json`,
`docs/source-evidence.json`, `examples/synthetic_air.json` y
`examples/synthetic_report.html`. Las fuentes consultadas están en `docs/SOURCES.md`.

## Límites materiales de esta entrega

- No se ejecutaron ROMs comerciales, Windows, WSL o macOS en este entorno.
  La matriz CI está preparada; su mera existencia no demuestra ejecución en ellos.
- Ghidra no se instaló. Las pruebas de su wrapper utilizan procesos/estados simulados,
  no decompilaciones reales. El Java fue contrastado con fuentes API, pero no se
  compiló ni importó una ROM con el loader. Sigue experimental.
- Los rangos Ghidra filtran funciones exportadas por dirección inicial; no limitan
  Auto Analysis a un rango. Su salida todavía no se integra como AIR Function.
- Las referencias locales relacionan nombres/direcciones; no prueban equivalencia
  de funciones ni reconstruyen automáticamente C comunitario.
- El escaneo es heurístico, puede conservar falsos positivos y puede detenerse por
  presupuesto. Se registran esos límites, sin extrapolar cobertura.
- El caché Python opera por bundle; no reanuda a mitad de una tabla. Hay deduplicación
  de archivos de recursos, pero cada candidato nuevo se decodifica para validarse.
- La escritura es atómica por archivo; ROM y sidecar no constituyen una transacción
  conjunta. Directorios y herramientas instaladas deben pertenecer al usuario de confianza.
- Huffman BIOS/FE, objetos FE7, capítulos, eventos, gráficos, audio y reglas de combate
  siguen pendientes. AIR admite tipos que todavía no tienen extractor.
- LT-Maker no está implementado ni validado. No se genera `.ltproj`, campaña,
  videojuego ni sistema multijugador. No se integró código de LT-Maker/FEMultiPlayer.

## Prioridad recomendada para 0.4

Primero ejecutar Windows/Linux y Ghidra/loader/JDK reales; después cotejar tablas
con copias autorizadas y mapas versionados. Luego extender Item FE7, soportes y
promociones, validar decodificadores de texto y convertir funciones a AIR. La
expansión a eventos/campañas y LT-Maker requiere pruebas específicas posteriores.

## Archivos e instrucciones

`docs/CHANGED_FILES.txt` enumera todas las altas/modificaciones frente al starter.
`README.md` e `INSTALLATION.md` permiten instalar y probar; `CLI_REFERENCE.md`
documenta comandos/códigos y `EXTRACTION_FORMATS.md` el contrato de datos.
Se entrega ZIP del repositorio y parche Git compatible con `git am` sobre v0.2.
El empaquetado excluye ROMs, blobs privados, referencias externas, logs Ghidra,
entornos, cachés, historial Git y directorios de build.
