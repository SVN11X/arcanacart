<#
Interpret existing AIR/resources blobs. No ZIP import, UPS patching or ROM scan.
Compatible with Windows PowerShell 5.1 and PowerShell 7.
#>
[CmdletBinding()]
param(
    [string]$Datos = 'C:\FireEmblem',
    [ValidateSet('all', 'fe7', 'fe8')][string]$Game = 'all',
    [string]$Variant = '*',
    [ValidateRange(0, 100000)][int]$MaxPreviews = 500,
    [ValidateRange(1, 8192)][int]$ByteBudgetMiB = 512,
    [ValidateRange(1, 1024)][int]$PixelBudgetMi = 64,
    [string]$AirPath = '',
    [string]$Recipes = '',
    [string]$BaseAir = '',
    [string]$PythonExe = ''
)
. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if (-not $PythonExe) {
    $LocalPython = Join-Path $Datos 'entorno-arcanacart/Scripts/python.exe'
    if (Test-Path -LiteralPath $LocalPython -PathType Leaf) { $PythonExe = $LocalPython }
}
$Python = Get-ArcanaPython -Requested $PythonExe
$Jobs = New-Object System.Collections.Generic.List[object]
$ResultsRoot = Join-Path $Datos 'resultados'
if ($AirPath) {
    $Resolved = (Resolve-Path -LiteralPath $AirPath).ProviderPath
    $Jobs.Add([pscustomobject]@{ Game = $Game; Variant = 'explicit'; Air = $Resolved })
} else {
    if ($Recipes -or $BaseAir) { throw 'Recipes y BaseAir requieren AirPath para evitar aplicar archivos de otra ROM.' }
    if (-not (Test-Path -LiteralPath $ResultsRoot -PathType Container)) { throw "No existe $ResultsRoot." }
    foreach ($Id in @('fe7', 'fe8')) {
        if ($Game -ne 'all' -and $Game -ne $Id) { continue }
        $Folder = Join-Path $ResultsRoot $Id
        if (-not (Test-Path -LiteralPath $Folder -PathType Container)) { continue }
        $Containers = New-Object System.Collections.Generic.List[object]
        if ('base' -like $Variant) { $Containers.Add([pscustomobject]@{ Variant = 'base'; Folder = $Folder; Pattern = 'base-*' }) }
        foreach ($Child in @(Get-ChildItem -LiteralPath $Folder -Directory | Sort-Object Name)) {
            if ($Child.Name -like $Variant -and (Test-Path -LiteralPath (Join-Path $Child.FullName "$Id-mod.gba") -PathType Leaf)) {
                $Containers.Add([pscustomobject]@{ Variant = $Child.Name; Folder = $Child.FullName; Pattern = 'analisis-*' })
            }
        }
        foreach ($Container in $Containers) {
            $Candidates = @(Get-ChildItem -LiteralPath $Container.Folder -Directory |
                Where-Object { $_.Name -like $Container.Pattern -and (Test-Path -LiteralPath (Join-Path $_.FullName 'air.json') -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $_.FullName 'resources') -PathType Container) })
            # Prefer completed, full linear scans. Never silently choose a partial scan over a completed one.
            $Ranked = @($Candidates | ForEach-Object {
                $Air = Get-Content -LiteralPath (Join-Path $_.FullName 'air.json') -Raw -Encoding UTF8 | ConvertFrom-Json
                $Complete = ($Air.scan.truncated -eq $false -and $Air.scan.step -eq 1)
                [pscustomobject]@{ Folder = $_; Complete = [int]$Complete; Count = @($Air.resources).Count }
            } | Sort-Object @{ Expression = 'Complete'; Descending = $true }, @{ Expression = 'Count'; Descending = $true }, @{ Expression = { $_.Folder.LastWriteTimeUtc }; Descending = $true })
            if ($Ranked.Count -gt 0) {
                $Selected = $Ranked[0].Folder.FullName
                Write-Host "Seleccionado $Id / $($Container.Variant): $Selected"
                $Jobs.Add([pscustomobject]@{ Game = $Id; Variant = $Container.Variant; Air = (Join-Path $Selected 'air.json') })
            }
        }
    }
}
if ($Jobs.Count -eq 0) { throw 'No se encontraron AIR con resources. Usa AirPath para elegir un informe exacto.' }
$Rows = New-Object System.Collections.Generic.List[object]
$Failed = $false
$Partial = $false
$PSNativeCommandUseErrorActionPreference = $false
Push-Location -LiteralPath $ProjectRoot
try {
    $Version = (& $Python -c 'import arcanacart; print(arcanacart.__version__)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [version]$Version -lt [version]'0.5.1') { throw 'Aplica ArcanaCart 0.5.1 antes de interpretar.' }
    $JobNumber = 0
    foreach ($Job in $Jobs) {
        $JobNumber++
        Write-Host "[$JobNumber/$($Jobs.Count)] Interpretando $($Job.Game) / $($Job.Variant)"
        $Parent = Split-Path -Parent $Job.Air
        $Out = Join-Path $Parent ('interpretacion-' + $Version + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
        try {
            $Arguments = @('-m', 'arcanacart', 'interpret', '--input', $Job.Air, '--out', $Out,
                '--max-previews', [string]$MaxPreviews, '--byte-budget', [string]([long]$ByteBudgetMiB * 1048576),
                '--pixel-budget', [string]([long]$PixelBudgetMi * 1048576))
            if ($Recipes) { $Arguments += @('--recipes', $Recipes) }
            if ($BaseAir) { $Arguments += @('--base', $BaseAir) }
            $Text = (& $Python @Arguments | Out-String)
            $Code = $LASTEXITCODE
            if ($Code -notin @(0, 3)) { throw "Interpretacion termino con codigo $Code." }
            $State = $Text | ConvertFrom-Json
            if ($Code -eq 3) { $Partial = $true }
            $Rows.Add([pscustomobject]@{ Juego = $Job.Game; Variante = $Job.Variant; Estado = $State.status; Candidatos = $State.candidates; BloquesUnicos = $State.unique_blobs; PNG = $State.generated_png_files; Aceptados = $State.identified_by_user_review; Pendientes = $State.pending_interpretation; Galeria = $State.gallery; Detalle = '' })
        } catch {
            $Failed = $true
            $Rows.Add([pscustomobject]@{ Juego = $Job.Game; Variante = $Job.Variant; Estado = 'error'; Candidatos = $null; BloquesUnicos = $null; PNG = $null; Aceptados = $null; Pendientes = $null; Galeria = ''; Detalle = $_.Exception.Message })
            Write-Warning "$($Job.Variant): $($_.Exception.Message)"
        }
    }
    $SummaryParent = if ($AirPath) { Split-Path -Parent $Jobs[0].Air } else { $ResultsRoot }
    $Summary = Join-Path $SummaryParent ('resumen-interpretacion-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6) + '.csv')
    $Rows | Export-Csv -LiteralPath $Summary -NoTypeInformation -Encoding UTF8
    $Rows | Format-Table Juego, Variante, Estado, Candidatos, PNG, Pendientes -AutoSize
    Write-Host "Resumen: $Summary"
    Write-Host 'Cada galeria index.html funciona localmente. Revisa el resumen para limites o errores.'
} finally { Pop-Location }
if ($Failed) { exit 2 }
if ($Partial) { exit 3 }
exit 0
