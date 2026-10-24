@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 gimmick_probe.py OutpostGate > gimmick_probe_log.txt 2>&1
