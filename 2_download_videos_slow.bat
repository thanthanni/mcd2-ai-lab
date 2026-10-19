@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VID=videos"
if exist E:\ set "VID=E:\MCD2-AI\videos"
set "VLAB=data_video"
if exist E:\ set "VLAB=E:\MCD2-AI\data_video"
echo [3단계-1] 느리게 받기: 게임하는 동안 인터넷을 덜 쓰게 초당 1MB로만 받아(10GB면 3시간쯤).
if not exist "%VID%" mkdir "%VID%"
.venv\Scripts\python -m yt_dlp -a videos.txt -f "bv*[height<=360][ext=mp4]/bv*[height<=360]/b[height<=360]" -o "%VID%\%%(id)s.%%(ext)s" --no-playlist --limit-rate 1M
pause
