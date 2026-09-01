@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -UpdateAll
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo Keelaryn__Manager: Manager + Hub update command completed successfully.) else (echo Keelaryn__Manager: combined update exited with code %RC%.)
pause
exit /b %RC%
