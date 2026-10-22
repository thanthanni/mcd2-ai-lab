@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python travel_test.py 3
if /i not "%NEXT%"=="%~nx0" pause
