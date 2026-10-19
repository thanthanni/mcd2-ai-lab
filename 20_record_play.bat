@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [플레이 기록] 모방학습용. 오프라인 사본 캐릭터로 평소처럼 플레이해. 게임을 끄면 자동으로 끝나고 결과를 보내.
echo 봇은 안 돌아가. 진짜 패드 그대로 써도 돼.
.venv\Scripts\python play_recorder.py
echo.
if /i not "%NEXT%"=="%~nx0" pause
