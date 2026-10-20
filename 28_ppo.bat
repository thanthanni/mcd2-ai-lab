@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [스스로 배우는 봇 v2] 규칙 없이 신경망이 점수만 보고 배워. 30분 돌아. 배운 건 ppo_policy.pt에 계속 쌓여.
.venv\Scripts\python ppo_bot.py 1800
if /i not "%NEXT%"=="%~nx0" pause
