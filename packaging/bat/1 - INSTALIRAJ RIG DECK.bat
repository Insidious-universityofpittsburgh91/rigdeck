@echo off
rem Double-click this. It asks for administrator rights once -- the vJoy driver, the
rem plugin in the game folder and the firewall rule all need them -- and then does the
rem whole installation on its own.
title Rig Deck - install
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   Asking for administrator rights...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\setup.ps1"
echo.
pause
