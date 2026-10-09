@echo off
chcp 65001 >nul
setlocal
if "%SPRITE_HOME%"=="" set "SPRITE_HOME=E:\OpenLookout\sprite_home"
if "%SPRITE_SANDBOX%"=="" set "SPRITE_SANDBOX=E:\OpenLookout\sprite_sandbox\demo"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
python -c "import sys; assert sys.version_info>=(3,10)" 2>nul || (echo [错误] 需要 Python 3.10+ 且在 PATH 中 & pause & exit /b 1)
python -m sprite.procctl --journal "%SPRITE_HOME%\suspended.json" --resume-all
pause
