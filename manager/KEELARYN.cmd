@echo off
setlocal
title Keelaryn Manager
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0product\tools\KeelarynMenu.ps1" -Action Menu
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" pause
exit /b %RC%
