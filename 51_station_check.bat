@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [역 상호작용 시험] 역까지 걸어가서 A·우클릭·좌클릭 중 무엇이 메뉴를 여는지 확인.
.venv\Scripts\python -X utf8 travel_nav_test.py 180 probe
