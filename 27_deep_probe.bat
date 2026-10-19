@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python deep_probe.py LiveQuest:44:60
if /i not "%NEXT%"=="%~nx0" pause
