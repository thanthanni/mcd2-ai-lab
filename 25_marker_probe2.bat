@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python marker_probe2.py
if /i not "%NEXT%"=="%~nx0" pause
