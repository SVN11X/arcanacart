# Contribuir

Usa Python 3.10+ y un entorno virtual. Instala `.[dev]` y ejecuta las comprobaciones
de README. GitHub Actions prepara Python 3.10/3.12/3.13 en Linux y Windows; la matriz
no equivale a resultados comprobados antes de ejecutarse en tu repositorio.

Mantén los comandos/API de compatibilidad del starter y las 11 pruebas originales
(solo se aplicó formato a sus archivos). El código nuevo debe especificar errores,
rangos, evidencia y recursos máximos. No agregues módulos sin implementación útil.
Las definiciones de otra variante necesitan otro hash; no añadas `allow-any-hash`.
No conviertas resultados heurísticos en `confirmed` por comodidad de una exportación.

Un parser nuevo requiere fuente primaria versionada, fixture original independiente,
expectativas de campos, límites, entradas truncadas y prueba de serialización AIR.
Las pruebas públicas no deben contener ROMs ni fragmentos copiados de ellas. Para
validaciones comerciales, usa copias locales y un procedimiento privado optativo.
No subas dumps, gráficos, música, diálogos o pseudocódigo a un PR público.

Un adaptador externo requiere probar la herramienta real y registrar versión/API;
si solo se probaron mocks, etiquétalo como contrato y mantén el estado experimental.
Las licencias de terceros deben revisarse antes de copiar código. Preferimos leer
referencias externas y conservar su commit/hash sin vendorizarlas.

No ejecutes scripts de referencias o entradas para extraer datos. Los subprocesos
necesitan argv explícito, errores controlados y ninguna descarga implícita.
Las salidas pertenecen a carpetas privadas; revisa `git diff` y `git status`.
La instalación/runtime debe seguir siendo útil con la biblioteca estándar.
