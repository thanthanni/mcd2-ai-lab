@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [기록 보내기] 아직 안 보낸 플레이 기록을 보내.
.venv\Scripts\python uploader.py play_*.jsonl
echo.
if /i not "%NEXT%"=="%~nx0" pause
