@echo off
REM Wake Vidit up (GUI). Add --cli for the terminal version.
cd /d "%~dp0"
if exist .venv-win\Scripts\activate.bat call .venv-win\Scripts\activate.bat
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
where pythonw >nul 2>nul
if errorlevel 1 (
    echo Python is not set up yet.
    echo Double-click setup_windows.bat first, then use this file again.
    pause
    exit /b 1
)
start "" /B pythonw -m vidit %*
