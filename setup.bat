@echo off
setlocal EnableExtensions
title SKYZEN - Setup
cd /d "%~dp0"

echo.
echo ==========================================
echo   SKYZEN - Environment Setup
echo ==========================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version
    if errorlevel 1 goto :python_error
    py -3 -m venv .venv
) else (
    where python >nul 2>nul
    if errorlevel 1 goto :python_error
    python --version
    python -m venv .venv
)
if errorlevel 1 (
    echo [ERROR] Could not create .venv.
    goto :fail
)

echo.
echo [1/2] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo.
echo [2/2] Installing Skyzen Python requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Setup completed.
echo Install FFmpeg and FFprobe separately and ensure both commands work:
echo   ffmpeg -version
echo   ffprobe -version
echo.
echo Next, double-click run.bat or silent.vbs to launch Skyzen.
pause
exit /b 0

:python_error
echo [ERROR] Python 3 was not found.
echo Install Python 3.10 or newer and enable the Python launcher or PATH option.
goto :fail

:fail
echo.
echo Setup failed. Read the error above, then try again.
pause
exit /b 1
