# Consolidar los retratos existentes · ArcanaCart 0.6.3

Este paso organiza los PNG que ya se exportaron. Conserva una copia de cada
archivo por SHA-256 y registra cada aparición en un juego, variante e ID.
Reutiliza un lote completado de ArcanaCart 0.6.2; sus entradas permanecen intactas.

## Ejecutar

Desde la raíz del repositorio actualizado, indica la carpeta del lote completado:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\scripts\windows\Consolidar-Retratos.ps1 `
    -Lote 'C:\FireEmblem\resultados\retratos-variantes-20261023-110704-777bef' `
    -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    -CrearZip `
    -Abrir
```

`-Lote` también acepta el ZIP de resultados. El programa lo lee directamente,
sin descomprimir sus archivos en el disco. `-Out` permite indicar una carpeta
nueva; por defecto se crea `catalogo-retratos-FECHA-HORA-ID` junto a la entrada.
`-CrearZip` añade un ZIP portable y `-Abrir` abre la galería al terminar.

El comando Python equivalente es:

```powershell
& 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
    .\scripts\variantes\consolidar_retratos.py `
    --repo . `
    --input 'C:\FireEmblem\resultados\retratos-variantes-20261023-110704-777bef' `
    --crear-zip --abrir
```

Añade `--dry-run` para verificar las entradas y conocer los conteos sin escribir
el catálogo. La herramienta utiliza Python 3.10+ y la biblioteca estándar.

## Qué contiene la salida

- `index.html`: galería local con 36 imágenes por página; filtros por juego,
  tipo y variante; búsqueda por ID, nombre de variante o hash. Al desplegar una
  imagen aparecen todas las variantes e IDs que la usan.
- `imagenes`: un PNG por SHA-256, conservado exactamente como se exportó.
- `paletas`: las paletas RGB555 originales, una por SHA-256.
- `catalogo.json`: imágenes con todos sus orígenes, incluyendo ROM, AIR, offset,
  hash del bloque y hash de la paleta.
- `imagenes.csv`: una fila por PNG distinto.
- `ocurrencias.csv`: una fila por aparición en un juego, variante e ID.
- `resumen.json` y `catalog-state.json`: conteos y hashes de los archivos publicados.

Las imágenes transparentes se guardan y se pueden mostrar con el filtro; la
galería las oculta inicialmente. Los CSV usan UTF-8 con BOM para abrirse en Excel.
La galería funciona abriendo el HTML y conserva sus recursos en carpetas locales.

## Conteos del lote revisado

El lote de 43 variantes contiene 17.291 apariciones de componentes. Tras reunir
los PNG idénticos se esperan 938 archivos distintos: **934 visibles y cuatro
totalmente transparentes**, con 537 paletas distintas. Las 219 apariciones de
imágenes transparentes permanecen registradas. Se evitan 16.353 copias de PNG.

La igualdad se refiere a los bytes del PNG; cada imagen conserva su color y sus
orígenes. Distintas paletas o bloques pueden producir el mismo PNG. Un diseño
parecido, un nombre de personaje compartido o un cambio de color no bastan para
reunir dos archivos. Los nombres de personajes siguen pendientes de revisión.

## Integridad y conservación

La consolidación requiere un lote marcado como completo. Verifica el enlace de
hashes entre el estado del lote, los resultados por variante, la validación de
tabla, los catálogos, los PNG y las paletas. Comprueba también la estructura y el
CRC de los PNG RGBA8 generados por ArcanaCart y determina su transparencia por
el canal alfa.

Las cuatro variantes FE8 con 28 IDs vacíos previstos se aceptan cuando todos los
componentes del rango están generados y validados. Su resumen original `partial`
se conserva dentro del lote original y no se interpreta como un fallo nuevo.

Los archivos de salida se preparan en una carpeta temporal y se publican al
terminar. Una entrada inválida o una interrupción durante esa preparación no
publica un catálogo incompleto. Los archivos existentes y los ZIP previos se
conservan; cada nueva ejecución utiliza otra carpeta de salida.

Las ROM, los AIR, los bloques y las galerías originales permanecen en sus rutas.
Este paso no ejecuta el escáner ni reconstruye los retratos. Los bloques raw y
comprimidos siguen en los análisis originales. La extracción de fondos, sprites
y animaciones corresponde a etapas posteriores.

La actualización mantiene los planes de extracción existentes sin alterar su
hash. El lanzador del lote anterior acepta correcciones compatibles 0.6.x y
puede seguir recuperando los resultados verificados.
