@echo off
echo === MouseWatch Build ===
echo.

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "VENV_PATH=%SCRIPT_DIR%\venv"

pushd "%SCRIPT_DIR%"

echo Creating/updating virtual environment...
call "%SCRIPT_DIR%\create_venv.bat" "%VENV_PATH%"
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    goto :fail
)

set "VENV_PY=%VENV_PATH%\Scripts\python.exe"

echo Installing development/build dependencies from requirements-dev.txt...
"%VENV_PY%" -m pip install -r "%SCRIPT_DIR%\requirements-dev.txt"
if errorlevel 1 (
    echo ERROR: Failed to install development/build dependencies.
    goto :fail
)

echo.
echo Building MouseWatch.exe...
"%VENV_PY%" -m PyInstaller --onefile --noconsole --name MouseWatch src\mousewatch\mousewatch.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    goto :fail
)

echo.
echo Build complete: dist\MouseWatch.exe
popd
pause
exit /b 0

:fail
popd
pause
exit /b 1
