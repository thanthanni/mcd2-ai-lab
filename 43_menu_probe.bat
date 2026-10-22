@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 menu_probe.py > menu_probe_result.txt 2>&1
