@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 travel_nav_test.py 420 goto:ForestA1-DangerZone > goto_check_log.txt 2>&1
