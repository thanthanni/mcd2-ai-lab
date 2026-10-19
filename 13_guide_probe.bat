@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [길 안내선 찾기] 게임에서 왼쪽 스틱을 눌러 길 안내선을 켠 다음 실행해.
.venv\Scripts\python guide_probe.py
echo.
pause
