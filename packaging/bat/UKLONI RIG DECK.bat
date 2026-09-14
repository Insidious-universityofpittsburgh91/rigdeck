@echo off
rem Removes the shortcuts and the firewall rule. Nothing else is touched -- delete this
rem folder afterwards and Rig Deck is gone.
title Rig Deck - remove
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   Asking for administrator rights...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\uninstall.ps1"
echo.
pause
