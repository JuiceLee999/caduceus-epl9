@echo off
title Caduceus firmware builder
cd /d "%~dp0"
set CADUCEUS_LAUNCHER=1
echo Caduceus - E-P7 firmware builder
echo.
where py >nul 2>nul && (py -3 -u caduceus.py & goto done)
where python >nul 2>nul && (python -u caduceus.py & goto done)
echo Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" during install), then double-click this file again.
start "" https://www.python.org/downloads/
:done
echo.
pause
