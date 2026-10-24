@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python -X utf8 quest_step_probe.py CA05 > quest_step_probe_log.txt 2>&1
