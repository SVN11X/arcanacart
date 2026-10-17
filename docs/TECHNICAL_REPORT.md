# ArcanaCart 0.4.0 — Lote FE7/FE8 y mods

Fecha: 16 de octubre de 2026 UTC. Se extiende la entrega 0.3.0 con organización de
entradas, nombres formales, catálogo de UPS y ejecución conjunta. La auditoría
original permanece en `TECHNICAL_REPORT_v0.3.md` y `AUDIT_v0.2.md`.

## Resultado

La entrega incluye todo el código Python, lanzadores PowerShell, configuración
de ejemplo y guía en español. El proceso normal copia cuatro ZIP sin cambiar los
originales, valida las bases, aplica dos variantes seleccionadas, analiza cuatro
ROMs y publica un índice HTML común. La opción `--all-variants` procesa cada UPS
catalogado contra su base limpia. Los fallos individuales no detienen el otro juego.

| Componente nuevo | Comprobación |
|---|---|
| `patchsets.py` | Catálogo selectivo, límites propios para paquetes grandes, IDs canónicos y copia con rehash |
| `batch.py` | Configuración estricta, importación, bloqueo, namespaces, aplicación forward y reanudación |
| CLI | `batch-import`, `batch --init`, selección de juego, catálogo, dry-run y todas las variantes |
| PowerShell | Selector de cuatro ZIP, argumentos literales, Python local y apertura del informe |
| Pruebas | 35 casos nuevos; conserva las 118 pruebas previas |

## Verificación ejecutada

Linux, Python 3.12.14. **153 pruebas pasan, sin fallos, errores ni omisiones**.
Se cubren ambos juegos con fixtures sintéticos de cabecera válida, seis UPS
independientes, selección inicial, todas las variantes, CRC incompatible,
conservación de fuentes, caché corrupto, catálogos, CLI, paths, bloqueos y
protección de salidas ajenas. La prueba de lote bloquea sockets y procesos externos.
Las definiciones de tablas se comprueban por variante y la comparación AIR exige
definiciones de ambos lados.

Ruff y formato correctos; mypy sin incidencias en 28 fuentes. Wheel y sdist se
construyeron correctamente. El wheel instalado sin red ni dependencias en otro
entorno completó importación, cuatro trabajos iniciales, reanudación y ocho
trabajos al incluir todos los UPS sintéticos. Se comprobó la presencia de
esquema/Java en el wheel y de lanzadores/guía/plantilla en el sdist.

También se usaron las dos bases locales adjuntas, de 16 MiB cada una. Sus SHA-1
coincidieron exactamente con FE7 USA y FE8 USA. Para ejercitar el flujo completo
sin disponer de los ZIP de mods se construyeron dos UPS sintéticos de un byte.
Los cuatro trabajos terminaron y se reutilizaron al repetirlos; cada comparación
base/mod informó un byte cambiado. No se incluyen esas ROMs ni sus UPS en el código.

En esa prueba se limitó el escaneo a un presupuesto de 8 MiB: se registró
`scan_truncated: true` y cero recursos aceptados. Cada AIR contenía tres entidades
de identidad/cabecera. Esto verifica integración con tamaños reales; no demuestra
extracción semántica ni cobertura útil de recursos de esos juegos.

La evidencia de calidad está en `verification.json` y `TEST_RESULTS.txt`.
`RELEASE_VERIFICATION.md` describe la comprobación del paquete, y
`EJECUTAR_FE7_FE8.md` contiene el procedimiento de usuario.

## Límites materiales

- Los paquetes reales FE7 Remastered y Sacred Trilogy solo se han mostrado como
  capturas y listados code2text; no se recibieron sus bytes UPS. La selección
  inicial se deduce de esos nombres y su aplicación real se verificará al importar.
- Los lanzadores Windows no se ejecutaron aquí. Se distribuyen como código
  PowerShell 5.1/7 y deben probarse en Windows con Python 3.10+.
- Ghidra continúa experimental y no se invoca desde este lote.
- Tablas de personajes/clases/objetos requieren definición por hash. No se
  distribuyen offsets inventados para los mods, campañas, C original ni LT-Maker.
- Los límites de ZIP y escaneo acotan recursos; no garantizan extracción total.
  El detalle de privacidad, escrituras y concurrencia permanece en `SECURITY.md`.

El ZIP se crea a partir de archivos versionados. Excluye ROMs, UPS de entrada,
resultados privados, entornos, builds e historial Git. El código mantiene MIT.
