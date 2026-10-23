# Changelog

## 0.6.2 — Retratos de las 43 variantes revisadas

- Corrige el falso aviso «Cambió una definición» cuando Git guarda los planes y definiciones con CRLF en Windows. Su identidad normaliza únicamente CRLF a LF; los hashes de AIR, ROM, recursos y resultados siguen verificando sus bytes exactos. La reanudación conserva su identidad al cambiar solo esos finales de línea.
- Integra `Extraer-Retratos-Variantes.ps1` y el lote Python en el repositorio, con 43 definiciones vinculadas a los SHA-256 exactos de las ROM y de sus AIR existentes.
- Comprueba los rangos de exportación FE7 1–228 y FE8 1–254 contra la ROM local antes de generar PNG; valida paletas, datos raw y descompresiones puntuales, sin repetir el escáner.
- Conserva los 28 IDs vacíos previstos de cuatro variantes FE8 y admite tarjetas de 80×80 en la validación; mantiene intactos los resúmenes originales de ArcanaCart.
- Reanuda verificando entradas y archivos exportados; conserva intentos anteriores, guarda progreso ante `Ctrl+C` y genera un índice común, CSV/JSON y ZIP de resultados.
- Documenta 17.291 PNG de componentes previstos, incluidas repeticiones; los rangos propuestos no certifican el tamaño total reservado de las tablas ni la extracción de todos los recursos del juego.

## 0.6.1 — FE8 y componentes sin compresión

- Incorpora el layout de la base FE8 USA exacta, con tabla virtual en `0x8ACBC4`, 172 entradas útiles y comprobación del puntero de código en `0x5524`.
- Lee componentes raw `00` desde la ROM local verificada; su longitud incluye los cuatro bytes de cabecera. Exporta el payload en `raw-resources`, con hashes, offsets y tamaños trazables.
- Mantiene separados los bloques identificados del AIR y los bloques raw para conservar el significado de las estadísticas del escaneo LZ10.
- Añade `-Game fe8` al lanzador Windows. Se esperan 115 retratos, 111 miniaturas y 57 tarjetas en la tabla de esta base; la salida offline informa los pendientes.
- Conserva los layouts personalizados por hash y la extracción anterior de FE7. No repite el escáner ni modifica resultados existentes.

## 0.6.0 — Retratos reconstruidos y paletas verificadas

- Añade `faces`: vincula componentes a una tabla documentada, ensambla retratos de 96×80 y exporta miniaturas y tarjetas de clase por ID.
- La base FE7 USA exacta tiene un layout incorporado; otras ROMs requieren una definición explícita ligada a su hash.
- La opción `--rom` verifica los punteros, los bloques comprimidos y sus descompresiones puntuales, y recupera paletas RGB555 sin compresión.
- Genera una galería organizada, catálogos con trazabilidad y un resumen separado; conserva AIR, bloques y revisiones previas.
- Incluye `Extraer-Retratos.ps1` para continuar desde el CSV de reparación, abrir la galería y empaquetar los recursos exportados.

## 0.5.1 — Páginas gráficas y reparación de resultados existentes

- Divide las hojas de tiles que exceden 1.048.576 píxeles en PNG completos por páginas, con rangos de tiles y bytes; conserva las imágenes pequeñas.
- Añade navegación y descarga de cada página en la galería y distingue bloques con vista de archivos PNG.
- Añade `repair-previews` y `Reparar-Previsualizaciones.ps1`: verifican el AIR y el catálogo, procesan solo errores de tamaño y conservan los PNG válidos, las recetas y los errores de otras causas.
- Respalda los metadatos antes de publicar la reparación y recupera una publicación interrumpida en la siguiente ejecución.
- Los presupuestos se comprueban para el bloque completo antes de dibujarlo. Los límites de reparación se aplican solo al trabajo nuevo.

## 0.5.0 — Interpretación, gráficos y análisis documentado

- `interpret` consume AIR/resources.json y bloques SHA256.bin existentes, sin
  descomprimir de nuevo; verifica tamaño/hash, conserva offsets repetidos y compara
  opcionalmente con la base sin convertir diferencias en recursos nuevos confirmados.
- PNG sin dependencias: tiles 4/8 bpp, RGB555, transparencia opcional y mapas BG
  con bancos, flips y distribución lineal/screenblocks. Paletas externas con hash.
- Galería local con filtros, páginas de 48 bloques, trazabilidad y editor de recetas
  exportables. Aceptar una interpretación requiere evidencia; el editor explica que
  los PNG se regeneran al volver a ejecutar Python. CSP y texto escapado.
- Cuotas de lectura/previsualización; los límites y errores mantienen entradas en
  el catálogo y producen estado parcial. Escritura separada del bundle original.
- `layouts` y `tables-define`: definiciones ligadas a ROM y símbolos locales;
  layouts declarativos para estructuras adicionales sin ejecutar código. Rechazo
  de solapamientos y comprobación de arrays de punteros. Tablas sospechosas: parcial.
- `code-index`: valida exports Ghidra por ROM/hash y genera AIR Function, mapa
  de instrucciones/datos/conflictos/desconocidos y archivos documentados. Símbolos
  permanecen como referencias. Java exporta rangos de instrucciones sin rellenar huecos.
