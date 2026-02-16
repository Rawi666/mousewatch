@echo off
echo === MouseWatch Uninstall ===
echo.

set "INSTALL_DIR=%LOCALAPPDATA%\MouseWatch"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo Removing startup shortcut...
if exist "%STARTUP%\MouseWatch.lnk" del "%STARTUP%\MouseWatch.lnk"

echo Removing install directory...
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"

echo.
echo MouseWatch uninstalled successfully.
pause
