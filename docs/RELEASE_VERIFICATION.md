# Verificación del paquete de entrega

La entrega 0.4.0 se distribuye como ZIP completo, generado exclusivamente desde
archivos versionados. Se verifican wheel y sdist, incluyendo los nuevos módulos,
lanzadores PowerShell y guía. El wheel se instala en un entorno aislado con
`--no-index --no-deps`; se comprueban las nuevas órdenes desde fuera del árbol fuente.
La suite se ejecuta también desde el ZIP descomprimido para detectar omisiones.

La comprobación rechaza entradas de ROM, parches binarios, assets extraídos,
referencias externas, directorios Git, entornos y cachés. Los ejemplos AIR/HTML
son contenido sintético creado por el generador distribuido.

Los resultados de esta comprobación se guardan en el informe de entrega;
el hash del ZIP se calcula después de empaquetar, sin introducirlo
en el propio commit para evitar una dependencia circular.

La entrega histórica 0.3.0 incluía un parche `git am` sobre el starter v0.2;
la descripción de aquel cambio permanece en `TECHNICAL_REPORT_v0.3.md`.
