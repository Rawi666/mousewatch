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

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m venv $venvPath
} else {
    & python -m venv $venvPath
}

& (Join-Path $venvPath "Scripts\python.exe") -m pip install -r (Join-Path $scriptDir "requirements.txt")

Write-Host "Virtual environment created at: $venvPath"
