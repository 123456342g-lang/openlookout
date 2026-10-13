@echo off
chcp 65001 >nul
rem 双击启动小精灵。需要 Python 3.11+（py 或 python 在 PATH 中）。
cd /d "%~dp0.."
where pythonw >nul 2>nul && (start "" pythonw -m sprite) || (python -m sprite)
