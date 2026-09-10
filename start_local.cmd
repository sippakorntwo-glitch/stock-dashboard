@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo Run install_local.cmd first.
 pause
 exit /b 1
)
.venv\Scripts\python -m streamlit run app.py
pause
