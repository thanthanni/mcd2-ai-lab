@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VID=videos"
if exist E:\ set "VID=E:\MCD2-AI\videos"
set "VLAB=data_video"
if exist E:\ set "VLAB=E:\MCD2-AI\data_video"
echo [3단계-2] 받은 영상에 IDM으로 키 입력을 채워 넣어. 결과는 E:\MCD2-AI\data_video(E 드라이브가 없으면 이 폴더의 data_video).
setlocal enabledelayedexpansion
set "LIST="
for %%f in ("%VID%\*.mp4" "%VID%\*.webm") do set LIST=!LIST! "%%~f"
.venv\Scripts\python label_videos.py --idm runs\idm\best.pt --out "%VLAB%" !LIST!
if /i not "%NEXT%"=="%~nx0" pause
