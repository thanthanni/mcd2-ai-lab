@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [상호작용 대상 찾기] 퀘스트 상호작용 구간(안내선이 안 켜지는 곳)에서 실행해. 몇 초 걸려.
.venv\Scripts\python interact_probe.py
echo.
if /i not "%NEXT%"=="%~nx0" pause
