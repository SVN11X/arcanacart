# Formatos de entrada, extracción e intercambio

## Cabecera y variantes

Se leen cabeceras GBA de al menos `0xC0` bytes, título, Game Code, Maker Code,
versión `0xBC`, constante `0x96`, checksum, bytes reservados y región orientativa.
SHA-1/SHA-256/CRC32 se calculan sobre toda la imagen. El logo y la firma legal de
una ROM no se autentican. Una cabecera válida no demuestra originalidad.

Se aceptan hasta 64 MiB de archivo para inspeccionar imágenes expandidas;
el mapa ROM ordinario representa 32 MiB. Los bytes superiores no se inventan
como direcciones de cartucho estándar. Los bancos ROM de espera `08–09`, `0A–0B`,
`0C–0D` resuelven el mismo offset dentro de su ventana de 32 MiB. No se repite una
imagen corta para fabricar bytes inexistentes. Dispositivos especiales/EEPROM no
se modelan como memoria ordinaria.

ZIP admite selección exacta `--member`; solo se leen bytes de la ROM seleccionada.
Las rutas internas no se usan como destinos. ZIP64, multidisco, ROM cifrada,
ROM symlink y nombres ROM peligrosos no se admiten. Los miembros ajenos no se
extraen ni ejecutan; nombres ROM duplicados o nombres ambiguos se rechazan.

## Compresión

| Formato | Firma | Capacidad |
|---|---|---|
| BIOS LZ77/LZ10 | `0x10` + tamaño LE de 24 bits | Literales, referencias solapadas, límites y truncamientos |
| BIOS RLE | `0x30` + tamaño LE de 24 bits | Paquetes literales y repeticiones, límites y truncamientos |
| BIOS Huffman | `0x24`/`0x28` | Investigado, todavía sin decodificador registrado |
| Huffman de texto Fire Emblem | Árbol/tablas propios | Pendiente; no equivale al formato BIOS por su nombre |
| LZ11, filtros delta, audio y compresiones personalizadas | Diversas | No implementados |

El escaneo usa paso 1 por defecto y excluye la cabecera de cartucho cuando su
constante/checksum son válidos. Cuenta intentos, rechazos, salida única y corte por
presupuesto. Los tamaños de intentos fallidos también consumen presupuesto.
El scanner se detiene al alcanzar sus límites y señala `truncated` y `stop_reason`;
no extrapola cuántos bloques podrían quedar. Un contenido repetido en offsets
distintos conserva ambas evidencias y se almacena una sola vez por hash.
La búsqueda todavía decodifica cada candidato una vez para validarlo; el caché
persistente evita repetir el bundle completo cuando nada cambia.

Cada candidato incluye dirección/offset, método, bytes consumidos, tamaño de salida,
SHA-256 comprimido y descomprimido, evidencia, referencias y tipo desconocido.
La descompresión correcta es validación **estructural**, no identidad de gráfico/mapa.
Las referencias solo buscan valores de 32 bits alineados hacia destinos elegidos;
no establecen por sí solas que el programa utilice esos bytes como punteros.

## Tablas FE: configuración obligatoria por variante

Los layouts se contrastaron con los headers de los commits registrados en
`docs/SOURCES.md`. No se incorporaron datos de personajes ni contenido de campañas.
Están implementados:

- FE7: `Character` (PInfo, `0x34` bytes), `Class` (JInfo, `0x54`).
- FE8: `Character` (`0x34`), `Class` (`0x54`), `Item` (`0x24`).

Bases/crecimientos, límites, promociones simples, competencias, flags y punteros
se leen con signo y endianess documentados. Los textos son IDs, no diálogos
decodificados. Objetos conservan rango codificado; valores especiales quedan sin
min/max. Los flags y efectos se conservan como números; no se reconstruye su lógica.
FE8 tiene promociones bifurcadas en tablas adicionales que aún no se interpretan.

Ejemplo **solo sintético**, generado por `examples/generate_synthetic.py`:

```json
{
  "profile": "fe8-us",
  "rom_sha256": "REEMPLAZAR_POR_EL_SHA256_COMPLETO_DE_LA_IMAGEN",
  "evidence": ["Mapa de símbolos local, commit y validación manual del rango"],
  "tables": [
    {"kind": "Character", "offset": 512, "count": 2, "first_id": 1},
    {"kind": "Class", "offset": 768, "count": 2, "first_id": 1},
    {"kind": "Item", "offset": 1280, "count": 2, "first_id": 1}
  ]
}
```

`offset` es offset de archivo decimal en JSON, no dirección `0x08...`.
`first_id` es la clave de slot para comparar variantes. Debe investigarse junto con
`count`, incluyendo o excluyendo los registros vacíos de forma coherente. IDs
internos inconsistentes se notifican, sin corregirlos en silencio. Una definición
aportada para una ROM desconocida produce registros `inferred`, incluso si pasa
los controles estructurales. No se asegura que un hack conserve estos layouts.
Máximo de protección: 50.000 registros por definición, 256 tablas; no es una medida
de cuántos registros tenga ningún juego. Un mismo tipo aparece como máximo una vez.

## AIR 1.0.0

Esquema distribuido: `arcanacart/schemas/air.schema.json`, JSON Schema 2020-12.
El validador propio aplica el vocabulario utilizado por ese esquema y comprueba
IDs únicos, referencias existentes, procedencia, límites y valores JSON finitos.
No es un validador universal de esquemas arbitrarios. Una prueba con jsonschema
valida independientemente el documento y el esquema cuando está instalado.

AIR admite Game, ROMVariant, Character, Class, Item, Weapon, Skill, Chapter, Map,
Terrain, Unit, Event, Dialogue, Animation, Asset, Function y Reference. Admitir un
tipo en el esquema **no significa** que ya exista un parser para él. Los emisores
actuales generan Game, ROMVariant, Asset y los tres tipos de tabla disponibles.

Todos los registros incluyen ID estable, juego/perfil, variante SHA-256, versión,
dirección/offset opcionales, tamaño, parser, versión de extractor, hash, evidencia,
referencias, validación/confianza, datos y lista de campos desconocidos. Los hashes
de entidades con rango corresponden a sus bytes fuente; el hash de salida de una
compresión va separado. `null` y `unknown_fields` evitan valores inventados.

JSON conserva la estructura; CSV guarda una entidad por fila con `data_json` y
protege campos de texto frente a fórmulas de hojas de cálculo. HTML escapa entradas,
funciona localmente sin scripts/CDNs e incluye una política CSP restrictiva.
Los datos son privados por defecto; una exportación no constituye autorización
para redistribuir contenido de terceros.

## Interpretación gráfica 0.5.0

La descompresión sigue separada de la identificación. `interpret` verifica los
blobs existentes y conserva hipótesis no exclusivas. Su catálogo registra cada
hash único con todos sus offsets. Las decisiones manuales quedan en recetas por
ROM/hash; no se promueven tipos AIR por tamaño ni por generar un PNG.

Se renderizan tiles 4/8 bpp, paletas RGB555 y mapas BG de texto con flips/bancos,
en filas o screenblocks de hardware. Los mapas de metatiles FE solo se detectan
como hipótesis; requieren una definición de metatiles para renderizarlos.
`--palette` admite archivos RGB555 externos, incluido contenido extraído sin
compresión mediante `dump`. Sus hashes y copias quedan en el bundle de revisión.

Las definiciones de tablas admiten opcionalmente `layouts`. El formato, validaciones
y ejemplos sintéticos figuran en `CONTINUAR_0.5.0.md`. No hay un layout FE7 Item
incorporado sin verificar: se proporciona uno documentado con ese mecanismo.
