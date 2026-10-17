# Verificación de ArcanaCart 0.4.1

## Problema reproducido

El informe del usuario para Sacred Trilogy 2.1.3 Full contiene una ROM de
33.291.636 bytes y un escáner detenido en el offset 8.988, con 123 intentos,
65.477.116 bytes de cuota imputada y cero bloques. La extracción de tablas,
símbolos y Ghidra estaba omitida. Es un análisis parcial, no una extracción total.

Un fixture original de 1 MiB con 300 cabeceras LZ10 falsas de 2 MiB anunciados y
un bloque válido al final reproduce la causa: 0.4.0 se detiene en el offset 256,
después de 32 intentos. La regresión de 0.4.1 alcanza el bloque válido con una
cuota de salida de solo 4 bytes. No se incrementó la cuota para ocultar el fallo.

## Cambios verificados

- Medición estructural LZ10/RLE sin crear los bytes anunciados por candidatos corruptos.
- Contadores independientes de tokens de validación y bytes de salida.
- Priorización de cabeceras con coincidencias de referencias ROM; conservan estado heurístico.
- Paso lineal para el resto de offsets, con límites y progreso separados.
- Estado parcial y salida CLI 3 en scan, extract, pipeline y propagación al lote.
- Reutilización comprobada de bundles parciales sin errores de herramientas externas.
- Informes con estado, avance lineal y bytes clasificados en texto legible.
- Lanzador que usa las ROMs existentes y crea carpetas nuevas según versión y cuotas.

## Pruebas y comprobaciones

169 pruebas automatizadas correctas con el entorno de desarrollo completo,
incluida la validación independiente con jsonschema. Ruff, formato y mypy
correctos. Wheel y sdist construidos sin aislamiento ni descargas.

Las regresiones cubren declaraciones falsas grandes, errores tras producir
datos parciales, referencias solapadas, límites durante la expansión,
agotamiento de validación, métodos corruptos, bloques sin alineación,
referencias ROM espejo, fallback lineal, estados CLI, caché y propagación de
resultados parciales al lote. Las pruebas previas de ZIP, UPS e I/O se conservan.

## Comprobación local con las bases limpias aportadas

Se ejecutó el escáner con las cuotas por defecto y sin publicar datos extraídos:

| Base | Bloques candidatos | Salidas únicas | Bytes producidos | Referencias candidatas revisadas / inventariadas | Motivo de parada |
|---|---:|---:|---:|---:|---|
| FE7 USA | 1.000 | 785 | 394.058 | 1.012 / 3.981 | Límite de resultados |
| FE8 USA | 1.000 | 813 | 348.113 | 1.030 / 4.662 | Límite de resultados |

Los bloques se validan estructuralmente, pero no se declara que sus tipos o
significados estén identificados. Hay salidas repetidas. La fase lineal aún no
comenzó en estas dos mediciones: el progreso lineal es 0 % y el estado es parcial
por la cuota de 1.000 resultados. No son mediciones de cobertura total.

## Límites de la verificación

No se dispuso del binario UPS de Sacred Trilogy ni del resto de mods en este
entorno; el registro y el HTML del usuario sí se inspeccionaron. No se promete
un número de bloques concreto para las ROMs modificadas. PowerShell no estaba
disponible para ejecutar el lanzador en Windows: se revisó su flujo y las
opciones se contrastaron con el CLI probado. Ghidra y LT-Maker no se ejecutaron.

Las ROMs, parches de juegos y recursos de las bases permanecen fuera de la
entrega. Las definiciones de tablas por SHA-256 siguen siendo necesarias para
extraer personajes, clases u objetos; no se trasladan offsets originales a hacks.
