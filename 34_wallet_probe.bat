@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python wallet_probe.py
if /i not "%NEXT%"=="%~nx0" pause
