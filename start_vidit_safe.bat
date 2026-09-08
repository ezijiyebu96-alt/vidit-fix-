@echo off
REM ============================================================
REM  Vidit - SAFE mode: starts WITHOUT hearing (no faster-whisper).
REM
REM  Use this if Vidit crashes on your PC (e.g. a Windows
REM  "access violation" while loading the speech model).
REM  He will still chat, remember, speak, etc. — only the
REM  microphone / wake word is disabled.
REM
REM  Normal mode = start_vidit.bat
REM ============================================================
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
set VIDIT_NO_EARS=1
start "" /B pythonw -m vidit %*
