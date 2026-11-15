@echo off
setlocal
title Bridge Insight - Launcher
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "bridge_status=%ERRORLEVEL%"
if not "%bridge_status%"=="0" (
    echo.
    echo Bridge Insight could not start. See the error above.
    pause
)
exit /b %bridge_status%
