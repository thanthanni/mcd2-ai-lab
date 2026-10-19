@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [주변 액터 찾기] 상호작용 대상(마름모 표시) 바로 옆에 서서 실행해. 몇 초 걸려.
.venv\Scripts\python nearby_probe.py
echo.
if /i not "%NEXT%"=="%~nx0" pause
