# Verificación de ArcanaCart 0.6.1

## Punto de partida

El cambio se construyó sobre el repositorio publicado en el commit
`fe26c622e98a82faa794838c58769fc01dd8cb5d` (ArcanaCart 0.6.0). Se conserva la
ejecución desde `C:\my_drive\Portafolio\arcanacart` y el Python explícito
`C:\FireEmblem\entorno-arcanacart\Scripts\python.exe`.

## Datos FE8 recibidos

Archivo: `arcanacart-fe8-base-validacion-20261022-220843.zip`.

- ROM declarada: FE8 USA, BE8E, 16 MiB.
- SHA-256: `638cda9d9b72657220fbf7e7a500cd3b64d9686c36e8a56fca69d26d13886f2f`.
- SHA-1: `c25b145e37456171ada4b0d440bf88a19f4d509f`.
- AIR: 4.998 candidatos LZ10; 4.400 bloques únicos; 17.934.637 bytes de payload.
- Comprobación ZIP CRC: correcta. Hashes de los 4.400 bloques: correctos.
- Tamaños de los bloques frente a los 4.998 registros del AIR: correctos.
- Escaneo declarado: 100 %, sin truncamiento. Este dato se conserva separado
  del progreso de identificación semántica.

La ejecución real sin ROM con 0.6.1 produjo 111 miniaturas y 57 tarjetas de
clase, cero errores, 126 bloques únicos del AIR vinculados y 115 componentes
pendientes según la tabla documentada. El estado fue `partial`, como
corresponde a la ausencia de la ROM y las paletas raw.

Los PNG generados tienen las dimensiones esperadas (32×32 y 80×72) y se
comprobaron sus hashes contra `faces-state.json`. Los otros 4.274 bloques del
AIR quedan fuera de esta clasificación por tabla de retratos; no se presentan
como recursos nuevos confirmados.

## Definición y formato raw: fuentes primarias

Se consultó `FireEmblemUniverse/fireemblem8u`, commit
`04d1edb163d14bd10777a065697e1a9f17be65f2`:

- [src/portrait_data.c](https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/src/portrait_data.c): 172 registros desde `0x8ACBE0`; campos no nulos para 115 retratos, 111 miniaturas y 57 tarjetas.
- [include/types.h](https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/include/types.h): `FaceData`, de 28 bytes, con campos gráficos en +0, +4 y +16 y paleta en +8.
- [src/face.c](https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/src/face.c): acceso por ID menos uno. La base virtual usada por el layout es `0x8ACBC4`; se omite su entrada cero.
- [src/bmlib.c](https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/src/bmlib.c): `UnpackRaw` omite cuatro bytes y resta esa cabecera del tamaño declarado.
- [scripts/compressor.py](https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/scripts/compressor.py): el contenedor `.fk` escribe tipo `00` y longitud de payload más cuatro.
- [scripts/dump_portrait.py](https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/scripts/dump_portrait.py): corroboración de campos y tratamiento diferenciado de tilesets, miniaturas y tarjetas.

Además, [ROMFE8U.cs de FEBuilderGBA](https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ROMFE8U.cs)
fija el puntero de la tabla en `0x5524` y el tamaño de entrada en 28 bytes.
No se incorpora código ni gráficos de esos repositorios al paquete entregado.

## Comprobaciones del código

- Suite completa: 256 pruebas; 252 correctas y 4 omitidas por requerir Windows.
- Ruff 0.14.0: análisis y formato correctos.
- Mypy 1.18.2: sin errores en 37 archivos fuente.
- Construcción wheel y sdist: correcta.
- Los casos raw usan ROMs sintéticas: colores conocidos, tamaño incluido en
  cabecera, límites, rango fuera de ROM, codificación no admitida, exportación
  por hash y separación entre conteos AIR y raw.
- Prueba de regresión con los recursos reales de FE7 y las paletas del ZIP
  coloreado recibido: los 419 componentes reproducen exactamente sus píxeles
  con el renderer 0.6.1.
- El JavaScript de la galería se comprueba con `node --check`.
- El parche se comprueba y aplica mediante `git am` en una copia limpia del
  commit base y en una copia con finales de línea CRLF, comparando después
  todos los archivos versionados contra la entrega.

## Límites de esta verificación

El ZIP de FE8 recibido no contiene la ROM, los retratos raw ni sus paletas.
La extracción completa en color de FE8 debe confirmarse en el equipo del
usuario. Los conteos 115/111/57 son los esperados de su definición documentada,
no una ejecución real en color efectuada aquí. No se ejecutó PowerShell nativo
en Windows en este entorno; los casos correspondientes quedan en la suite y
en la matriz de CI del proyecto.

Las variantes continúan necesitando definiciones propias validadas por hash.
No se han verificado sus tablas a partir de este paquete de la base FE8.
Las animaciones de boca y ojos, las otras tablas del juego y el análisis de
código son etapas posteriores.
