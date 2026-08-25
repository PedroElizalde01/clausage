@echo off
cd /d "%~dp0"

echo [Clausage] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed.
    echo Make sure Python 3 is installed and "pip" is available in PATH.
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
