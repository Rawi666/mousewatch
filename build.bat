@echo off
echo === MouseWatch Build ===
echo.

echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Building MouseWatch.exe...
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name MouseWatch mousewatch.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\MouseWatch.exe
pause
