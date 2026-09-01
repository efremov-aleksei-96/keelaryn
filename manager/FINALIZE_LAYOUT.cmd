@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -FinalizeLayout
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo Keelaryn Manager: legacy layout archived.) else (echo Keelaryn Manager: layout finalization exited with code %RC%.)
pause
exit /b %RC%
