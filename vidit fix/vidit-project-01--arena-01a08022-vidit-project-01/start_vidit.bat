@echo off
REM Wake Vidit up (GUI). Add --cli for the terminal version.
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
start "" /B pythonw -m vidit %*
