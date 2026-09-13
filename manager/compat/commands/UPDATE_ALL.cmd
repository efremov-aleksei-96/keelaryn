@echo off
setlocal
rem Keelaryn generated compatibility command
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\product\tools\KeelarynMenu.ps1" -Action UpdateAll -NoRootLauncher
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
