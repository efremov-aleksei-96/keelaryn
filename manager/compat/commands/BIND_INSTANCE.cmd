@echo off
setlocal
rem Keelaryn generated compatibility command
set "TARGET=%~1"
if not defined TARGET set /p "TARGET=Path to Keelaryn__Hub: "
if not defined TARGET exit /b 2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\product\runtime\Keelaryn__Manager.ps1" -BindInstancePath "%TARGET%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
