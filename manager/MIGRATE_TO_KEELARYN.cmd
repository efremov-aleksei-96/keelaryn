@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -MigrateLegacyNamespace
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo Keelaryn__Manager: namespace migration complete.) else (echo Keelaryn__Manager: namespace migration exited with code %RC%.)
pause
exit /b %RC%
