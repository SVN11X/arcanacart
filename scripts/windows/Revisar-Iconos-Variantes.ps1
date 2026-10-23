<#
Review the 43 registered variants using exact ROM/AIR hashes and bounded reads.
No scanner, decompression, dependency installation or portrait extraction.
#>
[CmdletBinding()]
param(
    [string]$Datos = 'C:\FireEmblem',
    [string]$OutputParent = '',
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [switch]$CrearZip
)

. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$PSNativeCommandUseErrorActionPreference = $false
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
if (-not $OutputParent) { $OutputParent = Join-Path $Datos 'resultados' }
$Out = Join-Path $OutputParent (
    'revision-iconos-variantes-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
    [guid]::NewGuid().ToString('N').Substring(0, 6)
)
$Arguments = @('-m', 'arcanacart.icon_variants', 'review', '--datos', $Datos, '--out', $Out)
if ($CrearZip) { $Arguments += @('--zip', ($Out + '.zip')) }
Push-Location -LiteralPath $ProjectRoot
try {
    Write-Host 'Revisando hashes y ventanas de iconos de las 43 variantes. No se repite el escaneo.'
    $Text = (& $Python @Arguments | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "La revision se detuvo. Conserva la salida completa. Si existe $Out, se conserva."
    }
    $Result = $Text | ConvertFrom-Json
    if ($Result.status -ne 'completed') { throw 'La revision no confirmo su finalizacion.' }
    Write-Host "Variantes: $($Result.variants); verificadas: $($Result.counts.verified); pendientes: $($Result.counts.pending); errores: $($Result.counts.error)."
    Write-Host "Informe: $(Join-Path $Out 'revision.json')"
    if ($CrearZip) { Write-Host "ZIP para revisar: $($Result.zip.output)" }
    if (-not $Result.ready_for_full_batch) {
        Write-Host 'Adjunta el ZIP de revision. Las candidatas no quedan habilitadas para extraccion.'
    }
    $Result | ConvertTo-Json -Depth 8
} finally { Pop-Location }
