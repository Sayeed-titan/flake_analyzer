@echo off
setlocal
title FlakeScope — Starting...
cd /d "%~dp0"

:: ── Find Python ──────────────────────────────────────────────────────────────
set PYTHON=
python --version >nul 2>&1
if not errorlevel 1 set PYTHON=python

if "%PYTHON%"=="" (
    py --version >nul 2>&1
    if not errorlevel 1 set PYTHON=py
)

if "%PYTHON%"=="" (
    echo.
    echo ==============================================================
    echo   ERROR: Python was not found on this computer.
    echo ==============================================================
    echo.
    echo   Please install Python 3.8 or newer from:
    echo     https://www.python.org/downloads/
    echo.
    echo   IMPORTANT: During installation check:
    echo     [x]  Add Python to PATH
    echo.
    echo   After installing Python, double-click FlakeScope.bat again.
    echo.
    pause
    exit /b 1
)

:: ── Check Python version (need 3.8+) ─────────────────────────────────────────
for /f "tokens=2" %%v in ('%PYTHON% --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PYMAJ=%%a
    set PYMIN=%%b
)
if %PYMAJ% LSS 3 goto :old_python
if %PYMAJ% EQU 3 if %PYMIN% LSS 8 goto :old_python
goto :python_ok

:old_python
echo.
echo   ERROR: Python %PYVER% is too old. FlakeScope requires Python 3.8+.
echo   Please upgrade at https://www.python.org/downloads/
echo.
pause
exit /b 1

:python_ok

:: ── Create virtual environment ────────────────────────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   First-time setup: creating isolated Python environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo.
        echo   ERROR: Could not create virtual environment.
        echo   Make sure Python is properly installed and try again.
        echo.
        pause
        exit /b 1
    )
    echo   Done.
)

:: ── Install dependencies (once) ───────────────────────────────────────────────
if not exist ".venv\Scripts\flakescope.ready" (
    echo.
    echo   Installing required packages (one-time setup, ~2-3 minutes)...
    echo   Please wait and keep your internet connection active.
    echo.
    .venv\Scripts\python -m pip install --quiet --upgrade pip
    .venv\Scripts\pip install --quiet PyQt5 opencv-python numpy scikit-image
    if errorlevel 1 (
        echo.
        echo   ERROR: Package installation failed.
        echo.
        echo   Possible causes:
        echo     - No internet connection
        echo     - Firewall or proxy blocking pip
        echo.
        echo   Fix: connect to the internet and delete the .venv folder,
        echo   then double-click FlakeScope.bat to retry.
        echo.
        pause
        exit /b 1
    )
    echo 1 > ".venv\Scripts\flakescope.ready"
    echo.
    echo   All packages installed successfully!
    echo.
)

:: ── Launch ────────────────────────────────────────────────────────────────────
title FlakeScope — Graphene / hBN Analyzer
cls
echo   Launching FlakeScope...
.venv\Scripts\python main.py
set EXIT_CODE=%errorlevel%
if %EXIT_CODE% neq 0 (
    echo.
    echo   FlakeScope exited with an error (code %EXIT_CODE%).
    echo   Check the output above for details.
    echo.
    echo   If you see "ModuleNotFoundError", delete the .venv folder
    echo   and double-click FlakeScope.bat to reinstall packages.
    echo.
    pause
)
endlocal
