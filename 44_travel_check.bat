@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [3분 점검] 지도 탭을 확인한 경우에만 빠른 이동. 탭 확인 실패 시 중단.
.venv\Scripts\python -X utf8 travel_nav_test.py 180
