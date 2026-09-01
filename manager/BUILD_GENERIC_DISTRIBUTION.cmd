@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -BuildDistribution
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo Keelaryn__Manager: distribution build complete.) else (echo Keelaryn__Manager: distribution build exited with code %RC%.)
pause
exit /b %RC%
