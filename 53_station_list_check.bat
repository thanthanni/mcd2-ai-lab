@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [역 목록 확인] 가까운 역에서 목록을 한 칸씩 내리며 사진(이동 안 함)
.venv\Scripts\python -X utf8 travel_nav_test.py 240 list
