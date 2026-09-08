@echo off
REM ============================================================================
REM  GET_VIDIT_REPORT.bat - double-click me.
REM  Collects Vidit's error logs into ONE text file on your Desktop
REM  (Vidit_report.txt) and opens it. Paste its contents when asked.
REM  Nothing leaves your PC - you choose what to share.
REM ============================================================================
setlocal
set "OUT=%USERPROFILE%\Desktop\Vidit_report.txt"
if not exist "%USERPROFILE%\Desktop" set "OUT=%USERPROFILE%\Vidit_report.txt"

echo Gathering Vidit's logs...
> "%OUT%" echo =================================================================
>> "%OUT%" echo VIDIT ERROR REPORT  -  generated %DATE% %TIME%
>> "%OUT%" echo =================================================================

>> "%OUT%" echo.
>> "%OUT%" echo --- boot_state.json ---
if exist "%LOCALAPPDATA%\Vidit\boot_state.json" (
    type "%LOCALAPPDATA%\Vidit\boot_state.json"
) else (
    echo missing - the app never booted this Windows user
)

>> "%OUT%" echo.
>> "%OUT%" echo --- vidit_crash.log (FULL - this is the important one) ---
if exist "%LOCALAPPDATA%\Vidit\logs\vidit_crash.log" (
    type "%LOCALAPPDATA%\Vidit\logs\vidit_crash.log"
) else (
    echo missing - no crash was logged.
    echo If the app still crashed with no log here, antivirus is likely
    echo killing the unsigned exe: add the Vidit folder to Defender
    echo exclusions and try again.
)

>> "%OUT%" echo.
>> "%OUT%" echo --- vidit.log last 120 lines ---
if exist "%LOCALAPPDATA%\Vidit\logs\vidit.log" (
    powershell -NoProfile -Command "Get-Content \"$env:LOCALAPPDATA\Vidit\logs\vidit.log\" -Tail 120"
) else (
    echo missing
)

>> "%OUT%" echo.
>> "%OUT%" echo --- logs folder listing ---
if exist "%LOCALAPPDATA%\Vidit\logs" (
    dir /b /o-d "%LOCALAPPDATA%\Vidit\logs"
) else (
    echo missing - Vidit has never created its data folder.
)

>> "%OUT%" echo.
>> "%OUT%" echo --- end of report ---

echo.
echo Done. Your report is here:
echo   %OUT%
echo.
echo It will open in Notepad now. Copy its contents (Ctrl+A, Ctrl+C)
echo and paste it back in the chat with the agent.
start "" notepad "%OUT%"
echo.
echo Press any key to close this window...
pause >nul
endlocal
