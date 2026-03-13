@echo off
setlocal
cd /d "%~dp0"
title ALAUTO

set "PYTHON_EXE="
set "CONDA_EXE="
for %%I in (python.exe) do (
    if not defined PYTHON_EXE (
        for /f "delims=" %%J in ('where %%I 2^>nul') do (
            if not defined PYTHON_EXE set "PYTHON_EXE=%%~J"
        )
    )
)

if defined PYTHON_EXE (
    "%PYTHON_EXE%" -c "import cv2, numpy, scipy, imutils, lz4, keyboard" >nul 2>nul
    if not errorlevel 1 goto run_system_python
)

for %%I in ("%USERPROFILE%\anaconda3\Scripts\conda.exe" "%USERPROFILE%\miniconda3\Scripts\conda.exe") do (
    if not defined CONDA_EXE if exist "%%~I" set "CONDA_EXE=%%~I"
)

if not defined CONDA_EXE (
    for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
        if not defined CONDA_EXE set "CONDA_EXE=%%~I"
    )
)

if not defined CONDA_EXE (
    echo No usable Python environment was found.
    echo Install the required packages for your system Python or set up the azurlane Conda environment.
    pause
    exit /b 1
)

goto run_conda

:run_system_python
where git >nul 2>nul
if not errorlevel 1 git pull

:run_loop
"%PYTHON_EXE%" macro_viewer.py
set "EXITCODE=%ERRORLEVEL%"
echo.
echo macro_viewer.py exited with code %EXITCODE%.
echo Restarting in 3 seconds. Press Ctrl+C to close this window.
timeout /t 3 >nul
goto run_loop

:run_conda
where git >nul 2>nul
if not errorlevel 1 git pull

:run_conda_loop
"%CONDA_EXE%" run --live-stream -n azurlane python macro_viewer.py
set "EXITCODE=%ERRORLEVEL%"
echo.
echo macro_viewer.py exited with code %EXITCODE%.
echo Restarting in 3 seconds. Press Ctrl+C to close this window.
timeout /t 3 >nul
goto run_conda_loop
