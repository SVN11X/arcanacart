# Arquitectura

Se conservó `feunpack` como API de compatibilidad; sus lectores corregidos siguen
siendo la implementación de GBA/ZIP/UPS/LZ10. `arcanacart` agrega capas con trabajo
real. Se mantuvo un layout de paquetes en la raíz para no mover innecesariamente
el starter ni exigir configuración especial a las pruebas originales.

| Capa | Implementación | Contrato |
|---|---|---|
| Core | `core/io.py`, `core/memory.py` | Lecturas acotadas, publicación por archivo, memoria y punteros explícitos |
| Readers/formats | `feunpack/gba.py`, `archives.py`, `ups.py`, `manifest.py` | Binarios y manifiestos, sin interpretación de campañas |
| Compression | `compression/__init__.py`, `feunpack/lz10.py` | Decodificadores reemplazables y presupuestos de escaneo |
| Extractors | `extractors/layouts.py`, `extractors/__init__.py` | Layouts tipados y tablas ligadas a SHA-256 |
| Disassembly | `disassembly/ghidra.py`, script Java empaquetado | Integración opcional y síncrona; estado final obligatorio |
| Knowledge | `integrations/symbols.py`, referencias AIR | Símbolos, commit, evidencia y correlación de direcciones |
| Converters | Construcción de entidades en `schemas/__init__.py` | Bytes conocidos a registros AIR con campos desconocidos |
| Exporters | `exporters/__init__.py` | JSON/CSV/esquema, separados de cualquier motor de destino |
| Reporting | `reporting/__init__.py` | Métricas reales, escape HTML y límites explícitos |
| Orchestration | `pipeline.py`, `cli.py` | Reanudación, control de etapas, CLI nueva y alias anterior |
| Multi-variant batch | `batch.py`, `patchsets.py`, `scripts/windows/` | Importación, catálogo UPS, bases independientes, selección e índice común |

## Organización de ambos juegos

`batch-import` valida todas las entradas solicitadas antes de iniciar copias y
publica nombres estables en `private/inputs/`. Conserva fuentes, nombres y hashes.
`patchsets.py` cataloga el ZIP completo sin expandir su árbol; únicamente lee los
UPS seleccionados y les asigna nombres internos independientes del path original.

`batch.py` prepara las bases y aplica cada UPS directamente a la base de su juego.
El manifiesto de parche y el hash de la ROM controlan su reutilización. Cada trabajo
usa el pipeline existente; el namespace incluye versión, hash de ROM, tablas y
opciones de escaneo. Cambiar esas opciones produce otra carpeta de análisis.
El índice común registra fallos individuales y continúa con el otro juego.
La comparación binaria usa base/mod; la comparación AIR exige definiciones para ambos.
El lote no invoca Ghidra. Los lanzadores PowerShell solo componen argumentos para la CLI.

## Extensiones útiles

`Layout` implementa el protocolo `Extractor`: tamaño, fuente documental y
`parse(bytes) -> dict`. Los perfiles FE7 y FE8 tienen sus registros concretos;
no hay un cargador que ejecute código de plugins recibido desde una ROM.
Para añadir otro juego, incorpora y prueba un layout propio, registra su perfil
y proporciona definiciones ligadas a cada imagen. Para formatos variables,
implementa otro lector con validación de rangos antes de convertir a AIR.

El registro `DECODERS` tiene implementaciones LZ10 y RLE. Un nuevo formato necesita
vectores independientes y fallos truncados comprobados antes de registrarse.
Una firma por sí sola nunca clasifica un recurso.

## Reproducibilidad y estados

El fingerprint del pipeline incluye SHA-256 de ROM, versión del programa, perfil,
definición completa de tablas, límites, símbolos y configuración opcional Ghidra.
Una repetición con `--resume` comprueba hashes de los archivos generados antes de
reutilizarlos. Si falta un resultado o cambió su contenido, regenera el bundle.
Si cambió la entrada/configuración, exige una salida nueva. La reanudación Python
se realiza por bundle, no por cada tabla o byte; Ghidra tiene registros por función.
No se guardan marcas de tiempo variables en AIR para una entrada/configuración fija.

El estado se escribe antes del trabajo. Un fallo registra `failed`; una herramienta
opcional fallida registra `partial` y conserva el AIR disponible; una herramienta
opcional ausente queda `skipped`. Un bloqueo exclusivo impide escritores simultáneos.
Las escrituras son atómicas **por archivo**, no una transacción de toda la carpeta.
Un cierre abrupto puede dejar salidas parciales identificables mediante estado/hash.

## Semántica y confianza

`confirmed` se reserva para evidencia directa como una huella calculada o identidad
exacta; `structural` significa lectura compatible con el formato, `inferred` señala
interpretación no confirmada. `confidence` es una categoría, no una probabilidad.
IDs AIR deterministas incluyen juego, hash de variante, tipo, clave y offset;
la comparación entre variantes usa tipo y clave lógica, conservando ambos offsets.
Los inventarios iniciales pertenecen a definiciones de unidades/eventos, y no se
inventan a partir de una tabla de personajes.
