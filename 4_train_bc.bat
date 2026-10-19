@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "DATA=%USERPROFILE%\Documents\MCD2-AI\data"
if exist E:\ set "DATA=E:\MCD2-AI\data"
if exist data_path.txt set /p DATA=<data_path.txt
set "VLAB=data_video"
if exist E:\ set "VLAB=E:\MCD2-AI\data_video"
echo [4단계] 네 녹화 + 영상 라벨을 합쳐서 모방학습을 해. 끊겨도 다시 실행하면 이어서 해.
.venv\Scripts\python train.py --mode bc --data "%DATA%" --data "%VLAB%" --out runs\bc --epochs 20
pause
