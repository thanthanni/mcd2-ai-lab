@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [걷기 시험] 마을 역과 북쪽 필드를 20분 동안 오가며 도착률을 재.
.venv\Scripts\python nav_test.py 1200
if /i not "%NEXT%"=="%~nx0" pause
