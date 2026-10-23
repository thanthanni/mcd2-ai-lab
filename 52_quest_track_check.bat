@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [퀘스트 추적 시험] J 짧게(일지) - J 길게(추적) - Esc - 휠 클릭(안내선)
.venv\Scripts\python -X utf8 quest_track_check.py
