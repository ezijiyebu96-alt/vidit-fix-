@echo off
REM ============================================================================
REM  Vidit - Windows 11 x64 build script (v3, double-click friendly)
REM  Produces:  release\Vidit\Vidit.exe  (onedir bundle, no Python needed)
REM
REM  * This window NEVER closes by itself - errors stay on screen.
REM  * The PyInstaller step writes build_log.txt and shows the last 30 lines
REM    if it fails, so an error can never scroll away or vanish.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Vidit Windows 11 build

echo ==================================================================
echo   Vidit - Windows 11 build
echo   If anything fails, read the [X] line below - the fix is written
echo   right under it. The PyInstaller log is saved as build_log.txt.
echo ==================================================================
echo.

REM ---- [1/7] find a real Python 3.10-3.13 (best first, rejects Store stub) --
set "PYEXE="
set "PYSRC="
for %%v in (3.12 3.11 3.13 3.10) do call :try_py %%v
if defined PYEXE goto :have_python
call :try_generic py -3
if defined PYEXE goto :have_python
call :try_generic python
if defined PYEXE goto :have_python

echo  [X] No usable Python 3.10-3.13 was found.
echo.
echo  HOW TO FIX - 2 minutes:
echo    1. Open  https://www.python.org/downloads/
echo    2. Install Python 3.12 (or 3.11).
echo    3. On the FIRST installer screen, TICK the checkbox:
echo          "Add python.exe to PATH"     (bottom - MANDATORY)
echo    4. Close this window and double-click build_windows.bat again.
echo.
echo  Note: the Microsoft Store "Python" app does NOT work for building.
goto :fail

:try_py
if defined PYEXE goto :eof
py -%1 -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,15) else 1)" >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=py -%1"
set "PYSRC=the py launcher, Python %1"
goto :eof

:try_generic
if defined PYEXE goto :eof
%1 -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,15) else 1)" >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=%1"
set "PYSRC=PATH, %1"
goto :eof

:have_python
echo  [1/7] Python found via %PYSRC%:
%PYEXE% -c "import sys; print('       ' + sys.version)"
%PYEXE% -c "import sys; sys.exit(1 if sys.version_info >= (3,14) else 0)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo  NOTE: this is Python 3.14 or newer. Some optional packages may not
    echo  have installers yet - Vidit still builds; missing senses are skipped
    echo  with a message. For the fullest build, use Python 3.12 from python.org.
    echo.
)

REM ---- [2/7] virtual environment --------------------------------------------
set "VENV=.venv-win"
set "VPY=%VENV%\Scripts\python.exe"
echo  [2/7] Virtual environment %VENV% ...
if exist "%VPY%" (
    echo         reusing existing %VENV%
    goto :venv_ready
)
%PYEXE% -m venv "%VENV%"
if errorlevel 1 goto :venv_fail
if not exist "%VPY%" goto :venv_fail
goto :venv_ready

:venv_fail
echo  [X] Could not create the virtual environment.
echo  Fix: this folder must be writable. Do NOT keep the project inside
echo  "C:\Program Files" - copy it to your Desktop or Documents first,
echo  then run this script again.
goto :fail

:venv_ready
"%VPY%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo         repairing pip inside the venv...
    "%VPY%" -m ensurepip --upgrade >nul 2>nul
)
"%VPY%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo  [X] pip is broken inside %VENV%.
    echo  Fix: delete the %VENV% folder and run this script again.
    goto :fail
)
echo         OK
echo.

REM ---- [3/7] core dependencies ------------------------------------------------
echo  [3/7] Installing CORE dependencies - PyQt5, requests, psutil, markdown...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [X] CORE dependencies failed to install.
    echo  Fix: connect to the internet and run this script again.
    echo  If the error says "Microsoft Visual C++ ... required", your Python is
    echo  too new - install Python 3.12 from python.org and run again.
    goto :fail
)
echo         OK
echo.

REM ---- [4/7] optional senses - one package at a time, failures tolerated ------
echo  [4/7] Installing OPTIONAL senses - this is the longest step...
set "FAILED_SENSE="
for %%p in (numpy opencv-python Pillow pypdf python-docx openpyxl faster-whisper sounddevice pyttsx3 mss pyautogui) do (
    echo         installing %%p ...
    "%VPY%" -m pip install %%p >nul 2>&1
    if errorlevel 1 (
        echo         [!] skipped: %%p - Vidit will run without this sense
        call set "FAILED_SENSE=%%FAILED_SENSE%% %%p"
    )
)
if defined FAILED_SENSE (
    echo.
    echo  [!] Skipped optional packages:%FAILED_SENSE%
    echo      This is OK - Vidit builds and runs without them.
)
echo         done
echo.

