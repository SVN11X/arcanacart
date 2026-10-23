# Fuentes primarias consultadas

Consulta realizada el 16 de octubre de 2026 UTC. `source-evidence.json` registra
URLs y SHA-256 de los documentos técnicos obtenidos. No se distribuyen esos
archivos fuente externos ni recursos de juegos.

| Fuente | Uso y alcance |
|---|---|
| [FE7 README](https://github.com/StanHash/fe7_us) | SHA-1 exacto, alcance parcial de la descompilación |
| [FE7 unit.h, commit 5c8b3c5e254e00f0f3458b9772c27e1a5a326e3b](https://github.com/StanHash/fe7_us/blob/5c8b3c5e254e00f0f3458b9772c27e1a5a326e3b/include/unit.h) | Estructuras PInfo/JInfo y tamaños/campos, implementados de forma independiente |
| [FE8 README](https://github.com/FireEmblemUniverse/fireemblem8u) | SHA-1 exacto y requisitos del proyecto de referencia |
| [FE8 bmunit.h, commit f2e1f060dbe5b0cc35285df5a0f6659860644a04](https://github.com/FireEmblemUniverse/fireemblem8u/blob/f2e1f060dbe5b0cc35285df5a0f6659860644a04/include/bmunit.h) | CharacterData y ClassData |
| [FE8 bmitem.h, mismo commit](https://github.com/FireEmblemUniverse/fireemblem8u/blob/f2e1f060dbe5b0cc35285df5a0f6659860644a04/include/bmitem.h) | ItemData y campos de objetos |
| [FE8 tablas fuente](https://github.com/FireEmblemUniverse/fireemblem8u/tree/f2e1f060dbe5b0cc35285df5a0f6659860644a04/src) | Convenciones de índices; sin copiar contenido de personajes/objetos |
| [FE-CLib referencias](https://github.com/StanHash/FE-CLib/tree/master/reference) | Sintaxis SET_DATA/SET_FUNC; las ubicaciones no se incorporan como offsets universales |
| [Ghidra Headless](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md) | Import/process, loader, processor, scripts, timeout y argumentos |
| [HeadlessScript.java](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/Base/src/main/java/ghidra/app/util/headless/HeadlessScript.java) | Método real analysisTimeoutOccurred; no se asume nombre de un ejemplo antiguo |
| [DecompInterface.java](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/Decompiler/src/main/java/ghidra/app/decompiler/DecompInterface.java) | openProgram/decompileFunction y liberación de interfaz |
| [Program.java](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Framework/SoftwareModeling/src/main/java/ghidra/program/model/listing/Program.java) | Huella del ejecutable y registros |
| [gba-ghidra-loader](https://github.com/pudii/gba-ghidra-loader) | Instalación y separación de versiones de API |
| [GBALoader.java](https://github.com/pudii/gba-ghidra-loader/blob/main/src/main/java/gba/GBALoader.java) y [GBA.opinion](https://github.com/pudii/gba-ghidra-loader/blob/main/data/GBA.opinion) | Nombre de clase del loader y lenguaje armv4t; no ARMv7 |
| [GBATEK, mantenimiento mGBA](https://mgba-emu.github.io/gbatek/) | Mapa y mirrors GBA; la copia de consulta local quedó parcial, no es evidencia única de decodificación |
| [mGBA BIOS](https://github.com/mgba-emu/mgba/blob/master/src/gba/bios.c) | Contraste de formatos BIOS RLE/Huffman; lectores Python propios con vectores sintéticos |

No se descargaron repositorios durante comandos de análisis. Las consultas de
fuentes se hicieron durante el desarrollo, aparte de la herramienta distribuida.
La correlación local no descarga nada y conserva commit/hash de cada referencia.

Las fuentes públicas pueden cambiar. Los layouts FE usan commits fijados; los
archivos de API consultados por rama se identifican adicionalmente por el hash del
registro. La compatibilidad real del script Java requiere ejecutar la versión de
Ghidra elegida, no solo consultar su API.

## Formatos gráficos de 0.5.0

Se contrastó la organización de tiles, paletas y mapas BG con GBATEK, mantenido
por mGBA: https://mgba-emu.github.io/gbatek/ (secciones LCD VRAM Character Data,
BG Screen Data Format y Color Palettes; consulta del índice el 18 de octubre de 2026).
El conversor es una implementación propia, comprobada con vectores sintéticos
independientes; no se copian datos ni gráficos de ningún juego. No se añadió un
layout FE7 Item sin documentación verificable; se habilitan layouts declarativos.
