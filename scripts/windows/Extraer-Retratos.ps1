<#
Reconstruct documented face-table graphics. Reuses AIR/resources and reads the
matching local ROM for raw RGB555 palettes. No scanner, patching or ROM upload.
#>
[CmdletBinding()]
param(
    [string]$Datos = 'C:\FireEmblem',
    [string]$ResumenCsv = '',
    [string]$AirPath = '',
    [string]$RomPath = '',
    [string]$Definition = '',
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [switch]$SinRom,
    [switch]$CrearZip,
    [switch]$Abrir
)
. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
if (-not $AirPath) {
    if (-not $ResumenCsv) { throw 'Indica -ResumenCsv con el resumen de reparacion o -AirPath con un AIR exacto.' }
    $Base = Import-Csv -LiteralPath $ResumenCsv |
        Where-Object { $_.Juego -eq 'fe7' -and $_.Variante -eq 'base' } |
        Select-Object -First 1
    if ($null -eq $Base -or -not $Base.Galeria) { throw 'No se encuentra una galeria para la base FE7 en el CSV.' }
    $Review = Split-Path -Parent $Base.Galeria
    $AirPath = Join-Path (Split-Path -Parent $Review) 'air.json'
}
$AirPath = (Resolve-Path -LiteralPath $AirPath).ProviderPath
if ($SinRom -and $RomPath) { throw 'Elige -RomPath o -SinRom.' }
if (-not $SinRom) {
    if (-not $RomPath) { $RomPath = Join-Path $Datos 'resultados/fe7/fe7-usa-base.gba' }
    if (-not (Test-Path -LiteralPath $RomPath -PathType Leaf)) {
        throw "No se encuentra la ROM local: $RomPath. Indica su ruta con -RomPath."
    }
    $RomPath = (Resolve-Path -LiteralPath $RomPath).ProviderPath
}
if ($Definition) { $Definition = (Resolve-Path -LiteralPath $Definition).ProviderPath }
$Out = Join-Path (Split-Path -Parent $AirPath) ('retratos-0.6.0-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
$PSNativeCommandUseErrorActionPreference = $false
Push-Location -LiteralPath $ProjectRoot
try {
    $Version = (& $Python -c 'import arcanacart; print(arcanacart.__version__)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [version]$Version -lt [version]'0.6.0') { throw 'Este extractor requiere ArcanaCart 0.6.0.' }
    $Arguments = @('-m', 'arcanacart', 'faces', '--input', $AirPath, '--out', $Out, '--verbose')
    if (-not $SinRom) { $Arguments += @('--rom', $RomPath) }
    if ($Definition) { $Arguments += @('--definition', $Definition) }
    Write-Host 'Reconstruyendo los componentes de la tabla de retratos...'
    $SavedAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $Text = (& $Python @Arguments | Out-String)
        $Code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $SavedAction }
    if ($Code -notin @(0, 3)) { throw "El extractor termino con codigo $Code. Revisa el diagnostico anterior." }
    $State = $Text | ConvertFrom-Json
    Write-Host "Estado: $($State.status)"
    Write-Host "Retratos: $($State.portraits); miniaturas: $($State.miniatures); tarjetas: $($State.classcards)."
    Write-Host "Bloques unicos vinculados: $($State.unique_classified_blobs); paletas reales: $($State.resolved_palettes)."
    Write-Host "Errores: $($State.errors); componentes sin paleta real: $($State.components_without_real_palette)."
    Write-Host "Galeria: $($State.gallery)"
    if ($CrearZip) {
        $Zip = $Out + '.zip'
        Compress-Archive -LiteralPath $Out -DestinationPath $Zip -CompressionLevel Optimal
        Write-Host "Recursos exportados: $Zip"
    }
    if ($Abrir) { Invoke-Item -LiteralPath $State.gallery }
} finally { Pop-Location }
exit $Code
