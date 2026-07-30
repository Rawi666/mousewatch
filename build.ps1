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

$exitCode = 0
Push-Location $scriptDir

try {
    Write-Host "=== MouseWatch Build ==="
    Write-Host ""

    Write-Host "Creating/updating virtual environment..."
    & (Join-Path $scriptDir "create_venv.ps1") $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
    }

    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "Python executable not found in virtual environment: $venvPython"
    }

    Write-Host "Installing development/build dependencies from requirements-dev.txt..."
    & $venvPython -m pip install -r (Join-Path $scriptDir "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install development/build dependencies."
    }

    Write-Host ""
    Write-Host "Running test suite..."
    & $venvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed. Aborting build."
    }

    Write-Host ""
    Write-Host "Building MouseWatch.exe..."
    & $venvPython -m PyInstaller --onefile --noconsole --name MouseWatch src\mousewatch\mousewatch.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    Write-Host ""
    Write-Host "Build complete: dist\MouseWatch.exe"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    Pop-Location
}

exit $exitCode
