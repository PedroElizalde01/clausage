@echo off
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

if exist "%STARTUP%\clausage.vbs" (
    del "%STARTUP%\clausage.vbs"
    echo Clausage removed from startup.
) else (
    echo Clausage startup entry not found.
)

echo.
echo If Clausage is currently running, right-click its tray icon and choose Quit.
pause
