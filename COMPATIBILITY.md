# Compatibilidad comprobada y límites

| Componente | Estado |
|---|---|
| Python | Mínimo 3.10; ejecución local comprobada en 3.12.14 |
| Linux | Pruebas, instalación y ejemplo ejecutados localmente |
| Windows/WSL | Código portable y CI preparados; ejecución real pendiente en esos sistemas |
| macOS | No probado |
| FE7U/FE8U originales | SHA-1 de las dos bases adjuntas comprobado; preparación, análisis y comparación probados con UPS sintéticos |
| Japón/Europa y otras regiones | Cabecera/genérico; sin huellas completas ni layouts regionales verificados |
| FE7 Remastered/Sacred Trilogy y otros hacks | Nombres, selección y lote implementados; ZIP reales de mods pendientes de recepción; sin parsers específicos |
| Personajes/clases FE7 y FE8 | Lectura binaria implementada, configuración por hash obligatoria, fixtures sintéticos |
| Objetos/armas FE8 | Datos de tabla Item; arma inferida por flags que se conservan, sin entidad Weapon automática |
| Objetos FE7 | Pendiente de layout independiente verificado |
| Capítulos/mapas/eventos/textos completos | Pendientes |
| Gráficos/audio/lógica de combate | No reconstruidos; recursos comprimidos permanecen sin clasificación semántica |
| UPS1 | Implementado, reversible, CRC completo; no in-place |
| IPS/BPS | Futuros adaptadores; no implementados |
| Ghidra | Integración Java/Headless experimental; contratos probados con mocks, no Ghidra real |
| Referencias fe7_us/fireemblem8u | Importación local de mapas/nm/assignments, hash y commit; no build automático |
| LT-Maker `.ltproj` | No exportable en 0.4.0; cero entidades verificadas como compatibles con el motor |

Los proyectos FE7 y FE8 tienen cobertura distinta. ArcanaCart no reproduce
porcentajes de descompilación upstream ni declara funciones equivalentes por
compartir nombre o dirección. La comparación de bytes es exacta para sus entradas;
la comparación AIR depende de layouts/definiciones y puede reflejar distinta
cobertura. No infiere modificaciones de reglas de combate desde bytes aislados.

## AIR frente a un motor de destino

AIR es formato de intercambio y evidencia. Ningún comando genera un archivo
`.ltproj` falso ni crea una campaña. Una futura integración requiere seleccionar
un commit de [LT-Maker](https://gitlab.com/rainlash/lt-maker), inspeccionar proyectos
reales, adaptar IDs/reglas/recursos, construir una campaña sintética y abrirla en
ese motor. No se han realizado esas verificaciones.

Ghidra y gba-ghidra-loader se consultan como herramientas externas con sus licencias
Apache-2.0. Las referencias de descompilación se consultan por estructuras/hashes;
no se vendorizó su código ni se asume una licencia común. LT-Maker y
FEMultiPlayer-V2 requieren evaluación de su versión/licencia antes de incorporar
código; no se incorpora ninguno en esta entrega. El código nuevo mantiene la
licencia MIT del starter, preservando su atribución.
