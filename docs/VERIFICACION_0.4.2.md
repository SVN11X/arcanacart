# Verificación de ArcanaCart 0.4.2

## Comprobaciones locales

- Suite de unittest con validador JSON Schema independiente instalado: 183
  pruebas descubiertas, 182 aprobadas y una omitida por requerir Windows.
- Ruff, comprobación de formato y mypy sobre todo el proyecto.
- Construcción de wheel y sdist sin aislamiento ni descargas.
- Instalación del wheel en un entorno nuevo sin acceso a índices de paquetes;
  pipeline LZ10 y comparación ejecutados fuera del checkout del código.
- CLI de comparación contra el `base-lz10.json` de 0.4.1 recibido: aceptado,
  4.400 salidas únicas coincidentes en comparación consigo mismo.

## Pipeline nativo sobre ROMs base

Con 64 MiB, 20.000 resultados, 500.000 intentos, paso 1 y `--compression lz10`:

| Base | Candidatos | Salidas únicas | Recorrido | Resultado |
|---|---:|---:|---:|---|
| FE7 USA | 4.274 | 3.767 | 100 % | completed |
| FE8 USA | 4.998 | 4.400 | 100 % | completed |

En ambos casos se verificó SHA-256 de la ROM antes y después. Una segunda llamada
con `--resume` obtuvo `cache_hit` y conservó la fecha del AIR. Los recursos se
exportaron por hash y los informes registraron que RLE estaba fuera del barrido.

## Regresiones cubiertas

Selección LZ10/RLE en API y CLI; identidad de caché por selección canónica;
rechazo de reanudación con formatos diferentes; conservación del JSON de lote;
aceptación de AIR y manifiestos anteriores; coincidencias aunque cambie el offset;
conteos por salida única; patrones uniformes 00/FF; datos vacíos y corruptos;
límites de escritura; dry-run; comparaciones parciales y código de salida 3.

`tests/test_windows_reanalysis.py` ejercita el lanzador PowerShell real en Windows
con dos ROMs sintéticas ya preparadas, comparación de base, rutas con espacios,
repetición por caché y conservación de resúmenes y entradas. Se ejecutará en el
job Windows de la matriz CI existente. Aquí se omite porque no hay PowerShell.

## Alcance de la evidencia del mod

El usuario ejecutó el API LZ10 de 0.4.1 sobre Sacred Trilogy 2.1.3 Full: 12.384
candidatos, 11.706 salidas únicas y recorrido del 100 % sin truncamiento. Sus
manifiestos registran 3.815 salidas coincidentes y 7.891 sin coincidencia frente
a FE8 USA. El SHA-256 de esa variante es
`a665ac03d3c74907ad762f16baafdf6a646acb2136e005debafa16f1db447ca1`.

No se dispone localmente del binario de esa variante para repetir aquí su
pipeline nativo. Las 45 ROMs, los RLE especulativos y los tipos semánticos no se
presentan como verificados por estas pruebas. Ghidra y una reconstrucción
compilable siguen fuera de la evidencia de esta corrección.
