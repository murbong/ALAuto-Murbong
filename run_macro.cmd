@echo off
setlocal
cd /d "%~dp0"
title ALAUTO

set "PYTHON_EXE="
set "PYTHON_LAUNCHER="
set "CONDA_EXE="
set "PYTHON_REASON="

call :try_python_path "python.exe"
call :try_python_launcher py -3.7
call :try_python_path "%LocalAppData%\Programs\Python\Python37\python.exe"
call :try_python_path "%LocalAppData%\Programs\Python\Python37-32\python.exe"
call :try_python_path "%ProgramFiles%\Python37\python.exe"
call :try_python_path "%ProgramFiles%\Python37-32\python.exe"
call :try_python_path "%ProgramFiles(x86)%\Python37\python.exe"
call :try_python_path "%ProgramFiles(x86)%\Python37-32\python.exe"

if defined PYTHON_EXE (
    goto run_system_python
)

if defined PYTHON_LAUNCHER (
    goto run_python_launcher
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
    if defined PYTHON_REASON echo Last Python check failed: %PYTHON_REASON%
    echo Install Python 3.7 with the required packages, add it to PATH, or set up the azurlane Conda environment.
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

:run_python_launcher
where git >nul 2>nul
if not errorlevel 1 git pull

:run_launcher_loop
%PYTHON_LAUNCHER% macro_viewer.py
set "EXITCODE=%ERRORLEVEL%"
echo.
echo macro_viewer.py exited with code %EXITCODE%.
echo Restarting in 3 seconds. Press Ctrl+C to close this window.
timeout /t 3 >nul
goto run_launcher_loop

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

:try_python_path
if defined PYTHON_EXE exit /b 0
if defined PYTHON_LAUNCHER exit /b 0

set "CANDIDATE=%~1"
if /i "%~1"=="python.exe" (
    for /f "delims=" %%J in ('where python.exe 2^>nul') do (
        if not defined PYTHON_EXE if not defined PYTHON_LAUNCHER call :validate_python "%%~J" path
    )
) else (
    if exist "%~1" call :validate_python "%~1" path
)
exit /b 0

:try_python_launcher
if defined PYTHON_EXE exit /b 0
if defined PYTHON_LAUNCHER exit /b 0
where py >nul 2>nul || exit /b 0
call :validate_python "%~1 %~2" launcher
exit /b 0

:validate_python
if /i "%~2"=="launcher" (
    %~1 -c "import cv2, numpy, scipy, imutils, lz4, keyboard" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_LAUNCHER=%~1"
        exit /b 0
    )
) else (
    "%~1" -c "import cv2, numpy, scipy, imutils, lz4, keyboard" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=%~1"
        exit /b 0
    )
)
set "PYTHON_REASON=%~1 is missing one or more required packages: cv2, numpy, scipy, imutils, lz4, keyboard"
exit /b 0
