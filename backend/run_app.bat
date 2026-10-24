@echo off
REM ===========================================================================
REM VoltSpace - one-click launcher (Windows)
REM
REM Double-click this file. It finds a Python on THIS machine, starts the
REM backend (which also serves the web UI) and opens your browser at the app.
REM
REM No path in this file is specific to any computer, so a downloaded copy
REM works as-is as long as Python 3.10+ is installed.
REM
REM Options are passed through to start.py:
REM     run_app.bat --setup         create .venv and install requirements, then exit
REM     run_app.bat --port 8080
REM     run_app.bat --flet          also try the Flet desktop UI
REM     run_app.bat --check         verify the environment only
REM ===========================================================================
setlocal EnableDelayedExpansion

set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "PYTHONIOENCODING=utf-8"
cd /d "%HERE%"

REM --- 1. a virtualenv inside this project, if one exists ---------------------
set "PY="
if exist "%HERE%\.venv\Scripts\python.exe"    set "PY=%HERE%\.venv\Scripts\python.exe"
if not defined PY if exist "%HERE%\.venv314\Scripts\python.exe" set "PY=%HERE%\.venv314\Scripts\python.exe"
if not defined PY if exist "%HERE%\venv\Scripts\python.exe"     set "PY=%HERE%\venv\Scripts\python.exe"

REM --- 2. the Windows `py` launcher ------------------------------------------
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 (
    for /f "delims=" %%P in ('py -c "import sys;print(sys.executable)" 2^>nul') do if not defined PY set "PY=%%P"
  )
)

REM --- 3. `python` then `python3` on PATH ------------------------------------
if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
)
if not defined PY (
  for /f "delims=" %%P in ('where python3 2^>nul') do if not defined PY set "PY=%%P"
)

REM --- 4. common install locations -------------------------------------------
if not defined PY (
  for %%V in (314 313 312 311 310) do (
    if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    if not defined PY if exist "C:\Python%%V\python.exe" set "PY=C:\Python%%V\python.exe"
  )
)

if not defined PY (
  echo.
  echo [X] Python 3.10 or newer was not found on this computer.
  echo.
  echo     1. Install Python from https://www.python.org/downloads/
  echo        ^(on the first installer screen, tick "Add python.exe to PATH"^)
  echo     2. Then double-click this file again.
  echo.
  echo     If Python is installed but still not found, open a terminal here and run:
  echo         py start.py --setup
  echo.
  pause
  exit /b 1
)

echo Using Python: %PY%
echo.

"%PY%" "%HERE%\start.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [X] The app exited with code %RC%.
  echo.
  echo     If packages are missing, install them once:
  echo         "%PY%" start.py --setup
  echo     Then check the setup:
  echo         "%PY%" start.py --check
  echo.
  pause
)
endlocal & exit /b %RC%
