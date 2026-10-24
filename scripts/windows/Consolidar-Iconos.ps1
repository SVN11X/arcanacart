<# Consolidate an existing variant icon batch; never read ROM or repeat extraction. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Lote,
    [string]$OutputParent = 'C:\FireEmblem\resultados',
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [switch]$CrearZip,
    [switch]$Abrir
)

. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$PSNativeCommandUseErrorActionPreference = $false
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
if (-not (Test-Path -LiteralPath $Lote)) { throw "No existe el lote: $Lote" }
$Lote = (Resolve-Path -LiteralPath $Lote).ProviderPath
$Out = Join-Path $OutputParent (
    'catalogo-iconos-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
    [guid]::NewGuid().ToString('N').Substring(0, 6)
)
$Arguments = @('-m', 'arcanacart.icon_catalog', 'consolidate', '--input', $Lote, '--out', $Out)
if ($CrearZip) { $Arguments += @('--zip', ($Out + '.zip')) }
Push-Location -LiteralPath $ProjectRoot
try {
    Write-Host 'Comprobando el lote y consolidando iconos. No se leen ROM ni se repite la extraccion.'
    $Text = (& $Python @Arguments | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "La consolidacion se detuvo. Conserva la salida completa y cualquier resultado en $Out."
    }
    $Result = $Text | ConvertFrom-Json
    if ($Result.status -ne 'completed') { throw 'El catalogo no confirmo su finalizacion.' }
    Write-Host "Variantes: $($Result.variants); apariciones: $($Result.icon_occurrences); PNG unicos: $($Result.unique_images)."
    Write-Host "Raw unicos: $($Result.unique_raw_resources); paletas unicas: $($Result.unique_palettes); copias PNG evitadas: $($Result.duplicate_png_copies_avoided)."
    Write-Host "Galeria: $($Result.gallery)"
    if ($CrearZip) { Write-Host "ZIP para revisar: $($Result.zip.output)" }
    if ($Abrir) { Invoke-Item -LiteralPath $Result.gallery }
    $Result | ConvertTo-Json -Depth 8
} finally { Pop-Location }
