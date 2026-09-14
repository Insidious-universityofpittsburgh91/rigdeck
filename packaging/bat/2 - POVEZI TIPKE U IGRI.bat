@echo off
rem Run this once after the game has seen vJoy for the first time -- and again any time
rem the game resets your controls. The game must be closed. No administrator rights: it
rem only touches your own profile under Documents, and keeps a backup of it.
title Rig Deck - bind the buttons
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\bind.ps1"
echo.
pause
