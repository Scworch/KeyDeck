@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONW=%ROOT%.venv\Scripts\pythonw.exe"

if not exist "%PYTHONW%" (
    echo Virtual environment is missing.
    echo Create it with: python -m venv .venv
    echo Then install deps: .\.venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "" "%PYTHONW%" -m keydeck
