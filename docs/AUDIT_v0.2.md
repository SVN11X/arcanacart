# Auditoría previa a cambios — FE-GBA Disasm Starter v0.2

Fecha: 2026-10-16 UTC. Entrada: `fe-gba-disasm-starter-v0.2(2).zip`.
Se leyeron los 20 archivos de código, pruebas y documentación; las carpetas
del ZIP no se cuentan como archivos. Se conservó una copia intacta como base Git.

## Evidencia inicial

- Python 3.12.14, Linux. `python -m unittest discover -s tests -v`: **11/11**.
- `python -m feunpack --help` e `inspect --help`: funcionan.
- No hay ROMs adjuntas a este encargo. No se reutilizó como evidencia la
  validación de ROMs que el starter documenta de una sesión anterior.
- Ghidra no está instalado; Java sí. Windows y WSL no están disponibles.

## Hallazgos antes de corregir

| Prioridad | Archivo | Comportamiento observado / riesgo | Acción propuesta |
|---|---|---|---|
| P0 | `ups.py:patch_file` | Escribe directamente y acepta salida igual a base; una reproducción temporal sobrescribió `abc` con `abd`. Sin límites de lectura de archivos ni control propio de sobrescritura. | Rechazar alias de entradas, lectura acotada, publicación atómica y dirección explícita. |
| P0 | `archives.py:prepare_zip` | Inspecciona y vuelve a abrir; solo compara longitud. Una prueba con metadatos obsoletos del mismo tamaño publicó un hash falso. | Comparar SHA-256 de bytes escritos y validar de nuevo antes de publicar. |
| P0 | `archives.py` | `exists` seguido de `os.replace` permite sobrescribir una salida creada entre ambos; limpieza del temporal dentro de archivo abierto falla en Windows. Manifiesto no atómico. | Temporales cerrados, limpieza `finally`, publicación sin sobrescritura y metadatos atómicos. |
| P0 | `archives.py` | Selección .gba limitada a 64 MiB, CRC de ZipFile sí comprobado, pero no hay política para nombres duplicados, symlinks, cantidad de miembros, ratio o tamaño del contenedor. Los nombres internos nunca se utilizan como destinos (esto ya es correcto). | Preservar destino explícito; rechazar miembros ROM peligrosos y limitar archivo/miembros/expansión. |
| P0 | `cli.py` | `inspect` lee todo antes de comprobar tamaño; `dump` y resultados LZ10 usan escrituras directas; JSON de errores no disponible. | Límites antes y durante lectura; códigos coherentes, diagnóstico y escrituras seguras. |
| P0 | `.gitignore` | Ignora globalmente `*.s`, `*.asm`, `*.map`, `*.elf`, `*.bin`, ocultando potencial código propio. | Ignorar salidas privadas por carpeta, conservando ensamblador legítimo. |
| P1 | `lz10.py` | Descompresor básico válido y 4 pruebas correctas. Scanner solo busca cada 4 bytes por defecto, retiene todas las salidas, sin presupuesto agregado ni evidencias de referencias. | Escaneo byte a byte, presupuestos, hashes, distinción estructural/semántica. |
| P1 | `gba.py` | 64 MiB máximo pese a ventana ROM normal de 32 MiB. Sin mapa, punteros, versión de cabecera, AIR o extractores. | Mantener inspección de archivos expandidos con advertencia, mapa de 32 MiB, identidad por hash exacto. |
| P2 | `ExportFunctions.py` | Solo UI, primeras 1000 funciones, fallos omitidos, CSV manual, sin reanudación ni validación de arquitectura. | Exportador Java Headless opcional, estados por función, índice, huellas y filtros. |
| P0 | `manifest.py` | XML y texto sin cota de tamaño ni límites de entidades; errores de parseo no manejados por CLI. | Lectura limitada, rechazo de DTD y validación. |
| P0 | paquete | `__version__` dice 0.1.0, distribución 0.2.0. Sin CI, lint, tipos ni instalación comprobada. | Versión única, alias compatible y checks reproducibles. |

## Alcance verificable

No existen parsers semánticos ni exportación a LT-Maker en v0.2. Las pruebas
originales no verifican Ghidra, ROMs reales, malformaciones ZIP avanzadas ni
publicación atómica. Implementar primero P0, luego un P1 con tablas documentadas
y fixtures sintéticos; P2 solo como integración opcional con límites declarados.
No copiar código o contenido de repositorios externos al paquete.
