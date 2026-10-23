# Verificación de ArcanaCart 0.5.1

Esta corrección parte de los archivos del ZIP 0.5.0 entregado anteriormente.
No se utilizaron ROMs ni los bloques privados del usuario. Las pruebas emplean
datos sintéticos, incluido un bloque de exactamente 1.114.112 bytes.

## Comprobaciones

- Suite completa: 233 pruebas, 230 correctas y 3 omitidas por requerir Windows.
- `python -m ruff check .` y `python -m ruff format --check .`: correctos con Ruff 0.14.0.
- `python -m mypy`: correcto, 35 archivos, mypy 1.18.2.
- Distribuciones wheel y sdist de 0.5.1 generadas con `python -m build --no-isolation`.
- Sintaxis del JavaScript de la galería comprobada con `node --check`.
- Integración real entre versiones: ejecución del código original 0.5.0 sobre
  el bloque sintético grande y otro pequeño; 1 error por tamaño. Reparación
  posterior con el CLI 0.5.1: 0 errores, 17 páginas nuevas y 18 PNG totales.
  Se conservaron exactamente el hash y la fecha de modificación del PNG previo.
- Regresión de tamaño real: se verifican los CRC y las dimensiones de los PNG,
  el primer píxel de cada uno de los 34.816 tiles y la cobertura consecutiva de
  los bytes. Las 17 páginas de 4 bpp y 16 tiles de ancho miden 128 × 1024.
- Planificación a 4/8 bpp y anchos de 1, 7, 16 y 128 tiles: todos los bytes
  cubiertos, ningún tile dividido, ninguna página supera el límite de imagen.
- Presupuestos insuficientes: no se publica una fracción del bloque y se puede
  reintentar la reparación con límites mayores.
- Se conservan errores de otras causas, las recetas y el estado de revisión.
  Repetir una reparación terminada no vuelve a leer los bloques ni reescribe
  sus metadatos.
- Fallo al crear una página: se retiran las páginas recién creadas de ese bloque.
  Fallo al publicar metadatos: se restablecen todos los metadatos anteriores y
  se retiran solo los PNG de esa transacción. Una publicación interrumpida con
  diario válido se recupera antes de reintentar.
- Cambios en el AIR, catálogo o recetas: se rechaza la mezcla de versiones.

## Límites de la verificación

El lanzador PowerShell tiene una prueba de integración para Windows que utiliza
un CSV y archivos temporales con espacios en sus rutas. No se ejecutó en este
entorno Linux; queda incluida para la matriz Windows de CI, junto con las dos
pruebas de lanzadores que ya existían. No se afirma haber ejecutado las 45 ROMs
reales ni revisado visualmente su contenido. La galería se valida mediante su
JavaScript, CSP y datos de salida; no se ejecutó aquí un navegador gráfico.

Los PNG indican una interpretación posible. Ninguna prueba sintética identifica
por sí sola recursos concretos de Fire Emblem.
