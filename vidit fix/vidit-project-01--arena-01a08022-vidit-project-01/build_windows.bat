@echo off
REM ============================================================================
REM  Vidit - Windows 11 x64 build script
REM  Produces:  release\Vidit\Vidit.exe   (onedir bundle, no Python needed)
REM  Usage:     double-click, or run from a developer command prompt.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ---- pick a Python 3.11+ launcher -----------------------------------------
set "PYTHON=py"
where py >nul 2>nul
if errorlevel 1 set "PYTHON=python"

echo [1/7] Interpreter: %PYTHON%
%PYTHON% --version
if errorlevel 1 goto :fail

set "VENV=.venv-win"
set "VPY=%VENV%\Scripts\python.exe"

echo [2/7] Virtual environment (%VENV%)...
if not exist "%VPY%" (
    %PYTHON% -m venv "%VENV%"
    if errorlevel 1 goto :fail
)

echo [3/7] Installing dependencies (core + senses)...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%VPY%" -m pip install -r requirements.txt -r requirements-senses.txt
if errorlevel 1 goto :fail

echo [4/7] Installing PyInstaller...
"%VPY%" -m pip install "pyinstaller>=6.0"
if errorlevel 1 goto :fail

echo [5/7] Running the test suite (quality gate)...
"%VPY%" -m pytest tests -q
if errorlevel 1 goto :fail

echo [6/7] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [7/7] Building Vidit.exe (onedir)...
"%VPY%" -m PyInstaller --noconfirm --clean Vidit.spec
if errorlevel 1 goto :fail

if not exist "dist\Vidit\Vidit.exe" (
    echo PyInstaller finished but dist\Vidit\Vidit.exe is missing.
    goto :fail
)

set "OUT=release"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"
robocopy "dist\Vidit" "%OUT%\Vidit" /E /NFL /NDL /NJH /NJS >nul
if errorlevel 8 goto :fail

REM ---- packaging self-check: frozen app must answer --doctor cleanly ---------
"%OUT%\Vidit\Vidit.exe" --doctor
if errorlevel 1 (
    echo WARNING: Vidit.exe --doctor reported missing optional deps — check output above.
)

echo.
echo ==========================================================================
echo  BUILD OK
echo  Application: %CD%\%OUT%\Vidit\Vidit.exe
echo  First run creates its data in %LOCALAPPDATA%\Vidit
echo ==========================================================================
exit /b 0

:fail
echo.
echo BUILD FAILED — read the last error above.
exit /b 1
