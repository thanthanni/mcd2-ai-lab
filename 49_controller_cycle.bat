@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 controller_cycle_check.py > controller_cycle_result.txt 2>&1
