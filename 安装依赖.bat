@echo off
setlocal
title Bridge Insight - Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
set "bridge_status=%ERRORLEVEL%"
if not "%bridge_status%"=="0" (
    echo.
    echo Setup could not finish. See the error above.
)
pause
exit /b %bridge_status%