- `report --review` separa recorrido, candidatos, PNG y decisiones documentadas.
- `Interpretar-Resultados.ps1` procesa los análisis previos y genera un resumen
  sin reorganizar ZIP, aplicar UPS ni repetir escaneos. Guía y demo sintética incluidas.

## 0.4.2 — Selección de formatos y comparación integrada

- `--compression lz10`, `rle` o ambos en scan/extract/pipeline/batch; las llamadas
  existentes siguen buscando ambos formatos si no se indica selección.
- El AIR, manifiesto, estado del pipeline e informe registran el alcance. Un
  barrido LZ10 finalizado deja RLE y la identificación semántica pendientes.
- La selección se incluye en caché y carpetas del lote sin cambiar los JSON de
  configuración existentes. `--resume` sigue reutilizando bundles verificados;
  no es un cursor incremental del escáner.
- `compare-resources` acepta AIR y manifiestos de las pruebas de terminal,
  compara hashes descomprimidos y genera resumen JSON y catálogo CSV sin repetir
  descompresión. Se marcan patrones 00/FF conocidos con trabajo acotado.
- Reanálisis Windows de ROMs preparadas: LZ10, 20.000 resultados, 500.000 intentos
  por defecto; `-CompareBase` añade las bases y compara cada variante. Prioriza el
  entorno local de Datos y crea un CSV resumen nuevo por ejecución.
- La organización previa de ZIP se mantiene como un paso independiente. Este
  reanálisis opera sobre las `.gba` ya preparadas.

## 0.4.1 — Cuotas reales y reanálisis transparente

- Validación LZ10/RLE sin expandir salidas falsas; cuota separada de tokens.
- `--budget` mide bytes producidos, no tamaños anunciados por cabeceras rechazadas.
- Cabeceras con referencias ROM se priorizan; el recorrido lineal sigue disponible.
- Métricas separadas para referencias, recorrido lineal, validación y salida.
- Escaneo truncado produce `partial` y código 3 en scan/extract/pipeline y en lotes.
- Los informes muestran avance, clasificación y tablas omitidas en texto legible.
- Caché verificable de resultados parciales sin errores de herramientas externas.
- Reanálisis PowerShell directo de las ROMs ya generadas, con carpetas nuevas y CSV.

## 0.4.0 — FE7, FE8 y variantes

- Importación de cuatro ZIP con nombres canónicos, copia verificada y registro de procedencia.
- Catálogo de UPS con nombre original, ID formal, versión, marca legacy y hash del contenedor.
- Soporte acotado de paquetes de mods de hasta 2 GiB, sin extraer archivos ajenos a UPS.
- Lote de ambas bases y mods seleccionados, con CRC de base/parche/salida y análisis independiente.
- Índice HTML común, informes JSON, diferencias binarias y tablas opcionales por variante.
- Reanudación con hashes, bloqueo y espacios de análisis separados por configuración.
- Lanzadores PowerShell y selector de los cuatro archivos; guía completa en español.
- 35 pruebas nuevas de lote/importación y conservación de las 118 anteriores.

Se verificaron las bases FE7U/FE8U adjuntas con UPS sintéticos de prueba. Los ZIP
reales de los autores de los mods y los lanzadores Windows requieren validación
en el entorno del usuario. La extracción completa de campañas continúa pendiente.

## 0.3.0 — ArcanaCart

- Nueva distribución/executable `arcanacart`, versión coherente y alias `feunpack`.
- Auditoría de todos los archivos y ejecución de las 11 pruebas iniciales antes de cambios.
- ZIP: preflight, límites, duplicados/symlinks, CRC y rehash después de escribir.
- I/O acotado y publicación atómica por archivo; protección frente a colisiones con entradas.
- UPS1: dirección explícita, preservación de base, sidecar con huellas y diferencias.
- Memoria GBA, mirrors de RAM/VRAM y ventanas ROM, lecturas LE y referencias elegidas.
- Scanner byte a byte LZ10/RLE, presupuestos y evidencia; deduplicación de outputs.
- Lectores de tablas FE7/FE8 con definiciones ligadas al hash de cada variante.
- AIR 1.0.0, validador y esquema, JSON/CSV e informes locales Markdown/HTML.
- Símbolos locales con hash/commit y comparación de entidades por clave/campo.
- Pipeline con bloqueo, estados por etapa y reanudación del bundle por hashes.
- Integración Ghidra Headless opcional, filtros/lotes/índice y exportación Java por función;
  marcada experimental hasta ejecutarse contra la herramienta real.
- Ejemplo sintético original, pruebas de corrupción/seguridad/integración y CI Windows/Linux.
- Ruff, formato, mypy, extras de desarrollo y pre-commit opcional.
- `.s`, `.asm`, `.map` y binarios propios ya no se ignoran globalmente.

No se incorporan ROMs, assets, campañas, dependencias de IA ni servicios comerciales.
No se implementan campañas LT-Maker, decodificador de texto FE ni extracción total de hacks.

## 0.2.0 — Starter recibido

Inspección GBA/ZIP, preparación, UPS1, scanner LZ10, dump de rangos, inventario
code2text y exportador Ghidra Jython limitado a 1000 funciones. Once tests sintéticos.
