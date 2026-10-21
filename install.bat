@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1 && (
  py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
) || (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
)
if errorlevel 1 (
  echo Python 3.11 or newer is required.
  exit /b 1
)
cd src\openlookout
where py >nul 2>&1 && (
  py -3.11 -m pip install pillow psutil jsonschema certifi -r requirements-proactive.txt
) || (
  python -m pip install pillow psutil jsonschema certifi -r requirements-proactive.txt
)
if errorlevel 1 exit /b 1
where py >nul 2>&1 && (
  py -3.11 -m pip install pystray
) || (
  python -m pip install pystray
)
if errorlevel 1 echo pystray is optional. Right-click Pause, Undo, and Quit still work.
where py >nul 2>&1 && (
  py -3.11 -m sprite.proactive.first_run
) || (
  python -m sprite.proactive.first_run
)
if errorlevel 1 exit /b 1
where py >nul 2>&1 && (
  py -3.11 -m sprite.proactive.live
) || (
  python -m sprite.proactive.live
)
