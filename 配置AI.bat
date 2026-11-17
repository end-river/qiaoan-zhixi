@echo off
setlocal
set "bridge_env=%~dp0.env"
if not exist "%bridge_env%" (
    copy "%~dp0.env.example" "%bridge_env%" >nul
    if errorlevel 1 (
        echo Could not create .env from .env.example.
        pause
        exit /b 1
    )
)
start "" notepad.exe "%bridge_env%"
