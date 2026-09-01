@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -UpdateManager
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo Keelaryn__Manager: Manager update command completed successfully.) else (echo Keelaryn__Manager: Manager update exited with code %RC%.)
pause
exit /b %RC%
