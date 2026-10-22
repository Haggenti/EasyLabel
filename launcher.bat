@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 (
	echo Impossible d'installer les dependances.
	pause
	exit /b 1
)
python label_app.py %*