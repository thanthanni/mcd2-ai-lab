@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python dest_probe.py CA05
if /i not "%NEXT%"=="%~nx0" pause
