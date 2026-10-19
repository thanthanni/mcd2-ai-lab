@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [게임 상태 탐색] 게임을 읽기만 해서 캐릭터·몹·체력 정보가 어디 있는지 훑어. 1~3분 걸려.
echo 오프라인 캐릭터로 월드에 들어가 몹 근처에 있을 때 실행해.
.venv\Scripts\python state_probe.py
echo.
echo 이 폴더에 생긴 state_probe.txt를 디스코드로 보내 줘.
if /i not "%NEXT%"=="%~nx0" pause
