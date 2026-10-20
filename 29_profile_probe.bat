@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python deep_probe.py PlayerServiceSubsystem:2:150 PlayerServiceImpl:2:80 OfflinePlayerServiceImpl:2:80 OnlinePlayerServiceImpl:2:80 AnonymousGuestPlayerServiceImpl:2:60 PlayerCharacterManagerSubsystem:2:150 LocalPlayerSaveGame:2:80
if /i not "%NEXT%"=="%~nx0" pause
