<#
Copies each supplied original ZIP to its formal input name. Originals are retained.
Run from anywhere; paths are literal, including spaces and [!] in ROM filenames.
No pip installation, activation, downloads or permanent policy changes are needed.
#>
[CmdletBinding()]
param(
    [string]$Fe7Rom = '',
    [string]$Fe8Rom = '',
    [string]$Fe7Mods = '',
    [string]$Fe8Mods = '',
    [string]$PythonExe = '',
    [switch]$PickFiles,
    [switch]$DryRun
)
. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$Python = Get-ArcanaPython -Requested $PythonExe
$Selected = [ordered]@{ Fe7Rom = $Fe7Rom; Fe8Rom = $Fe8Rom; Fe7Mods = $Fe7Mods; Fe8Mods = $Fe8Mods }
if ($PickFiles) {
    if ($env:OS -ne 'Windows_NT') { throw '-PickFiles requiere Windows; usa los parametros de rutas en otros sistemas.' }
    Add-Type -AssemblyName System.Windows.Forms
    $Titles = @{
        Fe7Rom = '1/4 - Selecciona la ROM base FE7 USA en ZIP'
        Fe8Rom = '2/4 - Selecciona la ROM base FE8 USA en ZIP'
        Fe7Mods = '3/4 - Selecciona el ZIP completo FE7 Remastered'
        Fe8Mods = '4/4 - Selecciona el ZIP completo Sacred Trilogy'
    }
    foreach ($Key in @('Fe7Rom', 'Fe8Rom', 'Fe7Mods', 'Fe8Mods')) {
        if (-not $Selected[$Key]) {
            $Dialog = New-Object System.Windows.Forms.OpenFileDialog
            try {
                $Dialog.Title = $Titles[$Key]
                $Dialog.Filter = 'Archivos ZIP (*.zip)|*.zip'
                $Dialog.CheckFileExists = $true
                $Dialog.Multiselect = $false
                if ($Dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
                    throw 'Seleccion cancelada. No se han copiado entradas.'
                }
                $Selected[$Key] = $Dialog.FileName
            } finally { $Dialog.Dispose() }
        }
    }
}
$Parameters = @('-m', 'arcanacart', 'batch-import', '--root', $ProjectRoot)
foreach ($Pair in @(@('--fe7-rom', $Selected.Fe7Rom), @('--fe8-rom', $Selected.Fe8Rom), @('--fe7-mods', $Selected.Fe7Mods), @('--fe8-mods', $Selected.Fe8Mods))) {
    if ($Pair[1]) {
        $FullPath = (Resolve-Path -LiteralPath $Pair[1]).Path
        $Parameters += @($Pair[0], $FullPath)
    }
}
if ($DryRun) { $Parameters += '--dry-run' }
$Code = 2
Push-Location -LiteralPath $ProjectRoot
try {
    & $Python @Parameters
    $Code = $LASTEXITCODE
    if ($Code -eq 0 -and -not $DryRun) {
        & $Python -m arcanacart batch --root $ProjectRoot --init
        $Code = $LASTEXITCODE
    }
} finally { Pop-Location }
exit $Code
