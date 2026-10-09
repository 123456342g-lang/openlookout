@echo off
chcp 65001 >nul
setlocal
if "%SPRITE_HOME%"=="" set "SPRITE_HOME=E:\OpenLookout\sprite_home"
if "%SPRITE_SANDBOX%"=="" set "SPRITE_SANDBOX=E:\OpenLookout\sprite_sandbox\demo"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
python -c "import sys; assert sys.version_info>=(3,10)" 2>nul || (echo [错误] 需要 Python 3.10+ 且在 PATH 中 & pause & exit /b 1)
echo. > "%SPRITE_HOME%\STOP_DEMO"
echo 正在停止正在运行的演示（会先恢复被挂起的进程）……
timeout /t 6 /nobreak >nul
python -m sprite.demo_live.stage_demo --reset
echo 已重置。再运行 run_demo.bat 或 run_demo_live.bat。
pause
