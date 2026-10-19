@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python deep_probe.py BP_QuestRunner_C QuestPlayerProgress W_QuestTracker_C
if /i not "%NEXT%"=="%~nx0" pause
