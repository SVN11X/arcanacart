# Verificación de ArcanaCart 0.5.0

Base: contenido del ZIP `arcanacart.zip` entregado el 18 de octubre de 2026.
Versión declarada en Python y pyproject: 0.4.2. Su referencia `.git` indicaba
`e18e3545a5ea8efe90dc7ce35d7b630a449c3986`. Para preparar el parche se creó un
snapshot independiente del contenido, sin reutilizar configuración/hooks del ZIP.

## Comprobaciones ejecutadas

| Comprobación | Resultado |
|---|---|
| Suite previa, antes de modificar | 183 casos; 2 omitidos inicialmente (Windows y validador opcional no instalado) |
| Suite de la versión nueva, con dependencias dev | 219 casos: 217 aprobados, 2 omitidos por requerir Windows |
| `ruff check .` | Correcto |
| `ruff format --check .` | Correcto |
| `mypy` | Correcto; 34 archivos de paquetes |
| JSON Schema independiente con jsonschema | Incluido en la suite; correcto |
| `python -m build` | sdist y wheel 0.5.0 construidos |
| Wheel instalado en carpeta separada, sin dependencias | `doctor` correcto; nuevos módulos y Java empaquetados |
| `node --check` del script de galería | Correcto |
| Demo gráfica completa | 5 candidatos, 4 bloques únicos, 3 PNG, sin errores; interpret no vuelve a escanear |
| Aplicación de parche | Comprobación contra snapshot 0.4.2 y comparación byte a byte de archivos de entrega |

Los comandos de verificación pueden repetirse con `.[dev]`. Los renderizadores
de producción utilizan exclusivamente la biblioteca estándar; instalar las
herramientas dev no introduce dependencias de ejecución para el usuario.

## Cobertura de los casos nuevos

- RGB555 con vectores de rojo/verde/azul y bit alto no utilizado.
- Orden de nibbles 4bpp, 8bpp, transparencia y relleno de hojas incompletas.
- PNG con CRC y flujo de píxeles descomprimido verificado independientemente.
- Mapas BG con bancos, giros horizontal/vertical y distribución screenblocks.
- Reutilización de manifiestos, offsets duplicados, hashes/tamaños y entradas
  faltantes/alteradas; límites y estado parcial sin perder registros de catálogo.
- Recetas con evidencia, ROM equivocada, formatos inválidos, paletas externas
  con hash y JSON UTF-8 con BOM (común en herramientas Windows).
- Escape de texto y CSP por hash, incluidos `</script>` y tokens en notas.
- Comparación por contenido sin promoción automática a recurso nuevo.
- Definiciones SHA-256, offsets/símbolos, campos firmados, layouts declarativos,
  solapamientos, rangos y arrays de punteros.
- Exports de código con hashes alterados, otra ROM, rutas peligrosas, huecos de
  instrucciones, exports antiguos y conflictos con datos.

## Límites de esta entrega

El ZIP de entrada no incluía `air.json`, `resources/`, ROMs ni la instalación de
Ghidra. No se declara validación gráfica o semántica de los 45 juegos reales.
La suite verifica contratos simulados del índice/exportación, pero no compila
ni ejecuta Java dentro de una instalación Ghidra real.

Los dos casos Windows ejecutan los scripts PowerShell sobre fixtures cuando
corren en CI Windows; en este entorno Linux quedaron omitidos. El script de
interpretación conserva compatibilidad prevista con Windows PowerShell 5.1 y 7.

No se pudo instalar/ejecutar Chromium para una comprobación visual interactiva.
Se comprobó la sintaxis JavaScript, el CSP y los contenidos generados; quedan
pendientes la comprobación visual en Edge/Chrome y la ejecución de PowerShell
en el equipo del usuario. Los límites y resultados sintéticos no se extrapolan
a cobertura semántica de FE7, FE8 o sus variantes.
