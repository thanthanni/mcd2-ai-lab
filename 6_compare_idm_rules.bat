@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "DATA=%USERPROFILE%\Documents\MCD2-AI\data"
if exist E:\ set "DATA=E:\MCD2-AI\data"
if exist data_path.txt set /p DATA=<data_path.txt
echo [비교] IDM만 / 화면 규칙만 / 둘을 섞은 것 중 뭐가 나은지 내 녹화로 비교해.
.venv\Scripts\python hud_rules.py --eval "%DATA%" --idm runs\idm\best.pt
pause
