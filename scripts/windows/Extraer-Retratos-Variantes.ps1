<#
Validate and export the reviewed FE7/FE8 variant portrait ranges.
Resumes the latest compatible batch by default; keeps original inputs read-only.
#>
[CmdletBinding()]
param(
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [string]$Plan = '',
    [string]$Resultados = 'C:\FireEmblem\resultados',
    [string]$Out = '',
    [switch]$NuevaEjecucion,
    [switch]$Abrir
)

. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
$Script = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../variantes/extraer_retratos_variantes.py')).ProviderPath
$Arguments = @($Script, '--repo', $ProjectRoot, '--output-parent', $Resultados)
if (-not $NuevaEjecucion) { $Arguments += '--resume-latest' }
if ($Plan) {
    $Plan = (Resolve-Path -LiteralPath $Plan).ProviderPath
    $Arguments += @('--plan', $Plan)
}
if ($Out) { $Arguments += @('--out', $Out) }
if ($Abrir) { $Arguments += '--abrir' }

$PSNativeCommandUseErrorActionPreference = $false
Push-Location -LiteralPath $ProjectRoot
try {
    & $Python @Arguments
    $Code = $LASTEXITCODE
    if ($Code -notin @(0, 130)) {
        throw 'El lote requiere revision. Comparte la salida completa y el ZIP indicado, si se genero.'
    }
} finally { Pop-Location }
exit $Code
