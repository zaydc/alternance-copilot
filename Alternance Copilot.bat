@echo off
REM Lance l'interface web d'Alternance Copilot (ferme cette fenetre pour arreter)
cd /d "%~dp0"
".venv\Scripts\streamlit.exe" run app.py
pause
