<# Consolidate an existing portrait batch, preserving every variant and ID. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Lote,
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [string]$Out = '',
    [switch]$CrearZip,
    [switch]$Abrir
)
. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
$Script = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../variantes/consolidar_retratos.py')).ProviderPath
$Lote = (Resolve-Path -LiteralPath $Lote).ProviderPath
$Arguments = @($Script, '--repo', $ProjectRoot, '--input', $Lote)
if ($Out) { $Arguments += @('--out', $Out) }
if ($CrearZip) { $Arguments += '--crear-zip' }
if ($Abrir) { $Arguments += '--abrir' }
$PSNativeCommandUseErrorActionPreference = $false
Push-Location -LiteralPath $ProjectRoot
try {
    & $Python @Arguments
    $Code = $LASTEXITCODE
    if ($Code -notin @(0, 130)) {
        throw 'La consolidacion se detuvo. Comparte la salida completa.'
    }
} finally { Pop-Location }
exit $Code
