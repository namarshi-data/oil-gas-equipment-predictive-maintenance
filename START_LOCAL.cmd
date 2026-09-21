@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project Python environment is missing. See LOCAL_SETUP.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "scripts\launch_local.py" %*
if errorlevel 1 pause
