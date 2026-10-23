<#
Reanalyzes existing ROMs from the standalone FireEmblem-Terminal workflow.
Run directly in the current PowerShell session; no powershell.exe lookup.
No ZIP import, file renaming, or UPS patching is performed here.
#>
[CmdletBinding()]
param(
    [string]$Datos = 'C:\FireEmblem',
    [ValidateSet('all', 'fe7', 'fe8')][string]$Game = 'all',
    [string]$Variant = '*',
    [ValidateRange(1, 4096)][int]$BudgetMiB = 64,
    [ValidateRange(1, 100000)][int]$ResultLimit = 20000,
    [ValidateRange(1, 1000000)][int]$CandidateLimit = 500000,
    [ValidateNotNullOrEmpty()][ValidateSet('lz10', 'rle')][string[]]$Compression = @('lz10'),
    [switch]$CompareBase,
    [string]$PythonExe = ''
)
. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if (-not $PythonExe) {
    $LocalPython = Join-Path $Datos 'entorno-arcanacart/Scripts/python.exe'
    if (Test-Path -LiteralPath $LocalPython -PathType Leaf) { $PythonExe = $LocalPython }
}
$Python = Get-ArcanaPython -Requested $PythonExe
$Methods = @('lz10', 'rle') | Where-Object { $_ -in $Compression }
$MethodTag = $Methods -join '-'
$ResultsRoot = Join-Path (Resolve-Path -LiteralPath $Datos).ProviderPath 'resultados'
if (-not (Test-Path -LiteralPath $ResultsRoot -PathType Container)) {
    throw "No existe $ResultsRoot. Este script usa las ROMs ya preparadas."
}
$Jobs = New-Object System.Collections.Generic.List[object]
foreach ($Id in @('fe7', 'fe8')) {
    if ($Game -ne 'all' -and $Game -ne $Id) { continue }
    $Folder = Join-Path $ResultsRoot $Id
    if (-not (Test-Path -LiteralPath $Folder -PathType Container)) { continue }
    $Base = Join-Path $Folder "$Id-usa-base.gba"
    if (('base' -like $Variant -or $CompareBase) -and (Test-Path -LiteralPath $Base -PathType Leaf)) {
        $Jobs.Add([pscustomobject]@{ Game = $Id; Variant = 'base'; Rom = $Base; Parent = $Folder; Stem = 'base' })
    }
    foreach ($Child in @(Get-ChildItem -LiteralPath $Folder -Directory | Sort-Object Name)) {
        if ($Child.Name -notlike $Variant) { continue }
        $Rom = Join-Path $Child.FullName "$Id-mod.gba"
        if (Test-Path -LiteralPath $Rom -PathType Leaf) {
            $Jobs.Add([pscustomobject]@{ Game = $Id; Variant = $Child.Name; Rom = $Rom; Parent = $Child.FullName; Stem = 'analisis' })
        }
    }
}
if ($Jobs.Count -eq 0) { throw 'No se encontraron ROMs preparadas para esa seleccion.' }
$Rows = New-Object System.Collections.Generic.List[object]
$Failed = $false
$Partial = $false
$BaseReports = @{}
# PowerShell 7 may promote native exit 3 to an exception. Partial is expected data.
$PSNativeCommandUseErrorActionPreference = $false
Push-Location -LiteralPath $ProjectRoot
try {
    $Version = (& $Python -c 'import arcanacart; print(arcanacart.__version__)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [version]$Version -lt [version]'0.4.2') {
        throw 'Aplica primero ArcanaCart 0.4.2 o posterior a este proyecto.'
    }
    $Number = 0
    foreach ($Job in $Jobs) {
        $Number++
        $Namespace = "$Version-$MethodTag-b$BudgetMiB-r$ResultLimit-c$CandidateLimit"
        $Out = Join-Path $Job.Parent ($Job.Stem + '-' + $Namespace)
        Write-Host "[$Number/$($Jobs.Count)] $($Job.Game) / $($Job.Variant)"
        try {
            $Arguments = @(
                '-m', 'arcanacart', 'pipeline', '--rom', $Job.Rom,
                '--out', $Out, '--resume', '--budget', ([string]([long]$BudgetMiB * 1048576)),
                '--limit', ([string]$ResultLimit), '--max-candidates', ([string]$CandidateLimit)
            )
            $Arguments += @('--compression') + @($Methods)
            $Text = (& $Python @Arguments | Out-String)
            $Code = $LASTEXITCODE
            if ($Code -notin @(0, 3)) { throw "ArcanaCart termino con codigo $Code. Consulta el error anterior." }
            $State = $Text | ConvertFrom-Json
            $Air = Get-Content -LiteralPath (Join-Path $Out 'air.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            $Status = 'finalizado'
            if ($Code -eq 3 -or $State.status -eq 'partial') { $Status = 'parcial'; $Partial = $true }
            $Comparison = ''
            $Matches = $null
            $Different = $null
            if ($Job.Stem -eq 'base') { $BaseReports[$Job.Game] = Join-Path $Out 'air.json' }
            elseif ($CompareBase) {
                if (-not $BaseReports.ContainsKey($Job.Game)) { throw 'No se pudo analizar la base para comparar.' }
                $Comparison = Join-Path $Out ('comparacion-base-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
                $CompareArgs = @(
                    '-m', 'arcanacart', 'compare-resources', '--left', $BaseReports[$Job.Game],
                    '--right', (Join-Path $Out 'air.json'), '--out', $Comparison
                )
                $CompareText = (& $Python @CompareArgs | Out-String)
                $CompareCode = $LASTEXITCODE
                if ($CompareCode -notin @(0, 3)) { throw "La comparacion termino con codigo $CompareCode." }
                $Compared = $CompareText | ConvertFrom-Json
                $Matches = $Compared.salidas_unicas_coincidentes
                $Different = $Compared.salidas_unicas_sin_coincidencia
                if ($CompareCode -eq 3) { $Status = 'parcial'; $Partial = $true }
            }
            $Rows.Add([pscustomobject]@{
                Juego = $Job.Game; Variante = $Job.Variant; Estado = $Status
                Formatos = $MethodTag
                Bloques = $State.resource_count
                AvanceLinealPct = $Air.scan.search_progress_percent
                CabecerasReferenciadasRevisadas = $Air.scan.referenced_header_targets_checked
                Informe = (Join-Path $Out 'report.html')
                Comparacion = $Comparison; Coincidentes = $Matches; SinCoincidencia = $Different
                Detalle = $Air.scan.stop_reason
            })
        } catch {
            $Failed = $true
            $Rows.Add([pscustomobject]@{
                Juego = $Job.Game; Variante = $Job.Variant; Estado = 'error'
                Formatos = $MethodTag
                Bloques = $null; AvanceLinealPct = $null
                CabecerasReferenciadasRevisadas = $null; Informe = ''
                Comparacion = ''; Coincidentes = $null; SinCoincidencia = $null
                Detalle = $_.Exception.Message
            })
            Write-Warning "$($Job.Variant): $($_.Exception.Message)"
        }
    }
    $Summary = Join-Path $ResultsRoot ("resumen-reanalisis-$Version-$MethodTag-" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.csv')
    $Rows | Export-Csv -LiteralPath $Summary -NoTypeInformation -Encoding UTF8
    $Rows | Format-Table Juego, Variante, Estado, Bloques, AvanceLinealPct -AutoSize
    Write-Host "Informes y diagnosticos: $Summary"
    Write-Host "Alcance: candidatos $MethodTag. Tablas y codigo requieren sus extractores especificos."
} finally {
    Pop-Location
}
if ($Failed) { exit 2 }
if ($Partial) { exit 3 }
exit 0
