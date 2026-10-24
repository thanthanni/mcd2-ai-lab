@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [퀘스트 안내선 따라가기] 10분
.venv\Scripts\python -X utf8 travel_nav_test.py 600 follow > quest_follow_log.txt 2>&1
