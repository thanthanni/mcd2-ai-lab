@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [마던2 AI 실험실] 처음 한 번만 실행해. 파이썬과 학습 도구(약 3GB)를 이 폴더 안에 받아.
where uv >nul 2>nul || powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
uv venv --python 3.12 .venv || goto fail
uv pip install --python .venv torch --index-url https://download.pytorch.org/whl/cu128 || goto fail
uv pip install --python .venv numpy imageio-ffmpeg yt-dlp || goto fail
.venv\Scripts\python -c "import torch;print('그래픽카드:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '못 찾음(CPU로 돌아감)')"
echo 준비 끝.
pause
exit /b 0
:fail
echo 설치 중에 실패했어. 이 창을 캡처해서 보내 줘.
pause
exit /b 1
