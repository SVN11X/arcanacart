<#
Extract only the documented raw item-icon bank. Uses the local Python package;
does not install dependencies, scan ROMs, patch inputs or repeat face extraction.
#>
[CmdletBinding()]
param(
    [string]$Datos = 'C:\FireEmblem',
    [ValidateSet('fe7', 'fe8', 'ambos')]
    [string]$Game = 'ambos',
    [string]$RomPath = '',
    [string]$AirPath = '',
    [string]$Definition = '',
    [string]$OutputParent = '',
    [string]$PythonExe = 'C:\FireEmblem\entorno-arcanacart\Scripts\python.exe',
    [switch]$CrearZip,
    [switch]$Abrir
)

. (Join-Path $PSScriptRoot 'ArcanaCart.Common.ps1')
$PSNativeCommandUseErrorActionPreference = $false
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).ProviderPath
$Python = Get-ArcanaPython -Requested $PythonExe
if ($Game -eq 'ambos' -and ($RomPath -or $AirPath -or $Definition)) {
    throw 'Con rutas especificas usa -Game fe7 o -Game fe8. El modo ambos usa las dos bases locales.'
}
if (-not $OutputParent) { $OutputParent = Join-Path $Datos 'resultados' }
$Games = @('fe7', 'fe8')
if ($Game -ne 'ambos') { $Games = @($Game) }
$Jobs = @()
foreach ($SelectedGame in $Games) {
    $SelectedRom = $RomPath
    if (-not $SelectedRom) {
        $SelectedRom = Join-Path $Datos "resultados\$SelectedGame\$SelectedGame-usa-base.gba"
    }
    if (-not (Test-Path -LiteralPath $SelectedRom -PathType Leaf)) {
        throw "No se encuentra la ROM de $SelectedGame. Indica -Game $SelectedGame -RomPath con su ruta exacta: $SelectedRom"
    }
    $Jobs += [pscustomobject]@{
        Game = $SelectedGame
        Rom = (Resolve-Path -LiteralPath $SelectedRom).ProviderPath
    }
}
foreach ($OptionalInput in @($AirPath, $Definition)) {
    if ($OptionalInput -and -not (Test-Path -LiteralPath $OptionalInput -PathType Leaf)) {
        throw "No se encuentra: $OptionalInput"
    }
}
if ($AirPath) { $AirPath = (Resolve-Path -LiteralPath $AirPath).ProviderPath }
if ($Definition) { $Definition = (Resolve-Path -LiteralPath $Definition).ProviderPath }
$Out = Join-Path $OutputParent (
    'iconos-' + $Game + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' +
    [guid]::NewGuid().ToString('N').Substring(0, 6)
)
if (Test-Path -LiteralPath $Out) { throw "La carpeta de salida ya existe: $Out" }
$Rows = @()
Push-Location -LiteralPath $ProjectRoot
try {
    & $Python -c 'from arcanacart.icons import extract_icons'
    if ($LASTEXITCODE -ne 0) { throw 'No se encuentra el modulo de iconos. Aplica el parche 0.6.4 en este repositorio.' }

    # Validate every input and bounded range before creating the batch output.
    foreach ($Job in $Jobs) {
        $CheckArgs = @('-m', 'arcanacart', 'icons', '--rom', $Job.Rom, '--out', (Join-Path $Out $Job.Game), '--dry-run')
        if ($AirPath) { $CheckArgs += @('--input', $AirPath) }
        if ($Definition) { $CheckArgs += @('--definition', $Definition) }
        Write-Host "Comprobando ROM, punteros y rango: $($Job.Game)"
        $Text = (& $Python @CheckArgs | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "No se valido $($Job.Game). Se conserva cualquier extraccion anterior." }
        $Plan = $Text | ConvertFrom-Json
        if ($Plan.status -ne 'planned' -or $Plan.game -ne $Job.Game) {
            throw 'La ROM o definicion no corresponde al juego seleccionado.'
        }
    }

    $null = New-Item -ItemType Directory -Path $Out
    $Utf8 = New-Object System.Text.UTF8Encoding($false)
    $RunState = Join-Path $Out 'run-state.json'
    [System.IO.File]::WriteAllText($RunState, '{"status":"running","rescanned":false}', $Utf8)
    try {
        foreach ($Job in $Jobs) {
            $Arguments = @('-m', 'arcanacart', 'icons', '--rom', $Job.Rom, '--out', (Join-Path $Out $Job.Game))
            if ($AirPath) { $Arguments += @('--input', $AirPath) }
            if ($Definition) { $Arguments += @('--definition', $Definition) }
            Write-Host "Extrayendo iconos: $($Job.Game)"
            $Text = (& $Python @Arguments | Out-String)
            if ($LASTEXITCODE -ne 0) { throw "La extraccion de $($Job.Game) no termino correctamente." }
            $Result = $Text | ConvertFrom-Json
            if ($Result.status -ne 'completed') { throw "Estado inesperado: $($Result.status)" }
            $Rows += $Result
            Write-Host "IDs: $($Result.icon_occurrences); PNG unicos: $($Result.unique_images); transparentes: $($Result.transparent_occurrences)."
            Write-Host "Galeria: $($Result.gallery)"
        }
        $Summary = [ordered]@{
            format = 'arcanacart-item-icon-batch-1'
            status = 'completed'
            games = $Rows.Count
            icon_occurrences = ($Rows | Measure-Object -Property icon_occurrences -Sum).Sum
            rescanned = $false
            inputs_modified = $false
            results = @($Rows)
        }
        [System.IO.File]::WriteAllText(
            (Join-Path $Out 'resumen.json'), ($Summary | ConvertTo-Json -Depth 12), $Utf8
        )
        [System.IO.File]::WriteAllText($RunState, '{"status":"completed","rescanned":false}', $Utf8)
    } catch {
        [System.IO.File]::WriteAllText($RunState, '{"status":"failed","rescanned":false}', $Utf8)
        throw
    }
    if ($CrearZip) {
        $Zip = $Out + '.zip'
        $PackageText = (& $Python -m arcanacart.icon_package --input $Out --out $Zip | Out-String)
        if ($LASTEXITCODE -ne 0) {
            throw "Los iconos estan en $Out, pero no se pudo crear el ZIP portable. No repitas la extraccion."
        }
        $PackageResult = $PackageText | ConvertFrom-Json
        if ($PackageResult.status -ne 'completed' -or -not $PackageResult.portable_paths) {
            throw 'El empaquetador no confirmo un ZIP portable.'
        }
        Write-Host "ZIP para revisar: $Zip"
    }
    if ($Abrir) {
        foreach ($Row in $Rows) { Invoke-Item -LiteralPath $Row.gallery }
    }
    Write-Host "Resultados: $Out"
} finally { Pop-Location }
