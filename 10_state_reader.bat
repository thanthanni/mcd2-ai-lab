@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [실시간 상태 읽기] 오프라인 사본 캐릭터로 몹 근처에 있을 때 실행해.
echo 30초 동안 기록하니까 그동안 몹이랑 싸우고 물약 한 번, 유물 한 번 써 줘.
.venv\Scripts\python state_reader.py 30
echo.
pause
