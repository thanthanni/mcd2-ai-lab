@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [길 안내선 2차] 진짜 패드는 빼고, 필드에서 실행해. 봇이 왼쪽 스틱을 눌러 안내선을 켜고 5초 동안 기록해.
.venv\Scripts\python guide_probe2.py
echo.
pause
