# ArcanaCart 0.4.2

La guía [REANALISIS_0.4.2.md](REANALISIS_0.4.2.md) integra el flujo comprobado en
terminal: selección LZ10/RLE, AIR e informes con alcance explícito y comparación
de candidatos por contenido. Un escaneo interrumpido se informa como `partial`
con código 3. Un barrido finalizado se refiere a los formatos y límites elegidos.

Herramienta **local y offline** para investigar archivos GBA: validación binaria,
ZIP seguro, parches UPS1, mapa de memoria, recursos BIOS LZ10/RLE y extracción
estructurada de tablas documentadas. Python **3.10+**, sin dependencias de ejecución.
Incluye el alias `feunpack` y los siete comandos del starter v0.2.

El proyecto contiene código funcional y fixtures sintéticos. No recupera de forma
automática el código C original ni una campaña completa. Los resultados señalan
qué se leyó, qué se infirió y qué queda desconocido.

## FE7, FE8 y sus mods en Windows

La guía [EJECUTAR_FE7_FE8.md](EJECUTAR_FE7_FE8.md) contiene los cuatro nombres
formales, estructura, selección de versiones y solución de errores.
Descomprime el proyecto, abre PowerShell en su carpeta y, con Python 3.10+ instalado:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\scripts\windows\Prepare-Inputs.ps1 -PickFiles
& .\scripts\windows\Run-ArcanaCart.ps1 -OpenReport
```

El primer comando permite elegir los cuatro ZIP originales y crea copias con sus
nombres canónicos. El segundo analiza FE7 y FE8 base, FE7 Remastered X QoL Final
Paladin Special de 2025-10-26 y Sacred Trilogy 2.1.3 Full. Cada mod se aplica a su
base limpia, con verificación de CRC. `-AllVariants` procesa todos los UPS encontrados.
No requiere instalar el paquete con pip ni activar un entorno.

Para las ROMs **ya preparadas** en `C:\FireEmblem`, usa directamente:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\scripts\windows\Reanalizar-Resultados.ps1 -Datos 'C:\FireEmblem' -Compression lz10 -CompareBase -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe'
```

Este comando analiza las `.gba` existentes. La organización previa de los ZIP es
independiente. Cada ejecución guarda su propio resumen y cada configuración usa
una carpeta de análisis distinta.

El índice queda en `workspace/fire-emblem/index.html`. El lote reúne análisis,
aplicación de parches e informes; para jugar, abre la `.gba` preparada en tu emulador.
No se incluye un emulador ni se ejecuta el juego dentro de ArcanaCart.

## Inicio rápido

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
arcanacart doctor
python examples/generate_synthetic.py --out workspace/demo
arcanacart pipeline --rom workspace/demo/synthetic.gba --profile fe8-us --tables workspace/demo/tables.json --out workspace/demo/analysis
arcanacart pipeline --rom workspace/demo/synthetic.gba --profile fe8-us --tables workspace/demo/tables.json --out workspace/demo/analysis --resume
```

Abre `workspace/demo/analysis/report.html` en el navegador. Incluye AIR JSON,
CSV, informe Markdown, recursos únicos por hash y estado del pipeline. El ejemplo
es contenido original sintético y **no es un videojuego jugable**.

En Linux/WSL activa el entorno con `source .venv/bin/activate`.
Sin instalación puedes usar `python -m arcanacart` desde la raíz; la instalación
es necesaria para tener los ejecutables en PATH. La instalación con pip puede
obtener herramientas de build; ningún comando de análisis descarga nada.

## Analizar tus copias locales

```powershell
arcanacart inspect "C:\FE\Fire Emblem (U) [!].zip"
arcanacart prepare --rom "C:\FE\Fire Emblem (U) [!].zip" --out workspace/fe7/baserom.gba
arcanacart pipeline --rom workspace/fe7/baserom.gba --profile fe7-us --out workspace/fe7/analysis
arcanacart patch --rom workspace/fe7/baserom.gba --patch private/mod.ups --out workspace/fe7/mod.gba --direction forward
arcanacart compare --left workspace/fe7/baserom.gba --right workspace/fe7/mod.gba --out workspace/fe7/diff.json
```

Sin `--tables`, el pipeline inspecciona, busca recursos y genera informes;
**omite la extracción de personajes/clases/objetos**, dejando una razón explícita.
`--tables` necesita ubicaciones y conteos investigados para **ese SHA-256**.
No se distribuyen offsets vanilla sin verificación ni se trasladan a hacks.
El ejemplo sintético muestra exactamente cómo construir esa definición.

| Capacidad | Estado de esta versión |
|---|---|
| Identidad por SHA-1 exacto FE7U/FE8U; SHA-256/CRC32/cabecera | Implementada; hashes publicados contrastados; fixtures probados |
| ZIP, UPS reversible/dirección explícita, protección de originales | Implementados y probados con entradas corruptas y fallos de escritura |
| FE7 + FE8 + paquetes de mods | Importación con nombres canónicos, catálogo, selección, lote, comparación y reanudación; UPS de prueba verificados |
| ROM/RAM/VRAM/paletas/OAM/IO, referencias seleccionadas | Implementados y probados |
| LZ10 y RLE BIOS; bloques sin alineación; cuotas y hashes | Implementados; descubrimiento heurístico |
| Personajes/clases FE7 y FE8; objetos FE8 | Parsers implementados; definiciones locales por hash; pruebas sintéticas |
| AIR 1.0, JSON, CSV, Markdown y HTML local | Implementados y validados |
| Símbolos locales, commit y comparación de campos AIR | Implementados; coincidencia de dirección es evidencia inferida |
| Ghidra ARMv4T Headless y exportador Java incremental | Integración experimental; no ejecutada con Ghidra real en este entorno |
| Huffman propio de FE, capítulos, eventos, gráficos, audio | Pendientes; no se simulan extracciones |
| Campaña LT-Maker `.ltproj` y multijugador | No implementados |

## Identidad de referencia

| Perfil | Game Code orientativo | SHA-1 exacto | Referencia |
|---|---|---|---|
| `fe7-us` | AE7E | `c735fdbb9e8abe19e0c6a44708df19acc962e204` | [StanHash/fe7_us](https://github.com/StanHash/fe7_us) |
| `fe8-us` | BE8E | `c25b145e37456171ada4b0d440bf88a19f4d509f` | [FireEmblemUniverse/fireemblem8u](https://github.com/FireEmblemUniverse/fireemblem8u) |

Cabecera, título, extensión y Game Code coincidentes **no** confirman originalidad.
Regiones no verificadas e imágenes modificadas funcionan en modo genérico.
Un perfil explícito selecciona un layout; no convierte una variante en original.

## Pruebas y documentación

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build
```

Lee [INSTALLATION.md](INSTALLATION.md), [CLI_REFERENCE.md](CLI_REFERENCE.md),
[EXTRACTION_FORMATS.md](EXTRACTION_FORMATS.md) y [GHIDRA_INTEGRATION.md](GHIDRA_INTEGRATION.md).
La auditoría previa está en [docs/AUDIT_v0.2.md](docs/AUDIT_v0.2.md) y la evidencia
final en [docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md).
La verificación específica de esta corrección está en
[docs/VERIFICACION_0.4.2.md](docs/VERIFICACION_0.4.2.md).

No hay telemetría, APIs remotas ni subida de ROMs. Conserva entradas y resultados
privados fuera de Git. MIT cubre este código, no los contenidos analizados.
