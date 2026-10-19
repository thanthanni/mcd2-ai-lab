@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [규칙 봇 v1] 진짜 패드는 빼고, 오프라인 사본 캐릭터로 몹 근처 넓은 곳에서 실행해.
echo 2분 동안 봇이 싸워. 멈추려면 이 창을 클릭하고 Ctrl+C.
.venv\Scripts\python rule_bot.py 120
echo.
if /i not "%NEXT%"=="%~nx0" pause
