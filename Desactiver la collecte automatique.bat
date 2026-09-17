@echo off
REM Désactive la collecte automatique
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\planifier_tache.ps1" -Action retirer
pause
