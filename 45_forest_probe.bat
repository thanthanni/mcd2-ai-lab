@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 forest_probe.py > forest_probe_result.txt 2>&1
