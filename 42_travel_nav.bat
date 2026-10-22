@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [빠른 이동 + 걷기] 마을 역과 숲 전초기지를 걸어가서 빠른 이동으로 오가며 20분.
.venv\Scripts\python travel_nav_test.py 1200
if /i not "%NEXT%"=="%~nx0" pause
