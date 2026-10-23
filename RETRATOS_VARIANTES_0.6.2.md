# Retratos de las 43 variantes · ArcanaCart 0.6.2

Continúa desde el diagnóstico completo de las ocho variantes FE7 y 35 variantes
FE8. Los planes, las 43 definiciones y el programa de extracción forman parte del
repositorio en `scripts/variantes`. Los AIR, las ROM y los bloques existentes se
leen desde las rutas registradas en el diagnóstico.

## Ejecutar en Windows

Desde la raíz del repositorio actualizado:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\scripts\windows\Extraer-Retratos-Variantes.ps1 `
    -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    -Abrir
```

Se reanuda por defecto el lote compatible más reciente de
`C:\FireEmblem\resultados`. Usa `-NuevaEjecucion` para crear otro lote, o
`-Resultados 'C:\otra\carpeta'` para cambiar el directorio de resultados.
`-Out` permite indicar una carpeta concreta; una carpeta existente necesita
un estado de reanudación compatible. `-Plan` selecciona otro archivo de planes.

El comando Python equivalente es:

```powershell
& 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    .\scripts\variantes\extraer_retratos_variantes.py `
    --repo . --resume-latest --abrir
```

Los programas utilizan la copia del paquete en el repositorio. Tras aplicar el
parche puedes ejecutarlos con el entorno existente, sin reinstalar dependencias.

## Alcance y evidencia

Se verificaron los 172 hashes de archivos y el estado completo de las 43
comparaciones del ZIP entregado por el usuario. La evidencia por tabla está en
`scripts/variantes/REVISION_TABLAS.md`; el detalle de cada variante se encuentra en
`revision-tablas.csv` y `planes.json`.

FE7 conserva la ubicación de su tabla y se incluyen los IDs 1–228
(`0x001–0x0E4`). FE8 reubica las tablas y se incluyen los IDs 1–254
(`0x001–0x0FE`), 82 IDs más que en la ventana anterior de la base. Cada ID puede
contener retrato, miniatura, tarjeta o estar vacío.

Son rangos acotados de exportación inferidos de los registros y de los bytes
siguientes. No certifican el tamaño total reservado de las tablas ni identifican
todos los recursos del juego. No se reconstruyen animaciones de ojos y boca.

Antes de exportar cada variante, el lote verifica el SHA-256 del AIR y de la ROM,
el código de acceso, el puntero, los bytes de la tabla, los componentes y las
paletas. Después, la extracción comprueba también los bloques existentes.
Si falla una validación, se conserva el informe y se continúa con las demás
variantes. Un bloque comprimido ausente del AIR requiere revisión.

## Totales previstos

| Grupo | Variantes | Retratos por variante | Miniaturas por variante | Tarjetas por variante | IDs vacíos previstos |
| --- | ---: | ---: | ---: | ---: | ---: |
| FE7 001–005 | 5 | 195 | 191 | 33 | 0 |
| FE7 006–008 | 3 | 195 | 193 | 33 | 0 |
| FE8 001 | 1 | 145 | 145 | 109 | 0 |
| FE8 002–009 | 8 | 142 | 142 | 112 | 0 |
| FE8 010–013 | 4 | 149 | 149 | 77 | 28 |
| FE8 014–035 | 22 | 149 | 149 | 105 | 0 |

Total previsto: **6.715 retratos, 6.689 miniaturas y 3.887 tarjetas = 17.291 PNG**.
Son componentes contados por ID, con repeticiones entre variantes; las muestras
de paletas no se suman a ese total. La ejecución local confirmará estos conteos.

Se conservan los 28 IDs vacíos de FE8 010–013. El resumen original de ArcanaCart
puede decir `partial` por estos huecos y se mantiene intacto. El lote solo marca
`completed` si se generaron todos los componentes previstos con paletas reales,
sin errores y con los huecos esperados.

La variante FE8 001 tiene además un registro vacío en `0x0FF`, fuera del rango
útil exportado. Las tarjetas de 3.200 bytes se renderizan como imágenes de 80×80.

## Resultados y reanudación

Se crea una carpeta `retratos-variantes-FECHA-HORA-ID` con `index.html`,
`resumen.csv`, `resumen.json` y carpetas cortas como `fe8-001`. El índice enlaza
las galerías. `resultado.json` contiene el veredicto sobre el rango;
`galeria/summary.json` conserva el resumen original del extractor.

Al terminar se genera un ZIP junto a esa carpeta, con los PNG, las paletas,
los componentes raw usados y los informes. Comparte ese ZIP y el registro de
consola para revisar el resultado. Los originales y Git se conservan intactos.

`Ctrl+C` guarda el progreso y prepara un ZIP parcial. Repite el comando para
reanudar: se comprueban los AIR, las ROM y todos los archivos exportados antes de
recuperar cada resultado. Un archivo alterado provoca un intento nuevo en otra
carpeta y se conserva el intento anterior. Cada ZIP recibe un nombre nuevo e
incluye los intentos activos del lote.

Tras un cierre forzado o un apagado puede quedar un bloqueo residual de
ArcanaCart; conserva el mensaje y confirma que el proceso terminó antes de
intervenir en él.

## Verificación

Las pruebas usan ROM sintéticas y la API real: componentes raw/LZ10, paletas
RGB555, tarjetas de 80×80, huecos, archivos alterados, reanudación, interrupciones
y llamada directa al programa desde otro directorio. Se validan también las 43
definiciones entregadas. La comprobación de todos los componentes de las ROM de
las variantes se realizará al ejecutar el lote en el equipo que las conserva.
