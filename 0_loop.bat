@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MCD2 AI 자동 실행기
echo [자동 실행기] 켜 두면 헤르타가 올린 작업을 알아서 받아서 실행하고 결과를 보내.
echo 게임은 오프라인 사본 캐릭터로 켜 두고, 진짜 패드는 빼 둬. 실행 중에는 마우스를 쓰지 마. 끄려면 이 창을 닫아.
:loop
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest 'https://codeload.github.com/thanthanni/mcd2-ai-lab/zip/refs/heads/main' -OutFile $env:TEMP\mcd2lab.zip; Remove-Item $env:TEMP\mcd2lab -Recurse -Force -EA 0; Expand-Archive $env:TEMP\mcd2lab.zip $env:TEMP\mcd2lab -Force" >nul 2>nul
if not errorlevel 1 robocopy "%TEMP%\mcd2lab\mcd2-ai-lab-main" "%~dp0." /E /XF 0_auto.bat 0_loop.bat last_job.txt sent.txt /NFL /NDL /NJH /NJS /NP >nul
.venv\Scripts\python runner.py
timeout /t 60 /nobreak >nul
goto loop
