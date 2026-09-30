@echo off
cd /d "%~dp0"
title Buzz Pack Studio
if not exist tools\venv\Scripts\python.exe (
    echo Run Install.bat first.
    pause
    exit /b 1
)
echo Buzz Pack Studio is opening in your browser: http://127.0.0.1:8765
echo Keep this window open while you use the app. Close it to stop the app.
echo.
tools\venv\Scripts\python -m buzz_engine studio
pause
