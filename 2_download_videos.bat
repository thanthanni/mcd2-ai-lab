@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VID=videos"
if exist E:\ set "VID=E:\MCD2-AI\videos"
set "VLAB=data_video"
if exist E:\ set "VLAB=E:\MCD2-AI\data_video"
echo [3단계-1] videos.txt에 적은 유튜브 주소를 360p로 받아 E:\MCD2-AI\videos에 넣어(E 드라이브가 없으면 이 폴더의 videos).
if not exist "%VID%" mkdir "%VID%"
.venv\Scripts\python -m yt_dlp -a videos.txt -f "bv*[height<=360][ext=mp4]/bv*[height<=360]/b[height<=360]" -o "%VID%\%%(id)s.%%(ext)s" --no-playlist
if /i not "%NEXT%"=="%~nx0" pause
