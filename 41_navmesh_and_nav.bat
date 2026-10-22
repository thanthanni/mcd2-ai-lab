@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [내비 메시 찾기 + 걷기 시험] 길찾기 데이터를 읽어 보고, 20분 걷기 시험.
.venv\Scripts\python navmesh_probe.py
.venv\Scripts\python nav_test.py 1200
if /i not "%NEXT%"=="%~nx0" pause
