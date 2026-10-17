# Ejemplo sintético reproducible

`generate_synthetic.py` crea 4096 bytes originales con cabecera sintética, dos
personajes ficticios, dos clases, dos objetos (perfil FE8), dos bloques LZ10 con el
mismo contenido y un bloque RLE. No usa datos de una ROM comercial.

```bash
python examples/generate_synthetic.py --out workspace/demo
arcanacart pipeline --rom workspace/demo/synthetic.gba --profile fe8-us --tables workspace/demo/tables.json --out workspace/demo/analysis
arcanacart pipeline --rom workspace/demo/synthetic.gba --profile fe8-us --tables workspace/demo/tables.json --out workspace/demo/analysis --resume
```

Resultado observado en Linux/Python 3.12.14 con el wheel instalado fuera del repo:

| Métrica | Resultado |
|---|---|
| Estado | completed |
| Tamaño de entrada | 4096 bytes |
| Registros de tablas | 6 |
| Entidades AIR totales | 12 (Game, ROMVariant, cabecera, tablas y recursos) |
| Bloques comprimidos | 3 |
| Salidas únicas | 2 |
| Intentos de descompresión | 3 |
| Presupuesto usado por intentos | 14 bytes descomprimidos declarados |
| Bytes clasificados (unión de rangos) | 560 / 4096 |
| Bytes desconocidos | 3536 / 4096 |
| Reanudación sin cambios | cache_hit: true |

Esto no mide cobertura de FE8. El hash sintético es desconocido para las referencias
comerciales y sus tablas se marcan `inferred`. `synthetic_air.json` y
`synthetic_report.html` son resultados del ejemplo y pueden abrirse sin disponer de
una ROM. No se incluyen las imágenes `.gba` ni los blobs generados.
