@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [모방학습 봇] 네 플레이를 보고 배운 봇이야. 진짜 패드는 빼고, 몹 있는 필드에서 실행해. 5분 동안 돌아.
.venv\Scripts\python bc_bot.py 300
echo.
if /i not "%NEXT%"=="%~nx0" pause
