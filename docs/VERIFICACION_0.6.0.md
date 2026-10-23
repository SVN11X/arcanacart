# Verificación de ArcanaCart 0.6.0

## Datos reales proporcionados

El ZIP de validación de FE7 contiene 3.767 bloques binarios y cuatro archivos
JSON. Se normalizaron los separadores de ruta del ZIP de Windows únicamente
para la extracción de trabajo en Linux. El archivo subido se conserva intacto.

- 4.274 candidatos en el AIR, 3.767 hashes únicos.
- Los 3.767 archivos coinciden en tamaño y SHA-256 con el manifiesto.
- Volumen total de bloques únicos: 27.845.718 bytes.
- El hash del AIR coincide con `source_manifest_sha256` del resumen.
- El inventario coincide con `candidate_inventory_sha256`; los resúmenes del
  catálogo y del archivo separado coinciden.

El identificador declarado es FE7 USA, SHA-1
`c735fdbb9e8abe19e0c6a44708df19acc962e204`, coincidente con la referencia de
StanHash/fe7_us. No se recibió una ROM completa: el campo
`rom_bytes_verified` permanece en `false` en la entrega de muestra.

## Reconstrucción real

Las referencias observadas se distribuyen en una tabla de 28 bytes por entrada,
con base en `0xC96584`. Coincide con el acceso documentado por el desensamblado
de referencia. El intervalo de entradas observadas va del ID `0x001` al `0x0E4`:

| Componente | Campo | Entradas por ID | Bloques únicos |
| --- | --- | ---: | ---: |
| Retrato | +0 | 195 | 170 |
| Miniatura | +4 | 191 | 101 |
| Tarjeta de clase | +16 | 33 | 33 |
| Total | | 419 | 304 |

Se ensamblaron los retratos en 96 × 80 píxeles siguiendo la distribución estándar.
Las miniaturas se ordenaron en 32 × 32 y las tarjetas con 10 tiles de ancho.
No se identificaron personajes por nombre. La galería mantiene el ID de tabla,
los offsets y los hashes de cada componente.

Los 419 PNG fueron reabiertos y sus dimensiones se contrastaron con el catálogo.
Se verificó el inventario de hashes de los archivos generados. Se inspeccionó
visualmente una hoja de los primeros 40 retratos y una muestra de ocho retratos.
Las imágenes siguen en escala de gris porque las paletas originales no están en
el ZIP proporcionado. La lectura en color de la ROM real se realizará en el
equipo del usuario con el comando documentado.

## Pruebas del código

- Suite completa: 250 pruebas, 246 correctas y cuatro omitidas por necesitar
  Windows. La suite incluye las regresiones de paginación y reparación 0.5.1.
- Pruebas de retratos: 17 casos, incluidos ensamblado de regiones, color RGB555,
  transparencia, alias de componentes, lectura de paleta local, hashes de ROM y
  de datos comprimidos, puntero de tabla, paleta inválida, rutas protegidas,
  salida existente, planificación, CSP y escape de textos.
- La ruta de color se verifica con una ROM sintética: se comprueban los píxeles
  rojo, verde y azul de retrato, miniatura y tarjeta, y los bytes de la paleta
  exportada. No se utiliza otra ROM descargada de Internet.
- Ruff 0.14.0: análisis y formato correctos.
- mypy 1.18.2: correcto en 37 archivos de código.
- Wheel y sdist de 0.6.0 generados con `python -m build --no-isolation`.
- JavaScript de la galería comprobado con `node --check`.

El lanzador `Extraer-Retratos.ps1` tiene un caso de integración con rutas que
contienen espacios y una ROM sintética. Se incluye para Windows CI y no se
ejecutó en este entorno Linux. Tampoco se ejecutó un navegador gráfico para la
nueva galería; se validaron el HTML, JavaScript, CSP y las imágenes exportadas.

## Interpretación de los resultados

Los 304 bloques son una clasificación por vínculo con una tabla documentada,
con contraste estructural y ejemplos inspeccionados. No se han convertido las
3.767 entradas originales en decisiones manuales aceptadas. El resto del
inventario, las paletas no proporcionadas y las animaciones siguen pendientes.
El estado `partial` de la muestra indica ausencia de paletas reales; no hay
errores de reconstrucción de los 419 componentes.
