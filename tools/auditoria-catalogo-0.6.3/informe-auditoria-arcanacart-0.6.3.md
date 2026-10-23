# ArcanaCart 0.6.3: auditoría independiente del catálogo

Fecha: 23 de octubre de 2026. Resultado: **APROBADO para integridad, trazabilidad y coherencia de los archivos entregados**, con las limitaciones indicadas al final.

No se ha modificado ArcanaCart, cambiado su versión, escaneado una ROM ni repetido la extracción. No se encontró un defecto que requiera un parche.

## Archivos examinados

| Archivo | Tamaño ZIP | Archivos interiores | SHA-256 del ZIP |
| --- | ---: | ---: | --- |
| `catalogo-retratos-20261023-141758-cfd1e9(1).zip` | 5.647.196 bytes | 1.482 | `ece62fcefee1e670dfaff716acb69d579c6bc06fc3fa8f25b36bc28786f97ca6` |
| `retratos-variantes-20261023-110704-777bef-resultado-20261023-112322-29cdaa.zip` | 53.550.650 bytes | 41.295 | `7e2973af174aaf3cf62a6bda5734b82b852703d394dafd311624a2a5f01ae358` |

Los SHA-256 de esta revisión se calcularon sobre bytes exactos. No se normalizaron saltos de línea de ningún archivo. Los manifiestos internos permiten comprobar consistencia e integridad, pero no son firmas de autenticidad externas.

## Resultados comprobados

| Concepto | Recuento verificado |
| --- | ---: |
| Variantes | 43: ocho FE7 y 35 FE8 |
| PNG únicos por SHA-256 | 938 |
| PNG con algún píxel visible | 934 |
| PNG completamente transparentes | 4 |
| Apariciones conservadas | 17.291 |
| Apariciones de imágenes transparentes | 219 |
| Paletas únicas RGB555 | 537 |
| Copias de PNG evitadas | 16.353 = 17.291 − 938 |
| Archivos de entrada declarados por la consolidación | 27.178; recuento compatible con los archivos utilizados del lote |

| Juego | Retratos | Miniaturas | Tarjetas de clase | Total de apariciones |
| --- | ---: | ---: | ---: | ---: |
| FE7 | 1.560 | 1.534 | 264 | 3.358 |
| FE8 | 5.155 | 5.155 | 3.623 | 13.933 |
| Total | 6.715 | 6.689 | 3.887 | 17.291 |

| Dimensiones reales de los PNG | Imágenes únicas |
| --- | ---: |
| 96 × 80 | 441 |
| 32 × 32 | 365 |
| 80 × 72 | 131 |
| 80 × 80 | 1 |

### Integridad y hashes

- Se leyeron completos los 42.777 archivos interiores de ambos ZIP. Sus CRC fueron válidos. No se encontraron nombres repetidos, colisiones de mayúsculas/minúsculas ni rutas absolutas o con escapes de directorio.
- Los 1.481 artefactos enumerados por `catalog-state.json` están presentes y sus SHA-256 coinciden. El único archivo sin autorreferencia es el propio manifiesto.
- Los hashes de `resumen.json`, `run-state.json` y `planes-usados.json` del lote original coinciden exactamente con los registrados por el catálogo consolidado.
- Se verificaron los 41.160 artefactos enumerados en los manifiestos de las galerías originales y la cadena de hashes de los 43 `resultado.json`, `validacion.json` y `faces-state.json`.

### PNG y paletas

- Los 938 PNG se abrieron, verificaron y decodificaron. Son RGBA de ocho bits por canal y sus dimensiones y visibilidad coinciden con el catálogo. Sus valores alfa son 0 o 255.
- Cada una de las 17.291 apariciones apunta a un PNG original presente. Su contenido coincide byte por byte con el PNG consolidado indicado. No hay apariciones originales omitidas ni claves repetidas de variante/ID/componente.
- Las 537 paletas tienen 32 bytes, equivalentes a 16 entradas RGB555. Su hash coincide con su nombre; sus bytes coinciden con las paletas del lote y con los valores hexadecimales de la validación original.
- Los colores visibles de cada PNG son compatibles con las paletas asociadas a sus apariciones. No hay imágenes ni paletas incluidas sin referencia.
- El lote incluye bloques `raw-resources` que permiten recalcular el SHA-256 del recurso fuente en 5.155 apariciones de origen `local-rom-raw`. Se comprobó esa relación. Las otras 12.136 apariciones tienen origen `air-resource`; para ellas se comprobaron los hashes declarados, PNG y paletas disponibles, sin atribuir una verificación de bytes de AIR ausentes.
- No se detectaron dos PNG distintos con las mismas dimensiones y exactamente los mismos bytes RGBA decodificados. La deduplicación certificada sigue siendo la definida por el proyecto: SHA-256 del PNG, no identidad de personaje ni semejanza visual.

### CSV, variantes e IDs

