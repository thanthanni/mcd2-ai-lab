@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [메인 퀘스트 받기 시험] 웅덩이 연못으로 빠른 이동 후 퀘스트 주민에게 말 걸기
.venv\Scripts\python -X utf8 travel_nav_test.py 400 quest
