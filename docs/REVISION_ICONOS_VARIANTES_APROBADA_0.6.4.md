# Rangos de iconos revisados: 43 variantes

La evidencia permite preparar la extracción de ventanas acotadas de las 43
variantes: FE7 IDs 0–172 y FE8 IDs 0–223, ambos inclusive. Las definiciones están
ligadas al hash de cada ROM, sus punteros, los bytes del banco, la paleta y los
contextos de acceso. No se confirma el final reservado de las tablas ni la
totalidad de los recursos del juego.

## Paquete y comprobaciones

Fuente: `revision-iconos-variantes-20261023-214804-177238.zip`.

- ZIP SHA-256: `7d54913acf611056886a9157fd12cf6af1ba5de282b11b766051015e7b06528c`.
- `revision.json` SHA-256: `c94433bb5f3c54a8ca33bbcc3cbb81b7e10afb1b4841af545f345fee415d256f`.
- 306 archivos con CRC y SHA-256 correctos, rutas portables y cobertura completa
  del manifiesto; plan e identidades coinciden con el registro del repositorio.
- Siete bancos distintos en las ventanas recibidas; una única paleta RGB555 de
  32 bytes, idéntica a la primera paleta de las dos bases auditadas.
- Se reconstruyeron independientemente los píxeles de los 1.466 IDs presentes
  en esos siete bancos y se compararon con el renderizador y PNG de ArcanaCart.
  Todos coincidieron. Se inspeccionaron visualmente las siete hojas de contacto.
- La expansión de esos bancos a sus 43 procedencias comprende 9.224 apariciones.
  Se esperan 400 PNG distintos entre juegos: 179 distintos en FE7 y 258 en FE8,
  con 37 imágenes compartidas. No se observaron apariciones transparentes.

Las ROM completas no estaban en el ZIP. Sus hashes exactos se comprobaron en
la ejecución local anterior y se volverán a comprobar al extraer. Esta revisión
verifica la evidencia recibida y su interpretación; no recalcula aquí el hash
de una ROM que no fue recibida.

## Accesos y formato

Se inspeccionaron las instrucciones Thumb presentes en las ventanas de código,
no solo los indicadores `access_context_matches_base` del informe. En todos los
casos se observan el desplazamiento de ID por siete bits (128 bytes por icono),
la carga literal del puntero del banco, su suma al índice desplazado y la
transferencia de 128 bytes. Las cargas literales consumen los offsets declarados:

| Juego | Instrucción que carga el banco | Literal del banco | Instrucción que carga la paleta | Literal de la paleta |
| --- | --- | --- | --- | --- |
| FE7 | `0x4DEE` | `0x4E20` | `0x4D30` | `0x4D40` |
| FE8 | `0x3682` | `0x36B4` | `0x35C0` | `0x35D0` |

Los cálculos de dirección de las cargas literales se hicieron a partir de sus
opcodes y posiciones. Las secuencias de la fuente de iconos incluyen los bytes
`e4 01 0c 48 24 18` y `20 1c 80 22`. El cargador de paletas conserva
`00 b5 01 1c 03 48 49 01 40 22` seguido de su llamada y retorno.

El contexto amplio de paleta FE8 difería de la base por código o constantes
anteriores. La rutina de carga de paletas inspeccionada permanece compatible:
la diferencia del contexto completo no implicaba por sí sola otra geometría de
iconos. Esta conclusión se apoya también en la paleta y los bancos recibidos;
no constituye una prueba de equivalencia de todas las rutas de ejecución.

El formato usado sigue siendo raw 4bpp, cuatro tiles 8×8 en orden 2×2, imagen
16×16, 16 colores RGB555 y transparencia del índice cero. La rutina de carga
puede copiar dos bancos de paletas; la exportación aprobada usa únicamente los
32 bytes de la primera paleta, igual que la extracción de bases. No se asignan
nombres de objetos ni se afirma que cada ID se utilice con esa paleta en el juego.

Fuentes de formato y acceso previamente fijadas:

