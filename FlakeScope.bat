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

:: ── Install / repair dependencies ─────────────────────────────────────────────
if not exist ".venv\Scripts\flakescope.ready" (
    echo.
    echo   Installing required packages (one-time setup, ~2-3 minutes)...
    echo   Please keep your internet connection active.
    echo.

    .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    .venv\Scripts\pip.exe uninstall opencv-python-headless -y >nul 2>&1
    .venv\Scripts\pip.exe install PyQt5 opencv-python numpy scikit-image

    if errorlevel 1 (
        echo.
        echo   ============================================================
        echo   ERROR: Package installation failed.
        echo   ============================================================
        echo.
        echo   Possible causes:
        echo     - No internet connection
        echo     - Firewall or proxy blocking pip
        echo.
        echo   Fix: connect to the internet, delete the .venv folder,
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
echo   Launching FlakeScope...
echo.
echo   (This window will close automatically — the app opens separately.)
echo.

:: Use pythonw.exe (GUI subsystem) so the app runs independently of this window.
:: 'start "" /b' detaches python from the CMD console so closing CMD won't kill it.
start "" /b .venv\Scripts\pythonw.exe main.py

:: Give the app 2 seconds to start, then let this window close on its own.
:: If pythonw.exe is missing (shouldn't happen), fall back to regular python.exe.
if errorlevel 1 (
    echo   WARNING: pythonw.exe failed, trying python.exe...
    start "" /b .venv\Scripts\python.exe main.py
)

timeout /t 2 /nobreak >nul
endlocal
