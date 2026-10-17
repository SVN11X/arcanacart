<#
Runs FE7 + FE8 bases and selected mods. -AllVariants processes every UPS in both ZIPs.
Exit codes: 0 completed/planned; 2 input/argument error; 3 some jobs failed/partial.
#>
[CmdletBinding()]
param(
    [ValidateSet('all','fe7','fe8')][string]$Game = 'all',
    [string]$Config = 'private/fire-emblem.json',
    [string]$PythonExe = '',
    [switch]$AllVariants,
    [switch]$CatalogOnly,
    [switch]$DryRun,
    [switch]$NoScan,
    [switch]$OpenReport
)
. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$Python = Get-ArcanaPython -Requested $PythonExe
$Parameters = @('-m', 'arcanacart', 'batch', '--root', $ProjectRoot, '--config', $Config, '--game', $Game, '--resume', '--verbose')
if ($AllVariants) { $Parameters += '--all-variants' }
if ($CatalogOnly) { $Parameters += '--catalog-only' }
if ($DryRun) { $Parameters += '--dry-run' }
if ($NoScan) { $Parameters += '--no-scan' }
$Code = 2
Push-Location -LiteralPath $ProjectRoot
try {
    if (-not $DryRun) {
        & $Python -m arcanacart batch --root $ProjectRoot --config $Config --init
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & $Python @Parameters
    $Code = $LASTEXITCODE
    if ($OpenReport -and -not $DryRun) {
        $Settings = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
        $Report = Join-Path $ProjectRoot (Join-Path $Settings.workspace 'index.html')
        if (Test-Path -LiteralPath $Report -PathType Leaf) { Invoke-Item -LiteralPath $Report }
    }
} finally { Pop-Location }
exit $Code
