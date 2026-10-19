@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "DATA=%USERPROFILE%\Documents\MCD2-AI\data"
if exist E:\ set "DATA=E:\MCD2-AI\data"
if exist data_path.txt set /p DATA=<data_path.txt
echo [2단계] 네 녹화로 "키 맞히는 AI(IDM)"를 학습해. 끊겨도 다시 실행하면 이어서 해.
.venv\Scripts\python train.py --mode idm --data "%DATA%" --out runs\idm --epochs 20
pause
