@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [스스로 배우는 봇] 몹 많은 필드에서 실행해. 10분 동안 2분짜리 판 5번을 하면서 배워.
echo 배운 건 q_table.json에 남아서, 다음에 또 돌리면 이어서 배워. 멈추려면 Ctrl+C.
.venv\Scripts\python learn_bot.py 600
echo.
if /i not "%NEXT%"=="%~nx0" pause
