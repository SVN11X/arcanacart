# Proceso gradual de investigación

Este documento conserva la ruta de lectura del starter, actualizada a ArcanaCart.

1. Identifica versión y huellas con `inspect`; prepara una copia con `prepare`.
2. Ejecuta el pipeline genérico. Revisa candidatos, referencias y regiones desconocidas.
3. Consigue un mapa local de la referencia elegida y registra su commit/hash con
   `symbols`. Investiga ubicaciones y conteos; crea una definición para ese SHA-256.
4. Extrae tablas y revisa IDs, signedness, límites y desconocidos. Para hacks crea
   definiciones por separado. No transfieras offsets porque el título coincida.
5. Aplica UPS en otra salida y compara bytes o entidades AIR; no confundir cambios
   binarios con mecánicas comprendidas.
6. Si dispones de Ghidra/loader/JDK, sigue [GHIDRA_INTEGRATION.md](../GHIDRA_INTEGRATION.md).
   El exportador ya no impone las primeras 1000 funciones; la integración está
   etiquetada experimental hasta comprobar su ejecución real.
7. Contrasta funciones con referencias de descompilación. Reconstrucción desde C
   comunitario, ensamblador recuperado y pseudocódigo de Ghidra son productos distintos.

No se genera una campaña `.ltproj`. Consulta [COMPATIBILITY.md](../COMPATIBILITY.md)
y [ROADMAP.md](../ROADMAP.md). El trabajo autorizado aquí es crear herramientas de
investigación, no desarrollar el videojuego final ni un sistema multijugador.
