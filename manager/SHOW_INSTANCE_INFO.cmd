@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -InstanceInfo
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
