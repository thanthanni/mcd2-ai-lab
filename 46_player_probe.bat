@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 player_probe.py > player_probe_result.txt 2>&1
