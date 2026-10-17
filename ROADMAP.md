# Hoja de ruta después de 0.4.0

## Entregado

P0: auditoría previa, originales protegidos, ZIP acotado/rehash, UPS atómico con
dirección, alias CLI, regresiones, lint/tipos y CI sin ROMs.

P1 parcial: mapa de memoria y referencias elegidas, LZ10/RLE con evidencia,
layouts reales FE7/FE8, configuración por hash, AIR, informes, comparación por campos
y pipeline reanudable. Las pruebas de tablas son sintéticas, no validación comercial.
No se declaran completos los perfiles de ningún juego.

P2 parcial/experimental: referencias locales por commit/hash y wrapper Ghidra con
exportador incremental Java. No se completó análisis Ghidra real, equivalencia de
funciones ni reconstrucción de reglas.

0.4: organización de entradas, catálogo UPS, lote FE7/FE8, índice y reanudación;
bases reales comprobadas con parches sintéticos. Falta ejecutar los ZIP reales
de los mods y probar los lanzadores PowerShell en Windows.

## Próxima versión: prioridad verificable

1. Ejecutar la matriz Windows/Linux y el exportador con Ghidra/loader/JDK elegidos.
   Resolver diferencias reales de API/importación antes de promocionar la integración.
2. Con copias autorizadas locales, verificar direcciones/conteos/nulos de tablas de
   FE7U/FE8U y definir fixtures de validación privados. Los mapas de símbolos pueden
   usar convenciones de indexación distintas: no copiar offsets sin cotejar bytes.
3. Validar el layout Item FE7 y referencias de soportes/promociones FE8; añadir
   extracción de tablas auxiliares con evidencia y comparación de variantes reubicadas.
4. Investigar BIOS Huffman con vectores independientes y el árbol de texto propio
   de FE por separado. Registrar decodificadores solo tras verificarlos.
5. Integrar resultados Ghidra como AIR Function, registrar rangos/bytes de funciones
   y contrastarlos con símbolos/source de referencia. No confundir nombre con equivalencia.
6. Instrumentar memoria pico y rendimiento con ROMs grandes sintéticas; ampliar
   streaming/caché por recurso si el presupuesto deja de ser suficiente.

## Expansión P3

Capítulos y eventos por versión, unidades/refuerzos/inventarios, texto y controles,
render de tiles/paletas, audio con formato comprobado y comparación de lógica.
Después, un adaptador LT-Maker para una versión concreta y campaña sintética abierta
en el motor. La exploración visual y otros juegos vendrán sobre ese núcleo.
El videojuego final y el multijugador siguen fuera de esta etapa.