- [FEBuilder: ImageItemIconForm.cs](https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ImageItemIconForm.cs).
- [FEBuilder: ROMFE7U.cs](https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ROMFE7U.cs).
- [FEBuilder: ROMFE8U.cs](https://github.com/FEBuilderGBA/FEBuilderGBA/blob/8e3557912ddab708d11bf85ad311b41bb6630fd1/FEBuilderGBA/ROMFE8U.cs).
- [Descompilación FE8: src/icon.c](https://github.com/FireEmblemUniverse/fireemblem8u/blob/04d1edb163d14bd10777a065697e1a9f17be65f2/src/icon.c).

## Rangos y grupos

Los hashes completos están en `REVISION_ICONOS_VARIANTES_APROBADA_0.6.4.json`
y las aprobaciones individuales en `scripts/variantes/iconos/variantes.json`.
Compartir el contenido del banco no sustituye la comprobación de identidad y
offsets de cada variante.

| Variantes | IDs inclusive | Offset del banco | Offset de paleta |
| --- | --- | --- | --- |
| FE7 001–003 y 005–008 | 0–172 | `0xC5EA4` | `0xCBEA4` |
| FE7 004 | 0–172 | `0xC5EA4` | `0xCBEA4` |
| FE8 001 | 0–223 | `0x1009C98` | `0x5996F4` |
| FE8 002–005 | 0–223 | `0x1357190` | `0x5996F4` |
| FE8 006–009 | 0–223 | `0x136D46C` | `0x5996F4` |
| FE8 010–013 | 0–223 | `0x10730CC` | `0x5996F4` |
| FE8 014–025 | 0–223 | `0x10730CC` | `0x5996F4` |
| FE8 026–035 | 0–223 | `0x1073608` | `0x5996F4` |

FE8 002–009 comparte un banco, con offsets distintos entre las dos familias.
FE8 010–013 y 014–025 tienen bancos diferentes aunque comiencen en el mismo
offset relativo a sus ROM. En FE7 no se detectó la firma FEditorAdv que excluye
el último ID original; los dos bancos conservan los gráficos de ese último ID.

Los bytes posteriores al rango FE8 contienen más material, pero 128 bytes de
contexto no confirman sus límites. No se amplía automáticamente a 255 iconos ni
se usa el tamaño de RAM de la caché como medida del banco gráfico.

## Confirmación sin repetir la adquisición

`Revisar-Iconos-Variantes.ps1 -RevisionAnterior CARPETA` aplica estas revisiones
al paquete ya generado. Comprueba su manifiesto, el hash del informe fijado en
el plan y los bytes de bancos, paletas y contextos de cada aprobación. Escribe
una carpeta nueva con las 43 definiciones verificadas; conserva la anterior.
No abre ROM ni AIR en este paso. El lote posterior sí vuelve a comprobarlos.

La alternativa sigue siendo ejecutar la revisión normal sobre los archivos
locales; ya reconocerá los 43 rangos revisados si sus bytes coinciden. No es
necesario repetirla para reutilizar el paquete recibido.

Ejemplo completo después de aplicar el parche de aprobación:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\my_drive\Portafolio\arcanacart'

    $Texto = (& '.\scripts\windows\Revisar-Iconos-Variantes.ps1' `
        -RevisionAnterior 'C:\FireEmblem\resultados\revision-iconos-variantes-20261023-214804-177238' `
        -Datos 'C:\FireEmblem' `
        -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
        -CrearZip | Out-String)
    $Confirmada = $Texto | ConvertFrom-Json
    if (-not $Confirmada.ready_for_full_batch -or $Confirmada.counts.verified -ne 43) {
        throw 'La evidencia no habilita las 43 variantes. Copia la salida completa.'
    }

    & '.\scripts\windows\Extraer-Iconos-Variantes.ps1' `
        -Revision $Confirmada.output `
        -Datos 'C:\FireEmblem' `
        -PythonExe 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe' `
        -CrearZip
}
```

Adjunta el ZIP `iconos-variantes-...zip` para auditar la exportación completa.
Se esperan 43 variantes y 9.224 apariciones dentro de los rangos indicados.

## Comprobación del parche

Se ejecutaron 76 pruebas de iconos: las 64 anteriores y 12 de confirmación.
Cubren conservación de evidencia, confirmación sin lectura de ROM/AIR, vínculo
al informe original, rechazos de manipulación y extracción desde una revisión
confirmada con ROM sintética. También se confirmó el paquete real recibido:
43 verificadas, cero pendientes, cero errores y ZIP portable de 306 archivos.

No se ejecutaron los lanzadores PowerShell en este entorno ni se recibieron
las ROM completas para ejecutar aquí el lote real. Sigue pendiente comprobar
la presentación de las galerías en un navegador real. Se mantiene 0.6.4.
