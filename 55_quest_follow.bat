@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [퀘스트 안내선 따라가기] 휠 클릭 안내선을 읽어 따라 걷기 20분
.venv\Scripts\python -X utf8 travel_nav_test.py 1200 follow
