@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [10분 시험] 고친 걸 짧게 확인하는 판.
.venv\Scripts\python ppo_bot.py 600
if /i not "%NEXT%"=="%~nx0" pause
