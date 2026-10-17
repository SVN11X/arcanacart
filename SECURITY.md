# Seguridad y privacidad

ArcanaCart procesa entradas localmente. No contiene clientes de red, telemetría,
subidas, ejecución de ROMs ni descargas de dependencias durante análisis. Invocar
Ghidra es opcional y explícito. Los repositorios de referencia solo se leen; no se
construyen, no se importan como Python ni se ejecutan sus scripts.

## Controles implementados

- Lecturas regulares limitadas antes y durante lectura; mínimo de cabecera GBA.
- Preflight del directorio central ZIP antes de crear objetos ZipInfo: contenedor
  128 MiB, directorio 4 MiB, 4096 miembros, expansión declarada total 256 MiB,
  ROM seleccionada 64 MiB y ratio 2000 por defecto. La API permite personalizarlos.
- ZIP64/multidisco no admitidos. Controles de duplicados, CRC, longitudes,
  symlinks y nombre ROM seleccionado. Ningún miembro usa su ruta como destino.
- El catálogo de paquetes de mods usa límites propios: contenedor y expansión
  declarada total de 2 GiB, directorio de 4 MiB, 4096 miembros, cada UPS de hasta
  128 MiB + 1024 bytes y ratio 2000. Lee solo los UPS seleccionados; no extrae
  directorios, readmes, ejecutables ni otros miembros. Catalogar no comprueba el
  CRC interno de cada UPS; ese control ocurre al seleccionarlo para aplicar.
- La copia ZIP compara tamaño y SHA-256 de la lectura y de lo escrito antes de
  publicarse. Los temporales se cierran antes de limpiar, para Windows.
- UPS valida CRC del parche, correspondencia de origen/destino y CRC de salida.
  Puede forzarse dirección; una base incompatible se rechaza. Base y parche tienen
  límites. No se aplican IPS/BPS como si fueran UPS.
- Publicación por hard link sin sobrescritura o replace explícito en `--force`.
  Temporales en el mismo directorio y `fsync` de contenido. Se rechazan symlinks de
  salida/directorios, paths equivalentes y hard links a las entradas conocidas.
- El pipeline tiene bloqueo de escritor y estado reanudable por hashes.
- Importación y lote tienen sus propios bloqueos. Las rutas de configuración
  permanecen dentro de `private/` o `workspace/`; se rechazan escapes y symlinks.
  Los cuatro destinos son distintos. Las entradas existentes con otro contenido
  y los índices de otra aplicación se conservan y producen un error explícito.
- Parsers binarios comprueban rangos; descompresión tiene cota por bloque y agregada.
- XML code2text tiene límite de 8 MiB, rechaza DTD/entidades y controla parseos fallidos.
- AIR comprueba consistencia y profundidad, no admite NaN; HTML escapa entradas,
  CSV protege fórmulas, Markdown usa fences seguros.
- Subprocesos con argv explícito; en Windows el launcher Ghidra `.bat` restringe
  caracteres especiales. No se interpola contenido de ROM en comandos.

## Alcance del modelo de amenazas

Las entradas pueden ser corruptas o maliciosas. El directorio de trabajo y las
herramientas instaladas deben pertenecer al usuario de confianza. Las comprobaciones
por ruta no constituyen aislamiento frente a otro usuario que pueda sustituir
concurrentemente directorios del filesystem. No ejecutes con privilegios elevados.
Un filesystem que no admite hard links seguros/replace atómico puede hacer fallar
la publicación: no se degrada silenciosamente a una escritura destructiva.
No se garantiza durabilidad transaccional frente a corte de energía ni atomicidad
conjunta entre ROM y manifiesto; un fallo tardío puede dejar la ROM correcta sin
sidecar. La entrada permanece intacta. El estado permite detectar bundles incompletos.

Los límites reducen agotamiento de memoria; no son un sandbox de CPU universal.
El scan conserva blobs únicos en memoria hasta terminar el bundle. Ajusta el
presupuesto para tu equipo. Los resultados y logs externos siguen siendo privados.
El exportador Java y Ghidra requieren revisión adicional con una instalación real.

## Publicación

`.gitignore` excluye ROMs, parches, saves, archivos comprimidos, outputs y referencias
privadas. No ignora globalmente código propio `*.s`, `*.asm`, `*.map` o `*.bin`.
Genera resultados siempre dentro de `workspace/`, `private/` u otras carpetas
excluidas. Revisa `git status` antes de publicar: `.gitignore` no es control de acceso.
Los informes normales conservan solo nombre de archivo fuente y rutas de símbolos
relativas; no se empaquetan logs ni resultados de ROMs en la distribución.

Conserva permisos y licencias del contenido. MIT cubre este proyecto; no concede
redistribución de juegos, gráficos, diálogos, música o pseudocódigo derivado ajenos.
