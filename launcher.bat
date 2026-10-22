@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
	python -m venv .venv
	if errorlevel 1 (
		echo Impossible de creer l'environnement Python.
		pause
		exit /b 1
	)
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
	echo Impossible d'installer les dependances.
	pause
	exit /b 1
)
.venv\Scripts\python.exe label_app.py %*