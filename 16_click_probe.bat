@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [마우스 클릭 이동 시험] 넓은 곳에서 실행해. 마우스가 4번 저절로 클릭해. 그동안 마우스는 만지지 마.
.venv\Scripts\python click_probe.py
echo.
if /i not "%NEXT%"=="%~nx0" pause
