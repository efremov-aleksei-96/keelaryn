@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -BuildRelease
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" pause
exit /b %EC%
