@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Keelaryn__Manager.ps1" -OpenOnly
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  pause
)
exit /b %RC%
