<#
Repair existing oversized tile previews. Keeps good PNG files and all recipes.
Use the CSV from Interpretar-Resultados.ps1. No ROM scan or batch reinterpretation.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ResumenCsv,
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [ValidateRange(0, 100000)][int]$MaxPreviews = 20000,
    [ValidateRange(1, 8192)][int]$ByteBudgetMiB = 512,
    [ValidateRange(1, 1024)][int]$PixelBudgetMi = 512,
    [switch]$SoloPlan
)
. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
$CsvPath = (Resolve-Path -LiteralPath $ResumenCsv).ProviderPath
$InputRows = @(Import-Csv -LiteralPath $CsvPath)
if ($InputRows.Count -eq 0) { throw 'El CSV esta vacio.' }
foreach ($Field in @('Juego', 'Variante', 'Estado', 'Galeria', 'Candidatos', 'BloquesUnicos', 'PNG', 'Aceptados', 'Pendientes', 'Detalle')) {
    if ($Field -notin $InputRows[0].PSObject.Properties.Name) { throw "Falta la columna $Field en el CSV." }
}
$Jobs = @($InputRows | Where-Object Estado -eq 'partial')
$Rows = New-Object System.Collections.Generic.List[object]
$Failed = $false
$Partial = $false
$JobNumber = 0
$PSNativeCommandUseErrorActionPreference = $false
Push-Location -LiteralPath $ProjectRoot
try {
    $Version = (& $Python -c 'import arcanacart; print(arcanacart.__version__)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [version]$Version -lt [version]'0.5.1') { throw 'Este reparador requiere ArcanaCart 0.5.1.' }
    Write-Host "Galerias parciales: $($Jobs.Count). Se reparan solo errores de imagen demasiado grande."
    foreach ($Row in $InputRows) {
        $Item = [ordered]@{
            Juego = $Row.Juego; Variante = $Row.Variante; Estado = $Row.Estado
            Candidatos = $Row.Candidatos; BloquesUnicos = $Row.BloquesUnicos; PNG = $Row.PNG
            Aceptados = $Row.Aceptados; Pendientes = $Row.Pendientes; Galeria = $Row.Galeria
            Detalle = $Row.Detalle; Elegibles = 0; Reparados = 0; PNGNuevos = 0; Respaldo = ''
        }
        if ($Row.Estado -eq 'partial') {
            $JobNumber++
            Write-Host "[$JobNumber/$($Jobs.Count)] $($Row.Juego) / $($Row.Variante)"
            try {
                if (-not $Row.Galeria) { throw 'El CSV no indica la galeria de esta fila.' }
                $Review = Split-Path -Parent $Row.Galeria
                $Air = Join-Path (Split-Path -Parent $Review) 'air.json'
                if (-not (Test-Path -LiteralPath $Air -PathType Leaf)) { throw "No se encuentra el AIR original: $Air" }
                $Arguments = @('-m', 'arcanacart', 'repair-previews', '--input', $Air, '--review', $Review,
                    '--max-previews', [string]$MaxPreviews, '--byte-budget', [string]([long]$ByteBudgetMiB * 1048576),
                    '--pixel-budget', [string]([long]$PixelBudgetMi * 1048576), '--verbose')
                if ($SoloPlan) { $Arguments += '--dry-run' }
                $SavedAction = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try {
                    $Text = (& $Python @Arguments | Out-String)
                    $Code = $LASTEXITCODE
                } finally { $ErrorActionPreference = $SavedAction }
                if ($Code -notin @(0, 3)) { throw "La reparacion termino con codigo $Code; revisa el diagnostico anterior." }
                $State = $Text | ConvertFrom-Json
                $Item.Estado = $State.status
                $Item.Candidatos = $State.candidates
                $Item.BloquesUnicos = $State.unique_blobs
                $Item.PNG = if ('generated_png_files' -in $State.PSObject.Properties.Name) { $State.generated_png_files } else { $State.generated_previews }
                $Item.Aceptados = $State.identified_by_user_review
                $Item.Pendientes = $State.pending_interpretation
                $Item.Galeria = $State.gallery
                $Item.Elegibles = $State.repair.eligible_blobs
                $Item.Reparados = $State.repair.repaired_blobs
                $Item.PNGNuevos = $State.repair.new_png_files
                if ('backup' -in $State.repair.PSObject.Properties.Name) { $Item.Respaldo = $State.repair.backup }
                $Item.Detalle = "Errores restantes: $($State.errors); vistas omitidas: $($State.skipped_previews)."
                if ($SoloPlan) { Write-Host "  Pendientes de reparar: $($Item.Elegibles) bloques / $($State.planned_png_files) PNG." }
                else { Write-Host "  $($Item.Estado): $($Item.Reparados) bloques reparados, $($Item.PNGNuevos) PNG nuevos. $($Item.Detalle)" }
            } catch {
                $Item.Estado = 'error'
                $Item.Detalle = $_.Exception.Message
                Write-Warning "$($Row.Variante): $($Item.Detalle)"
            }
        }
        if ($Item.Estado -eq 'error') { $Failed = $true }
        if ($Item.Estado -eq 'partial') { $Partial = $true }
        $Rows.Add([pscustomobject]$Item)
    }
    $Suffix = if ($SoloPlan) { 'plan-reparacion' } else { 'reparacion' }
    $Summary = Join-Path (Split-Path -Parent $CsvPath) ('resumen-' + $Suffix + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6) + '.csv')
    $Rows | Export-Csv -LiteralPath $Summary -NoTypeInformation -Encoding UTF8
    $Rows | Format-Table Juego, Variante, Estado, Elegibles, Reparados, PNGNuevos -AutoSize
    Write-Host "Resumen: $Summary"
    Write-Host 'Los errores de otras causas permanecen registrados. El CSV original se conserva.'
} finally { Pop-Location }
if ($Failed) { exit 2 }
if ($Partial) { exit 3 }
exit 0
