@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found in PATH.
    echo Install Python 3.9 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

echo [Clausage] Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo.
echo [Clausage] Registering startup launcher...
python "%~dp0_setup_startup.py"
if errorlevel 1 (
    echo.
    echo ERROR: Could not write startup entry.
    pause
    exit /b 1
)

echo.
echo [Clausage] Done! Clausage will start automatically on your next login.
echo To start it right now, run:
echo   python "%~dp0tray.py"
echo.
pause
