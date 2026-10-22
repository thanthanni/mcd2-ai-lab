@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 movement_check.py > movement_check_result.txt 2>&1
