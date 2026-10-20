@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MCD2 AI 자동 실행기
echo [자동 실행기] 켜 두면 헤르타가 올린 작업을 알아서 받아서 실행하고 결과를 보내.
echo 안티치트 게임(롤·발로란트 등)을 켜면 알아서 쉬고, 끄면 다시 파일을 확인해. 끄려면 이 창을 닫아.
if not exist loop_step.py powershell -NoProfile -Command "Invoke-WebRequest 'https://raw.githubusercontent.com/thanthanni/mcd2-ai-lab/main/loop_step.py' -OutFile loop_step.py"
:loop
.venv\Scripts\python loop_step.py
timeout /t 60 /nobreak >nul
goto loop
