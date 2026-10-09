@echo off
chcp 65001 >nul
setlocal
if "%SPRITE_HOME%"=="" set "SPRITE_HOME=E:\OpenLookout\sprite_home"
if "%SPRITE_SANDBOX%"=="" set "SPRITE_SANDBOX=E:\OpenLookout\sprite_sandbox\demo"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
python -c "import sys; assert sys.version_info>=(3,10)" 2>nul || (echo [错误] 需要 Python 3.10+ 且在 PATH 中 & pause & exit /b 1)
echo 即将真实占用内存（给系统留 至少 1.5GB），窗口里有“停止并立刻释放内存”按钮，240 秒后自动释放。
where pythonw >nul 2>nul && (start "" pythonw -m sprite.demo_live.eat_memory %*) || (start "" python -m sprite.demo_live.eat_memory %*)
