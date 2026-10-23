<# Extract only definitions validated by a completed, hash-checked review. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Revision,
    [string]$Datos = 'C:\FireEmblem',
    [string]$OutputParent = '',
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [switch]$SoloVerificadas,
    [switch]$CrearZip
)

. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$PSNativeCommandUseErrorActionPreference = $false
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
if (-not (Test-Path -LiteralPath $Revision -PathType Container)) {
    throw "No existe la carpeta de revision: $Revision"
}
$Revision = (Resolve-Path -LiteralPath $Revision).ProviderPath
if (-not $OutputParent) { $OutputParent = Join-Path $Datos 'resultados' }
$Out = Join-Path $OutputParent (
    'iconos-variantes-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
    [guid]::NewGuid().ToString('N').Substring(0, 6)
)
$Arguments = @('-m', 'arcanacart.icon_variants', 'extract', '--datos', $Datos,
               '--review', $Revision, '--out', $Out)
if ($SoloVerificadas) { $Arguments += '--only-verified' }
if ($CrearZip) { $Arguments += @('--zip', ($Out + '.zip')) }
Push-Location -LiteralPath $ProjectRoot
try {
    Write-Host 'Comprobando de nuevo la identidad y evidencia de todas las variantes seleccionadas.'
    $Text = (& $Python @Arguments | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "El lote se detuvo. Conserva la salida completa y cualquier resultado en $Out."
    }
    $Result = $Text | ConvertFrom-Json
    if ($Result.status -ne 'completed') { throw 'El lote no confirmo su finalizacion.' }
    Write-Host "Variantes: $($Result.processed_variants); apariciones: $($Result.icon_occurrences); PNG distintos: $($Result.unique_pngs_across_variants)."
    Write-Host "Resultados: $Out"
    Write-Host "Galerias: $(Join-Path $Out 'galerias.csv')"
    if ($CrearZip) { Write-Host "ZIP para revisar: $($Result.zip.output)" }
    $Result | ConvertTo-Json -Depth 8
} finally { Pop-Location }
