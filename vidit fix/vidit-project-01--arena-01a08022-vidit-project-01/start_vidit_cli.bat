@echo off
REM Talk to Vidit in the terminal.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python -m vidit --cli %*
pause
