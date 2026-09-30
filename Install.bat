@echo off
setlocal
cd /d "%~dp0"
title Buzz Toolkit setup
echo.
echo  Buzz Toolkit setup
echo  ==================
echo.

rem --- find Python 3.11 (the py launcher first, then python on PATH) ---
set "PY="
py -3.11 --version >nul 2>&1 && set "PY=py -3.11"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY goto nopython
echo Using %PY%
%PY% --version

rem --- the app: its own environment in tools\venv ---
if not exist tools\venv\Scripts\python.exe (
    echo.
    echo Creating the app environment...
    %PY% -m venv tools\venv || goto fail
)
tools\venv\Scripts\python -m pip install --disable-pip-version-check -q --upgrade pip
tools\venv\Scripts\python -m pip install --disable-pip-version-check -r requirements.txt || goto fail

rem --- ffmpeg ---
tools\venv\Scripts\python -c "import buzz_tools,sys; sys.exit(0 if buzz_tools.find_ffmpeg() else 1)"
if errorlevel 1 (
    echo.
    echo Downloading ffmpeg - free LGPL build, about 100 MB...
    tools\venv\Scripts\python -m buzz_engine setup --get-ffmpeg || goto fail
)

rem --- optional host voice ---
echo.
echo The host voice reads every question aloud in the host's voice.
echo It is a large download - about 6 GB - and works best with an NVIDIA graphics card.
echo You can skip it now and run Install.bat again later.
set "VOICE="
set /p VOICE=Install the host voice? [Y/N]
if /i "%VOICE%"=="Y" call :voice || goto fail

echo.
echo  Setup finished. Double-click "Start Buzz Pack Studio.bat" to open the app.
echo.
pause
exit /b 0

:voice
py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo The host voice needs Python 3.11 exactly - see the README.
    exit /b 1
)
if not exist tools\clone_venv\Scripts\python.exe (
    echo Creating the host voice environment...
    py -3.11 -m venv tools\clone_venv || exit /b 1
)
tools\clone_venv\Scripts\python -m pip install --disable-pip-version-check -q --upgrade pip
tools\clone_venv\Scripts\python -m pip install --disable-pip-version-check -r tools\clone_requirements.txt
exit /b %errorlevel%

:nopython
echo Python 3.11 was not found.
echo.
echo Install it from https://www.python.org/downloads/release/python-3119/
echo  - pick "Windows installer (64-bit)"
echo  - tick "Add python.exe to PATH" on the first screen
echo Then run Install.bat again.
echo.
pause
exit /b 1

:fail
echo.
echo Setup stopped because of the error above. Fix it and run Install.bat again -
echo finished steps are skipped.
echo.
pause
exit /b 1
