@echo off
echo === MouseWatch Install ===
echo.

REM Build first
call build.bat
if errorlevel 1 exit /b 1

set "INSTALL_DIR=%LOCALAPPDATA%\MouseWatch"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo.
echo Installing to %INSTALL_DIR%...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
copy /y "dist\MouseWatch.exe" "%INSTALL_DIR%\MouseWatch.exe"
if errorlevel 1 (
    echo ERROR: Failed to copy executable.
    pause
    exit /b 1
)

echo Creating startup shortcut...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP%\MouseWatch.lnk'); $s.TargetPath = '%INSTALL_DIR%\MouseWatch.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'MouseWatch - MCHOSE Battery Monitor'; $s.Save()"
if errorlevel 1 (
    echo ERROR: Failed to create startup shortcut.
    pause
    exit /b 1
)

echo.
echo MouseWatch installed successfully!
echo   Executable: %INSTALL_DIR%\MouseWatch.exe
echo   Startup:    %STARTUP%\MouseWatch.lnk
echo.
echo MouseWatch will start automatically on next login.
echo You can also run it now from: %INSTALL_DIR%\MouseWatch.exe
pause
