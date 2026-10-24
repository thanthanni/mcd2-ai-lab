@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 area_probe.py 8000 > area_probe_log.txt 2>&1
