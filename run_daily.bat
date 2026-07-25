@echo off
REM LeadForge - one-click daily lead run. Just double-click this file.
REM Runs: scrape-all -> score -> enrich -> Excel export, then waits so you can
REM read the summary (the Excel file path is on the last line).

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Setup is not finished - no .venv folder found here.
    echo See USER_GUIDE.md, section 2 "One-time setup".
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
leadforge daily %*

echo.
echo Finished. Open the Excel file listed above ^(it is in the exports folder^).
pause
