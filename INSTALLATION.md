# Instalación

Requiere Python 3.10 o posterior. Se verificó localmente con Python 3.12.14 en
Linux. Windows/WSL se contemplan en el código y la matriz CI; no se ejecutaron aquí.
Ghidra, JDK, referencias de descompilación y LT-Maker son independientes y opcionales.

## Windows PowerShell

Para FE7/FE8 y sus mods, sigue [EJECUTAR_FE7_FE8.md](EJECUTAR_FE7_FE8.md).
Los lanzadores ejecutan el código desde la carpeta descomprimida: solo requieren
Python 3.10+, sin pip ni activación. La instalación siguiente es opcional y sirve
para disponer de `arcanacart` como comando en PATH.

```powershell
cd arcanacart
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
arcanacart --version
arcanacart doctor --json
feunpack --help
```

Si PowerShell no permite activar el entorno, utiliza directamente
`.\.venv\Scripts\python.exe -m arcanacart doctor`.
No es necesario cambiar políticas del sistema. Los ejecutables se instalan en
la carpeta `Scripts` del entorno; activa ese entorno para encontrarlos.

## Linux y WSL

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m arcanacart doctor
```

La herramienta se ejecuta sin red tras instalarla. Para instalar desde código
sin red, prepara previamente setuptools `>=77,<85` y wheel `>=0.41,<1`, y usa:

```bash
python -m pip install --no-index --no-deps --no-build-isolation .
```

También puedes construir una rueda con `python -m build`, copiarla y ejecutar
`python -m pip install --no-index --no-deps arcanacart-0.4.1-py3-none-any.whl`.
El wheel incluye el esquema AIR y el exportador Java.

## Desarrollo

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m build
python -m pre_commit install
```

Las herramientas de desarrollo están fijadas en `pyproject.toml`; no se necesitan
para analizar ROMs. La suite completa usa únicamente archivos temporales y datos
sintéticos. La validación independiente con jsonschema se omite si no está instalado
el extra de desarrollo; el validador AIR de ejecución no necesita esa dependencia.

## Primer resultado reproducible

```bash
python examples/generate_synthetic.py --out workspace/demo
arcanacart pipeline --rom workspace/demo/synthetic.gba --profile fe8-us --tables workspace/demo/tables.json --out workspace/demo/analysis
```

No ejecutes el generador dos veces sobre los mismos archivos: protege contra
sobrescrituras. Para repetir el análisis utiliza `--resume`; para otra configuración,
usa un directorio de análisis nuevo. Si un proceso terminó abruptamente y dejó
`.arcanacart.lock`, comprueba que no haya ningún proceso trabajando antes de retirarlo.

## Parches de versiones anteriores

El parche de la entrega 0.3.0 se aplica a una copia Git del starter v0.2:

```bash
git status --short
git am /ruta/arcanacart-v0.3.0.patch
python -m pip install -e .
python -m unittest discover -s tests -v
```

Ese parche corresponde a los archivos del ZIP v0.2 adjunto al encargo inicial;
no incluye las funciones de lote de 0.4.0. Para esta entrega utiliza el ZIP completo.
Si tu repositorio ya cambió, revisa los conflictos; `git am --abort` cancela
la aplicación en curso. El ZIP completo permite empezar sin aplicar un parche.
