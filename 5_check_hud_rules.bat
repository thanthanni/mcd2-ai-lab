@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "DATA=%USERPROFILE%\Documents\MCD2-AI\data"
if exist E:\ set "DATA=E:\MCD2-AI\data"
if exist data_path.txt set /p DATA=<data_path.txt
echo [화면 규칙 채점] 내 녹화로 "칸이 회색이 되면 누른 것", "배경이 흐르는 반대 방향이 이동" 규칙이 얼마나 맞는지 봐.
.venv\Scripts\python hud_rules.py --eval "%DATA%"
if /i not "%NEXT%"=="%~nx0" pause
