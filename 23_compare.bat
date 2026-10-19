@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [비교] 모방학습 봇 3분, 규칙 봇 3분을 같은 자리에서 차례로 돌려서 성적을 비교해.
.venv\Scripts\python bc_bot.py 180
.venv\Scripts\python rule_bot.py 180
echo.
if /i not "%NEXT%"=="%~nx0" pause
