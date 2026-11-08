@echo off
setlocal
cd /d "%~dp0\.."

if not exist "logs" mkdir "logs"

echo ======================================================== >> logs\pipeline.log
echo [%date% %time%] Starting SiraLens Nightly Pipeline >> logs\pipeline.log

call backend\.venv\Scripts\activate.bat
python scripts\nightly_pipeline.py >> logs\pipeline.log 2>&1

echo [%date% %time%] Pipeline Finished >> logs\pipeline.log
endlocal
