@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
echo [가상 패드 시험] 처음 한 번은 설치부터 해.
uv pip install --python .venv vgamepad
.venv\Scripts\python -c "import vgamepad;vgamepad.VX360Gamepad()" 2>nul && goto run
echo 패드 드라이버(ViGEmBus)를 받아서 설치 창을 열게. 동의하고 설치한 다음 이 창으로 돌아와.
powershell -NoProfile -Command "Invoke-WebRequest https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe -OutFile $env:TEMP\ViGEmBus.exe"
start /wait "" "%TEMP%\ViGEmBus.exe"
:run
.venv\Scripts\python pad_test.py
echo.
if /i not "%NEXT%"=="%~nx0" pause
