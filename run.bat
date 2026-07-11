@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=python"
if exist "%CD%\.venv\Scripts\python.exe" set "PYTHON=%CD%\.venv\Scripts\python.exe"

"%PYTHON%" "%CD%\mentat_lifecycle.py" preflight %* || exit /b 1
"%PYTHON%" "%CD%\server.py" %*
