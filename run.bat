@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "VENV_DIR=%~1"
if "%VENV_DIR%"=="" set "VENV_DIR=venv"

set "IS_ABSOLUTE=0"
if "%VENV_DIR:~1,1%"==":" set "IS_ABSOLUTE=1"
if "%VENV_DIR:~0,2%"=="\\" set "IS_ABSOLUTE=1"
if "%VENV_DIR:~0,1%"=="\" set "IS_ABSOLUTE=1"

if "%IS_ABSOLUTE%"=="1" (
    set "VENV_PATH=%VENV_DIR%"
) else (
    set "VENV_PATH=%SCRIPT_DIR%\%VENV_DIR%"
)

if not exist "%VENV_PATH%\Scripts\python.exe" (
    echo Creating virtual environment at: %VENV_PATH%
    call "%SCRIPT_DIR%\create_venv.bat" "%VENV_PATH%"
    if errorlevel 1 exit /b 1
)

"%VENV_PATH%\Scripts\python.exe" "%SCRIPT_DIR%\src\mousewatch\mousewatch.py"
exit /b %errorlevel%
