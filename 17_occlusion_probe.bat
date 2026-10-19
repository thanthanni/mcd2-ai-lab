@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [벽 너머 몹 구별 찾기] 벽 너머 붉은 몹과 그냥 보이는 몹이 같이 있는 곳에서 실행해. 2초 걸려. 캐릭터는 가만히.
.venv\Scripts\python occlusion_probe.py
echo.
if /i not "%NEXT%"=="%~nx0" pause
