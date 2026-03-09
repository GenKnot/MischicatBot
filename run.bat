@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo [run.bat] venv not found, creating "%VENV_DIR%"...
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 -m venv "%VENV_DIR%"
  ) else (
    python -m venv "%VENV_DIR%"
  )
  if errorlevel 1 (
    echo [run.bat] Failed to create venv. Please install Python 3.
    exit /b 1
  )

  "%VENV_PY%" -m pip install --upgrade pip
  if exist "requirements.txt" (
    "%VENV_PY%" -m pip install -r "requirements.txt"
  )
)

call "%VENV_DIR%\Scripts\activate.bat"
python "run.py"
exit /b %errorlevel%

