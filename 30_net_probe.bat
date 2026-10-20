@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python net_probe.py
.venv\Scripts\python deep_probe.py PlayerService:2:200 PlayerCharacterManager:2:200
if /i not "%NEXT%"=="%~nx0" pause
