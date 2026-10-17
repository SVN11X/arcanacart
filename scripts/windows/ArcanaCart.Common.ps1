# Shared launcher helpers. Compatible with Windows PowerShell 5.1 and PowerShell 7.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ArcanaPython {
    param([string]$Requested = '')
    $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
    if ($Requested) {
        $Command = Get-Command $Requested -ErrorAction SilentlyContinue
        if (-not $Command) { throw "No se encuentra Python: $Requested" }
        $Candidate = $Command.Source
    } else {
        $Candidate = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            $Candidate = Join-Path $ProjectRoot '.venv/bin/python'
        }
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            $Candidate = ''
            foreach ($Name in @('python', 'python3')) {
                $Command = Get-Command $Name -ErrorAction SilentlyContinue
                if ($Command) {
                    & $Command.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
                    if ($LASTEXITCODE -eq 0) { $Candidate = $Command.Source; break }
                }
            }
            if (-not $Candidate) {
                $Launcher = Get-Command py -ErrorAction SilentlyContinue
                if ($Launcher) {
                    $Location = & $Launcher.Source -3 -c 'import sys; print(sys.executable) if sys.version_info >= (3,10) else sys.exit(1)'
                    if ($LASTEXITCODE -eq 0) { $Candidate = [string]($Location | Select-Object -Last 1) }
                }
            }
            if (-not $Candidate) { throw 'Instala Python 3.10+ o indica -PythonExe con su ruta.' }
        }
    }
    & $Candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'ArcanaCart requiere Python 3.10 o posterior.' }
    return $Candidate
}
