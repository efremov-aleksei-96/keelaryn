@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -Doctor
set "EC=%ERRORLEVEL%"
echo.
pause
exit /b %EC%
