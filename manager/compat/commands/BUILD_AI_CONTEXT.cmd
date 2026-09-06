@echo off
setlocal
rem Keelaryn generated compatibility command
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\product\runtime\Keelaryn__Manager.ps1" -BuildAIContext
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
