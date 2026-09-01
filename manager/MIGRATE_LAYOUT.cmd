@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -MigrateLayout
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo Keelaryn Manager: canonical layout activated.) else (echo Keelaryn Manager: layout migration exited with code %RC%.)
pause
exit /b %RC%
