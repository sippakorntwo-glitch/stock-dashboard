@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Installation complete. Open start_local.cmd to run the app.
pause
exit /b 0
:fail
echo Installation failed. Install Python 3.12 and read the error above.
pause
exit /b 1
