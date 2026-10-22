@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python class_probe.py BP_MinecartStation_C NameOnMap,bUnlocked,bStartAsUnlocked BP_SpicewoodTeleportDoor_C Tags
if /i not "%NEXT%"=="%~nx0" pause
