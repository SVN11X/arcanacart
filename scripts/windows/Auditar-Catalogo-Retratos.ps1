[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CatalogoZip,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$LoteOriginalZip,

    [ValidateNotNullOrEmpty()]
    [string]$Python = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',

    [ValidateNotNullOrEmpty()]
    [string]$OutputParent = 'C:\FireEmblem\resultados'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RepositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Auditor = Join-Path $RepositoryRoot 'tools\auditoria-catalogo-0.6.3\auditar_catalogo.py'

foreach ($InputFile in @($Python, $Auditor, $CatalogoZip, $LoteOriginalZip)) {
    if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
        throw "No se encuentra el archivo: $InputFile"
    }
}

$PythonPath = (Resolve-Path -LiteralPath $Python).ProviderPath
$CatalogoPath = (Resolve-Path -LiteralPath $CatalogoZip).ProviderPath
$LotePath = (Resolve-Path -LiteralPath $LoteOriginalZip).ProviderPath

& $PythonPath -c 'import PIL'
if ($LASTEXITCODE -ne 0) {
    throw 'El Python indicado necesita Pillow. Selecciona un entorno que ya lo incluya con -Python.'
}

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Suffix = [Guid]::NewGuid().ToString('N').Substring(0, 6)
$OutputDirectory = Join-Path $OutputParent "auditoria-catalogo-$Stamp-$Suffix"
if (Test-Path -LiteralPath $OutputDirectory) {
    throw "La carpeta de salida ya existe: $OutputDirectory"
}
$null = New-Item -ItemType Directory -Path $OutputDirectory
$ReportPath = Join-Path $OutputDirectory 'auditoria.json'

Write-Host 'Auditando los dos ZIP. No se leen ROM ni se repiten extracciones.'
& $PythonPath $Auditor --catalogo $CatalogoPath --original $LotePath --salida $ReportPath
$AuditExitCode = $LASTEXITCODE

if ($AuditExitCode -ne 0) {
    throw "La auditoria no termino con exito (codigo $AuditExitCode). Revisa la salida y, si se genero, $ReportPath"
}

Write-Host "Auditoria completada: $ReportPath"
