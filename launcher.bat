@echo off
cd /d "%~dp0"
set QT_STYLE_OVERRIDE=Fusion
if not exist ".venv\Scripts\python.exe" (
	echo Creation de l'environnement virtuel...
	python -m venv .venv
	if errorlevel 1 (
		echo Impossible de creer l'environnement virtuel.
		echo Installez Python avec le composant venv, puis relancez le programme.
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