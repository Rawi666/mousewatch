param(
    [string]$VenvDir = "venv"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([System.IO.Path]::IsPathRooted($VenvDir)) {
    $venvPath = $VenvDir
} else {
    $venvPath = Join-Path $scriptDir $VenvDir
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment at: $venvPath"
    & (Join-Path $scriptDir "create_venv.ps1") $venvPath
}

& $venvPython (Join-Path $scriptDir "src\mousewatch\mousewatch.py")
