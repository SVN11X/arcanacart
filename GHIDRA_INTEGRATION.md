# Integración Ghidra — experimental en 0.3.0

El núcleo funciona sin Ghidra. Se implementaron detección local, construcción de
argumentos, ejecución síncrona y exportador Java. Se probaron contratos del wrapper
con procesos simulados; **no se instaló ni ejecutó Ghidra y no se compiló este script
contra una distribución real en el entorno de entrega**. Esa validación sigue pendiente.

## Preparación externa

1. Instala [Ghidra](https://github.com/NationalSecurityAgency/ghidra) y el JDK que
   exige esa distribución.
2. Instala [gba-ghidra-loader](https://github.com/pudii/gba-ghidra-loader) para la
   misma versión de Ghidra y reinicia el programa. Upstream distingue Ghidra 12 de
   versiones anteriores; no mezcles releases por su nombre.
3. Conserva `extension.properties` de la extensión instalada. La carpeta indicada
   por `--loader-dir` debe corresponder a esa instalación, no a un ZIP descargado.
4. Prepara una ROM `.gba`; el wrapper no importa ZIPs mediante cargadores genéricos.

ArcanaCart no descarga Java, extensiones ni repositorios. Detecta versión en
`Ghidra/application.properties`, launcher, Java accesible y lenguaje instalado
`ARM:LE:32:v4t`. Compara la versión de la extensión aportada. Este diagnóstico no
asegura compatibilidad de Java ni que el launcher vea la extensión; la ejecución
real debe confirmarlo. `runtime_verified` permanece false en el diagnóstico.

```powershell
arcanacart doctor --ghidra-home "C:\Tools\ghidra" --loader-dir "C:\Tools\extensions\gba"
arcanacart disasm --rom workspace/fe8/baserom.gba --out workspace/fe8/ghidra --ghidra-home "C:\Tools\ghidra" --loader-dir "C:\Tools\extensions\gba" --dry-run
arcanacart disasm --rom workspace/fe8/baserom.gba --out workspace/fe8/ghidra --ghidra-home "C:\Tools\ghidra" --loader-dir "C:\Tools\extensions\gba"
```

También se admite `GHIDRA_HOME`. En Windows se rechazan rutas con metacaracteres
interpretables por el launcher `.bat`; usa nombres sencillos o WSL. El wrapper
construye una lista de argumentos y no usa `shell=True`.

## Contrato de importación y exportación

Se usa `support/analyzeHeadless`, `-import`, `-loader GBALoader`, lenguaje ARMv4T,
`-scriptPath` y `-postScript ArcanaExport.java`. No se usa ARMv7 ni `-overwrite`.
La ROM SHA-256 determina el nombre del proyecto local. Para reanudar se utiliza
`-process` sobre el nombre de programa importado. Conserva ese nombre y proyecto.

El postscript verifica SHA-256, lenguaje little-endian ARMv4T, ROM inicializada en
`0x08000000` y regiones EWRAM/IWRAM. Ghidra decide y almacena contexto ARM/Thumb;
el exportador registra `TMode`. No presupone que todas las instrucciones son Thumb.

`--start`/`--end` filtran **funciones por dirección de entrada para exportación**,
no restringen el alcance de Auto Analysis. El rango es semiabierto, dentro de
`0x08000000..0x0A000000`. No hay análisis selectivo de código por rango implementado.
`--timeout` limita Auto Analysis; cada intento de descompilar tiene 30 segundos.

El script consulta `analysisTimeoutOccurred()` de `HeadlessScript`, contrastado con
la fuente de la API. Algunas instrucciones de Headless en upstream mencionan
nombres anteriores: no se asumió que un ejemplo de documentación bastara.

## Resultados incrementales

En `functions/`:

- `<address>.s`: instrucciones recuperadas; no código ensamblador fuente original.
- `<address>.c`: pseudocódigo aproximado, marcado como tal.
- `<address>.json`: nombre, dirección, referencias entrantes, llamadas, tamaño,
  contexto, hashes de exportación, versión Ghidra y estado de descompilación.
- `summary.json`: intentadas, omitidas por caché, fallidas, restantes, timeout y estado.
- `index.html`: enlaces locales a cada función; sin servicios externos.

`--batch 0` procesa todas las funciones identificadas del rango. `--batch N` crea
un lote reanudable; las restantes mantienen el resultado `partial`. `--resume`
comprueba ROM, fingerprint de análisis/nombre/firma/versión y hashes de archivos.
Registros incompletos o corruptos se vuelven a exportar. Las funciones fallidas no
se cuentan como éxito. La exportación por función es atómica en filesystems que
soportan `ATOMIC_MOVE`; si no lo soportan se produce un error explícito.

La ausencia de `summary.json`, hash distinto, salida no cero o estado parcial
produce un error del wrapper. No se reutiliza un resumen antiguo como evidencia de
una ejecución nueva. Un lote parcial se reanuda con el mismo comando y `--resume`.
El pipeline conserva informes si la etapa Ghidra falla. Los logs quedan privados.

## Compatibilidad con el script anterior

`scripts/ghidra/ExportFunctions.py` ahora deriva al exportador Java. Requiere Jython
si se ejecuta como Python, que puede ser opcional en tu distribución. Es preferible
ejecutar `ArcanaExport.java` directamente en Script Manager o por CLI. El modo GUI
no valida por sí mismo toda la integración Headless; ambos requieren prueba local.

## Pendiente de validación real

Compilar script, importar con el loader instalado, comprobar bloques/contexto con
una ROM autorizada, interrumpir/reanudar un lote, verificar errores/timeouts y cotejar
una función con símbolos locales. El índice no es una medida de recuperación del
código original; Auto Analysis puede no descubrir funciones o confundir datos.
No se ha convertido automáticamente esta salida Ghidra a entidades AIR Function.
