@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [퀘스트 표시 찾기 + 비교] 퀘스트 목표 좌표를 찾고, 이어서 모방학습 봇 3분 / 규칙 봇 3분 비교.
.venv\Scripts\python marker_probe.py
.venv\Scripts\python bc_bot.py 180
.venv\Scripts\python rule_bot.py 180
echo.
if /i not "%NEXT%"=="%~nx0" pause
