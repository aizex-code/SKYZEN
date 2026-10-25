@echo off
setlocal EnableExtensions
title SKYZEN - Debug Launcher
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Environment not found. Run setup.bat first.
    pause
    exit /b 1
)

echo Starting Skyzen with console output enabled...
".venv\Scripts\python.exe" "%~dp0main.py"
set "RESULT=%ERRORLEVEL%"
echo.
echo Skyzen process exited with code %RESULT%.
echo If the app crashed, inspect skyzen-crash.log in this folder.
pause
exit /b %RESULT%