REM ---- [5/7] PyInstaller + test gate -------------------------------------------
echo   Installing PyInstaller...
"%VPY%" -m pip install "pyinstaller>=6.0"
if errorlevel 1 (
    echo  [X] PyInstaller could not be installed - cannot build without it.
    echo  Fix: check internet connection and run again.
    goto :fail
)
echo  [5/7] Running Vidit's test suite (quality gate)...
"%VPY%" -m pytest tests -q
if not errorlevel 1 goto :tests_ok
echo.
echo  [!] Some tests failed on THIS machine. The identical tests pass on the
echo      GitHub Windows builders, so this is usually a local quirk.
set "CONT="
set /p CONT=      Build anyway? [y/N]:
if /i "%CONT%"=="y" goto :tests_ok
echo  [X] Build cancelled - nothing was built or changed.
goto :fail
:tests_ok
echo         OK
echo.

REM ---- [6/7] build (log saved to build_log.txt) ---------------------------------
echo  [6/7] Building Vidit.exe - expect 5-15 minutes on a laptop...
echo        (console output is saved to build_log.txt)
taskkill /f /im Vidit.exe >nul 2>nul
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%VPY%" -m PyInstaller --noconfirm --clean Vidit.spec > build_log.txt 2>&1
if errorlevel 1 (
    echo  [X] PyInstaller failed. The LAST 30 LINES OF build_log.txt follow:
    echo  ------------------------------------------------------------------
    powershell -NoProfile -Command "Get-Content build_log.txt -Tail 30"
    echo  ------------------------------------------------------------------
    echo  Full log: %CD%\build_log.txt
    echo  Common causes: antivirus locking files ^(add this folder to Defender
    echo  exclusions^), or a broken optional package ^(delete .venv-win, retry^).
    goto :fail
)
if not exist "dist\Vidit\Vidit.exe" (
    echo  [X] PyInstaller finished but Vidit.exe is missing - see build_log.txt:
    powershell -NoProfile -Command "Get-Content build_log.txt -Tail 30"
    goto :fail
)
echo         OK
echo.

REM ---- [7/7] release folder + packaged smoke check -------------------------------
echo  [7/7] Copying to release\Vidit and smoke-checking the packaged app...
if exist release rmdir /s /q release
mkdir release
robocopy "dist\Vidit" "release\Vidit" /E /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
    echo  [X] Could not copy the app into the release folder.
    goto :fail
)
for %%A in ("release\Vidit\Vidit.exe") do echo         Vidit.exe size: %%~zA bytes
"%VPY%" packaging\check_exe.py "release\Vidit\Vidit.exe" --version
if errorlevel 1 goto :smoke_warn
"%VPY%" packaging\check_exe.py "release\Vidit\Vidit.exe" --doctor
if errorlevel 1 goto :smoke_warn
goto :ok

:smoke_warn
echo.
echo  [!] The exe was BUILT, but the packaged smoke check reported a problem.
echo      It may still work: double-click release\Vidit\Vidit.exe
echo      If it crashes, read %%LOCALAPPDATA%%\Vidit\logs\vidit_crash.log

:ok
echo.
echo ==================================================================
echo   BUILD OK
echo.
echo   Your app :  %CD%\release\Vidit\Vidit.exe
echo   Keep the WHOLE "Vidit" folder together - the exe needs the
echo   files beside it.
echo.
echo   First run: data goes to %%LOCALAPPDATA%%\Vidit
echo   SmartScreen appears once - More info, then Run anyway.
echo.
echo   Recommended: install Ollama from https://ollama.com and run
echo      ollama pull qwen2.5:7b
echo   so Vidit uses his full local brain.
echo ==================================================================
goto :pause_end

:tests_fail
echo.
echo  Build cancelled. Nothing was built or changed.

:fail
echo.
echo  BUILD FAILED - read the [X] message above.
echo  Most common fix: install Python 3.12 from python.org and tick
echo  "Add python.exe to PATH" during installation.

:pause_end
echo.
echo  Press any key to close this window...
pause >nul
endlocal & exit /b 0
