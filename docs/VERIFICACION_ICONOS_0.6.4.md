# Verificación de la extracción de iconos 0.6.4

Base recibida: ZIP local del commit `3866b32c504204c08754c1ab8a7473014c222c35`.
No se utilizó el estado público de GitHub como sustituto del código local.

Entorno: Linux, Python 3.12.14. Los recursos y ROM de prueba son sintéticos.

## Pruebas ejecutadas

129 pruebas descubiertas: 127 aprobadas, cero fallos, cero errores y dos
omitidas por dependencias opcionales o plataforma:

- Validador JSON Schema externo: no está instalada la dependencia de desarrollo.
- Lanzador de retratos existente: requiere PowerShell en Windows.

Módulos ejecutados:

```text
test_air_extraction.py
test_compression_framework.py
test_faces.py
test_interpretation.py
test_resource_workflow.py
test_table_definitions.py
test_item_icons.py
```

Las 21 pruebas nuevas de `test_item_icons.py` verifican:

- El orden top-left, top-right, bottom-left, bottom-right de los cuatro tiles
  y sus píxeles rojo, verde, azul y blanco esperados de forma independiente.
- Transparencia por índice cero; conservación de la imagen y su ID.
- Deduplicación de archivos sin perder los dos IDs ni sus offsets de origen.
- Coincidencia exacta de bytes raw, paleta y hashes de los artefactos.
- CSV y JSON; definición resuelta; preservación de las entradas.
- Rangos inclusivos y definiciones cuyo primer ID no es cero.
- Planificación sin escrituras y rechazo de salidas con contenido.
- Rechazo de ROM modificada, punteros nulos/RAM/fuera de rango, banco
  reubicado, paleta contradictoria, dimensiones inválidas e índices excesivos.
- Rechazo de extracción automática basada sólo en el Game Code.
- AIR de otra ROM y conservación del hash del AIR con CRLF sobre bytes exactos.
- Inventario de candidatos sin reclasificación ni verificación ficticia de blobs.
- Datos embebidos y CSP de la galería; CLI con éxito, planificación y error.

La prueba completa `test_pipeline_cli.py` no se ejecutó porque este snapshot
parcial no incluye `tests/test_ups.py`, del que importa un generador de
fixtures. La ruta CLI nueva se prueba directamente en `test_item_icons.py`.
No se declara que haya pasado la suite completa del repositorio.

## Alcance práctico

Se comprueba adicionalmente que el parche se aplica con `git am` sobre una
copia del snapshot recibido, con `core.autocrlf=false` y `true`, preservando
el contenido de los archivos y ejecutando las 21 pruebas nuevas desde la
copia con el parche aplicado.

No se ejecutó el lanzador nuevo en PowerShell ni se renderizó el HTML en un
navegador real. Tampoco se extrajeron en este entorno las bases comerciales
FE7/FE8 ni las variantes. El módulo incluye comprobaciones locales de hashes,
punteros y límites que deben pasar antes de exportar esas bases en Windows.

Las fuentes fijadas por commit están registradas en
`ICON_SOURCE_EVIDENCE_0.6.4.json`. Sus datos documentan 173 posiciones para FE7
y 224 para FE8; esos conteos son el alcance previsto, no un resultado de
ejecución sobre ROM reales en esta preparación.
