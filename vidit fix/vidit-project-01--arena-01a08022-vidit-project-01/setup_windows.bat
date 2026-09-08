@echo off
REM ============================================================
REM  Vidit - one-time setup for Windows 11 (run once, then use
REM  start_vidit.bat every day)
REM ============================================================
setlocal
cd /d "%~dp0"

set "PYEXE=python"
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"

echo.
echo  [1/5] Checking Python...
%PYEXE% --version >nul 2>nul
if errorlevel 1 (
    echo  Python not found. Install Python 3.12 from https://www.python.org/downloads/
    echo  IMPORTANT: tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)
%PYEXE% --version

echo  [2/5] Creating virtual environment (.venv-win)...
if not exist .venv-win %PYEXE% -m venv .venv-win
call .venv-win\Scripts\activate.bat

echo  [3/5] Installing Vidit's core (body + brain link)...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo  Core install failed - check your internet connection and run again.
    pause
    exit /b 1
)

echo  [4/5] Installing senses (voice, ears, files). Each is optional -
echo        failures here do NOT stop setup.
set "FAILED="
for %%p in (numpy opencv-python Pillow pypdf python-docx openpyxl faster-whisper sounddevice pyttsx3 mss pyautogui) do (
    echo        installing %%p ...
    pip install %%p >nul 2>&1
    if errorlevel 1 (
        echo        [!] skipped %%p - Vidit runs without it
        call set "FAILED=%%FAILED%% %%p"
    )
)

echo  [5/5] Checking for Ollama (his local brain)...
where ollama >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Ollama is not installed. Download it from https://ollama.com/download
    echo  After installing, open a terminal and run:   ollama pull qwen2.5:7b
    echo  ^(about 4.7 GB; runs fully on your RTX 4050^)
) else (
    echo  Ollama found. Pulling Qwen 2.5 7B if missing...
    ollama pull qwen2.5:7b
)

echo.
echo  Running the doctor...
python -m vidit --doctor
echo.
echo  Setup finished. Double-click  start_vidit.bat  to wake him up.
echo.
pause
