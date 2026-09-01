@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -Genesis
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo Keelaryn__Manager: Genesis complete.) else (echo Keelaryn__Manager: Genesis exited with code %RC%.)
pause
exit /b %RC%
