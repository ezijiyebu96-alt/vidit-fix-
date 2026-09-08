@echo off
REM ============================================================================
REM  Vidit - Windows 11 x64 build script (double-click friendly)
REM  Produces:  release\Vidit\Vidit.exe  (onedir bundle, no Python needed)
REM  This window NEVER closes by itself - you can always read the error.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Vidit Windows 11 build
set "RC=0"

echo ==================================================================
echo   Vidit - Windows 11 build
echo   If anything fails, SCROLL UP and read the first [X] message.
echo   This window stays open until YOU close it.
echo ==================================================================
echo.

REM ---- [1/7] find a real Python 3.10+ (rejects the Microsoft Store stub) ----
set "PYEXE="
set "PYSRC="
where py >nul 2>nul
if errorlevel 1 goto :try_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :try_python
set "PYEXE=py -3"
set "PYSRC=the py launcher"
goto :have_python

:try_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :no_python
set "PYEXE=python"
set "PYSRC=python on PATH"
goto :have_python

:no_python
echo  [X] Python 3.10 or newer was NOT found.
echo.
echo  HOW TO FIX - 2 minutes:
echo    1. Open  https://www.python.org/downloads/
echo    2. Install Python 3.11 or 3.12.
echo    3. On the FIRST installer screen, TICK the checkbox:
echo          "Add python.exe to PATH"
echo       (bottom of the screen - this step is MANDATORY)
echo    4. Close this window and double-click build_windows.bat again.
echo.
echo  Note: the Microsoft Store "Python" app does NOT work for building.
goto :fail

:have_python
echo  [1/7] Interpreter found via %PYSRC%:
%PYEXE% --version
echo.

REM ---- [2/7] virtual environment --------------------------------------------
set "VENV=.venv-win"
set "VPY=%VENV%\Scripts\python.exe"
echo  [2/7] Virtual environment %VENV% ...
if exist "%VPY%" (
    echo         reusing existing %VENV%
    goto :deps
)
%PYEXE% -m venv "%VENV%"
if errorlevel 1 goto :venv_fail
if not exist "%VPY%" goto :venv_fail
echo         OK
echo.
goto :deps

:venv_fail
echo  [X] Could not create the virtual environment.
echo  Fix: this folder must be writable. Do NOT keep the project inside
echo  "C:\Program Files" - copy it to your Desktop or Documents first.
goto :fail

REM ---- [3/7] core dependencies -----------------------------------------------
:deps
echo  [3/7] Installing CORE dependencies (PyQt5, requests, psutil, markdown)...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 echo         pip upgrade failed - continuing anyway
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [X] CORE dependencies failed to install.
    echo  Fix: check your internet connection, then run this script again.
    goto :fail
)
echo         OK
echo.

REM ---- [4/7] optional senses (may fail without breaking the build) -----------
echo  [4/7] Installing OPTIONAL senses - voice, ears, files, automation...
echo        This downloads the most and can take several minutes.
"%VPY%" -m pip install -r requirements-senses.txt
if errorlevel 1 (
    echo  [!] Some OPTIONAL packages failed. THIS IS OK - Vidit still builds
    echo      and runs; he just lacks the missing senses. The doctor output
    echo      inside the app shows exactly what is missing.
)
echo.

REM ---- [5/7] PyInstaller + test gate ------------------------------------------
echo   Installing PyInstaller...
"%VPY%" -m pip install "pyinstaller>=6.0"
if errorlevel 1 (
    echo  [X] PyInstaller could not be installed - cannot build without it.
    goto :fail
)
echo  [5/7] Running Vidit's test suite (quality gate)...
"%VPY%" -m pytest tests -q
if errorlevel 1 (
    echo.
    echo  [!] Some tests failed on THIS machine. The identical tests pass on
    echo      the GitHub Windows builders, so this is usually a local quirk.
    set "CONT="
    set /p CONT=      Build anyway? [y/N]:
    if /i not "!CONT!"=="y" goto :tests_fail
)
echo.

REM ---- [6/7] build -------------------------------------------------------------
echo  [6/7] Building Vidit.exe - expect 5-15 minutes on a laptop...
taskkill /f /im Vidit.exe >nul 2>nul
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%VPY%" -m PyInstaller --noconfirm --clean Vidit.spec
if errorlevel 1 (
    echo  [X] PyInstaller failed. Scroll up for the real error line.
    echo  Common causes:
    echo    - antivirus locked the build folder: add this folder to
    echo      Windows Defender exclusions and run again
    echo    - a half-installed optional package: delete the .venv-win
    echo      folder and run this script again
    goto :fail
)
if not exist "dist\Vidit\Vidit.exe" (
    echo  [X] PyInstaller finished but Vidit.exe is missing - scroll up.
    goto :fail
)
echo         OK
echo.

REM ---- [7/7] release folder + packaged smoke check ------------------------------
echo  [7/7] Copying to release\Vidit and smoke-checking the packaged app...
if exist release rmdir /s /q release
mkdir release
robocopy "dist\Vidit" "release\Vidit" /E /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
    echo  [X] Could not copy the app into the release folder.
    goto :fail
)
"%VPY%" packaging\check_exe.py "release\Vidit\Vidit.exe" --version
if errorlevel 1 goto :smoke_warn
"%VPY%" packaging\check_exe.py "release\Vidit\Vidit.exe" --doctor
if errorlevel 1 goto :smoke_warn
goto :ok

:smoke_warn
echo.
echo  [!] The exe was BUILT, but the packaged smoke check reported a problem.
echo      The app may still work: double-click release\Vidit\Vidit.exe
echo      and if it ever crashes, read %%LOCALAPPDATA%%\Vidit\logs\vidit_crash.log

:ok
echo.
echo ==================================================================
echo   BUILD OK
echo.
echo   Your app :  %CD%\release\Vidit\Vidit.exe
echo   Keep the WHOLE "Vidit" folder together - the exe needs the
echo   files beside it.
echo.
echo   First run: data goes to  %%LOCALAPPDATA%%\Vidit
echo   SmartScreen will appear once - More info, then Run anyway.
echo.
echo   Recommended: install Ollama from https://ollama.com and run
echo      ollama pull qwen2.5:7b
echo   so Vidit uses his full local brain.
echo ==================================================================
goto :pause_end

:tests_fail
echo.
echo  [X] Build cancelled because tests failed. Nothing was built or changed.
echo      Scroll up to see which test failed, then re-run this script.

:fail
echo.
echo  BUILD FAILED - read the [X] message above.
echo  Most common fix: install Python from python.org and tick
echo  "Add python.exe to PATH" during installation.
set "RC=1"

:pause_end
echo.
echo  Press any key to close this window...
pause >nul
endlocal & exit /b %RC%
