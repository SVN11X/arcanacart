# Changelog

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
