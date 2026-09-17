@echo off
REM Active la collecte automatique quotidienne (heure modifiable ci-dessous)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\planifier_tache.ps1" -Action installer -Heure 10:00
pause
