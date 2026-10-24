# Evidencia del rango de exportación

Origen: el ZIP completo de comparación de las 43 variantes.

SHA-256 del ZIP:
`b06ea5b773421fa1396c23eaa3cc0c290d21e2dda5c6f790640aa650ab030f35`.

Se comprobaron el CRC del ZIP, los 172 hashes de archivos registrados y el estado
completo de las 43 comparaciones. `revision-tablas.csv` detalla cada variante.

Los registros se interpretan con el formato FaceData de 28 bytes utilizado por
ArcanaCart 0.6.1. El puntero almacenado corresponde a la entrada virtual cero:
el ID 1 está 28 bytes después. El ID cero queda fuera de la extracción.

| Juego / grupo | Puntero literal | Tabla virtual cero | Último ID útil incluido | Primer registro incompatible observado |
| --- | --- | --- | --- | --- |
| FE7, ocho variantes | `0x6B30` | `0xC96584` | `0x0E4` | `0x0E5` |
| FE8 001 | `0x5524` | `0x1E662C0` | `0x0FE` | `0x100`; `0x0FF` está vacío |
| FE8 002–005 | `0x5524` | `0x1435468` | `0x0FE` | `0x0FF` |
| FE8 006–009 | `0x5524` | `0x144B790` | `0x0FE` | `0x0FF` |
| FE8 010–025 | `0x5524` | `0x124B4EC` | `0x0FE` | `0x0FF` |
| FE8 026–035 | `0x5524` | `0x1243B9C` | `0x0FE` | `0x0FF` |

Para localizar el cambio de estructura se revisaron los cinco campos de punteros,
las coordenadas y el campo final de cada registro. Los bytes posteriores tienen
patrones de índices pequeños y dejan de cumplir el formato. Esto permite proponer
un rango acotado; por sí solo no demuestra el tamaño de la reserva de memoria.

El lote requiere además que los bytes de cada rango coincidan con su hash guardado
y que todos sus componentes y paletas pasen la lectura puntual de la ROM local.
La ventana anterior de FE8 revisaba 172 IDs: este plan cubre 82 IDs adicionales,
que pueden contener retratos, miniaturas, tarjetas o entradas vacías.

Cada definición usa un SHA-256 de ROM distinto. `planes.json` conserva el hash del
AIR, la evidencia de acceso, los conteos previstos y los IDs vacíos. El tamaño
total reservado de las tablas sigue señalado como no confirmado.
