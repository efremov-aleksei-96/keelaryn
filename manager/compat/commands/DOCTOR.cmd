@echo off
setlocal
rem Keelaryn generated compatibility command
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\product\runtime\Keelaryn__Manager.ps1" -Doctor
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