- `imagenes.csv` contiene 938 filas y `ocurrencias.csv` contiene 17.291. Ambos se leen como CSV UTF-8 con BOM, sin errores de estructura.
- Se compararon todos sus campos con `catalogo.json`: hashes, rutas, dimensiones, visibilidad, tipos, juegos, variantes, IDs decimales y hexadecimales, offsets, procedencias y conteos.
- Todas las variantes corresponden a los 43 trabajos del plan original. Los hashes de ROM/AIR y los nombres de variante concuerdan entre sus registros.
- Los rangos son 1–228 para FE7 y 1–254 para FE8. Las apariciones coinciden con los componentes generados en los rangos revisados, sin IDs exportados fuera de ellos.
- Cada una de FE8 010–013 tiene los mismos 28 IDs vacíos previstos: 176, 177, 178, 179, 196, 197, 198, 199, 201, 202, 203, 204, 206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 217, 220, 229, 230, 231 y 239. Son 112 posiciones vacías contando las cuatro variantes; no hay pérdidas de consolidación en esas posiciones.

### Galería

- Los datos JSON embebidos en `index.html` coinciden íntegramente con las imágenes y procedencias de `catalogo.json`.
- El hash del script coincide con la autorización SHA-256 de su política CSP. Los enlaces estáticos a CSV y JSON apuntan a archivos incluidos. Las rutas de PNG y paletas referenciadas existen.
- Se inspeccionó una muestra de 49 PNG renderizados como imágenes, incluyendo los tres tipos y ambos juegos. Esto comprueba una muestra de los recursos, no la presentación de la interfaz HTML.
- **Sigue pendiente renderizar la galería en un navegador real.** El navegador disponible para esta sesión rechazó la navegación `file://` por su política de URL. La comprobación estática no certifica la disposición visual, los clics de descarga ni el comportamiento real de los filtros.

## Dos detalles que no son defectos

1. Las galerías genéricas de FE8 010–013 tienen `status: partial`; sus resultados de lote acotado tienen `status: completed`. Los registros genéricos enumeran exactamente los 28 vacíos previstos por variante, con cero errores y cero componentes pendientes. El resultado es coherente con el alcance del plan.
2. La tarjeta FE8 ID `0x0AF` mide **80 × 80**, y aparece en las 35 variantes. Su bloque declarado contiene 3.200 bytes 4bpp: 100 tiles, organizados en diez columnas y diez filas. El PNG y sus dimensiones coinciden con el lote. No corresponde recortarla a 80 × 72.

## Qué no demuestra esta auditoría

- No se recibieron las ROM ni los AIR completos. Sus SHA-256 se cotejaron entre los metadatos disponibles, pero no se recalcularon desde esos archivos. Tampoco se volvieron a leer los offsets de las ROM.
- No se recalcularon los hashes de bloques comprimidos o recursos AIR que no están incluidos en estos dos ZIP.
- La concordancia con el lote no demuestra por sí sola que cada composición gráfica represente exactamente lo mostrado por el juego. No se contrastaron todos los recursos con capturas de emulación.
- No se confirmó el tamaño total reservado de las tablas ni se revisaron IDs posteriores a los rangos acordados. No se certifica extracción total del juego.
- Siguen pendientes la revisión visual de la galería, los nombres de personajes y las animaciones de ojos y boca.

## Siguiente paso concreto

Conservar este catálogo como referencia verificada y preparar el siguiente módulo de extracción: **iconos de objetos, incluidas armas**, empezando por las dos ROM base y extendiéndolo después a las variantes cuyas referencias puedan comprobarse.

1. Revisar en el código local 0.6.3 cómo se leen AIR, referencias, bloques y paletas, y cómo se generan las salidas. El código público no debe suponerse idéntico al local. Antes de solicitar archivos para un parche, identificar las rutas realmente necesarias.
2. Crear un inventario a partir de los AIR y resultados ya existentes: bloques conocidos, hashes, offsets y referencias. Marcar los recursos ya vinculados a retratos y conservar candidatos sin clasificación confirmada. Esta fase no necesita repetir un escaneo de ROM.
3. Identificar y comprobar las referencias y la geometría del primer conjunto de iconos en FE7 y FE8 base. Si hacen falta lecturas nuevas de ROM, deben limitarse a las tablas y bloques concretos, vinculados a sus hashes; las variantes deben validarse individualmente antes de reutilizar una definición.
4. Exportar los iconos identificados con PNG, paleta y manifiesto de procedencia; conservar juego, variante, índice/ID, offsets, tamaños, hashes y vínculo con el bloque fuente. No asignar nombres por semejanza ni declarar como icono un bloque sólo porque pueda dibujarse.
5. Consolidarlos con deduplicación y procedencias, utilizando el mismo criterio que ya funcionó para retratos. Entregar la implementación como `.patch` para `git am`, basado en el código local 0.6.3 y probado antes de ampliar el lote.

Este es un paso de desarrollo propuesto. En esta auditoría no se han localizado ni extraído todavía los iconos.

## Evidencia incluida

- `auditoria-datos.json`: resultados estructurados, comprobaciones, hashes de ambos ZIP, conteos y detalle de las 43 variantes.
- `variantes-verificadas.csv`: rangos, estados y conteos por variante.
- `auditar_catalogo.py`: auditor independiente de solo lectura utilizado en esta sesión; requiere Python y Pillow. La salida JSON es el único archivo que escribe al ejecutarse.
- `LEEME.txt`: instrucciones PowerShell para repetir la auditoría con los dos ZIP originales. No aplica cambios al repositorio.
