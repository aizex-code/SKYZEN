@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Skyzen environment not found. Run setup.bat first.
    pause
    exit /b 1
)

if exist "%SystemRoot%\System32\wscript.exe" (
    start "" "%SystemRoot%\System32\wscript.exe" "%~dp0silent.vbs"
    exit /b 0
)

echo Windows Script Host is unavailable. Launching with a console instead.
".venv\Scripts\python.exe" "%~dp0main.py"
pause
