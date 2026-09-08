@echo off
REM ============================================================
REM  Vidit - one-time setup for Windows 11 (Lenovo LOQ, RTX 4050)
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo  [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  Python not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo  IMPORTANT: tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

echo  [2/5] Creating virtual environment...
if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo  [3/5] Installing Vidit's core (body + brain link)...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

echo  [4/5] Installing senses (voice, ears, files). Optional - press Ctrl+C to skip.
pip install -r requirements-senses.txt

echo  [5/5] Checking for Ollama (his local brain)...
where ollama >nul 2>&1
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
pause
