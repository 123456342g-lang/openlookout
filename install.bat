@echo off
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" && set "PY=py -3"
if not defined PY (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" && set "PY=python"
)
if not defined PY (
  echo Python 3.11 or newer is required.
  exit /b 1
)
cd src\openlookout
%PY% -m pip install pillow psutil jsonschema certifi -r requirements-proactive.txt
if errorlevel 1 exit /b 1
%PY% -m pip install pystray
if errorlevel 1 echo pystray is optional. Right-click Pause, Undo, and Quit still work.
%PY% -m sprite.proactive.first_run
if errorlevel 1 exit /b 1
%PY% -m sprite.proactive.live
