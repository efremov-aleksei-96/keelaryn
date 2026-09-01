@echo off
setlocal
set "TARGET=%~1"
if not defined TARGET set /p "TARGET=Path to Keelaryn__Hub: "
if not defined TARGET exit /b 2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -BindInstancePath "%TARGET%"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" pause
exit /b %EC%
