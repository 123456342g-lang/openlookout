@echo off
chcp 65001 >nul
setlocal
if "%SPRITE_HOME%"=="" set "SPRITE_HOME=E:\OpenLookout\sprite_home"
if "%SPRITE_SANDBOX%"=="" set "SPRITE_SANDBOX=E:\OpenLookout\sprite_sandbox\demo"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
python -c "import sys; assert sys.version_info>=(3,10)" 2>nul || (echo [错误] 需要 Python 3.10+ 且在 PATH 中 & pause & exit /b 1)
python -c "import psutil" 2>nul || echo [提示] 没装 psutil：先运行  python -m pip install psutil  （没有它读不到进程命令行，精灵就不会挂起任何进程）
python -m sprite.demo_live.dry_run_processes --seconds 75
pause
