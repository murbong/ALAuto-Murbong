@echo off
setlocal
cd /d "%~dp0"
title ALAUTO Legacy Start

where python >nul 2>nul
if errorlevel 1 (
    echo python was not found on PATH.
    echo Add Python to PATH and install requirements with: pip install -r requirements.txt
    pause
    exit /b 1
)

python -c "import cv2, numpy, scipy, imutils, lz4, keyboard" >nul 2>nul
if errorlevel 1 (
    echo Required packages are missing. Installing from requirements.txt...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install requirements.
        pause
        exit /b 1
    )
)

where git >nul 2>nul
if not errorlevel 1 git pull

:run_loop
python macro_viewer.py
set "EXITCODE=%ERRORLEVEL%"
echo.
echo macro_viewer.py exited with code %EXITCODE%.
echo Restarting in 3 seconds. Press Ctrl+C to close this window.
timeout /t 3 >nul
goto run_loop
