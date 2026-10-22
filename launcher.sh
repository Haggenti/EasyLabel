#!/bin/sh

cd "$(dirname "$0")" || exit 1

# Use the distribution PySide6 when available so Qt can use the desktop theme.
if python3 -c "import PySide6" >/dev/null 2>&1; then
	exec python3 label_app.py "$@"
fi

if [ ! -x .venv/bin/python ]; then
	echo "Creation de l'environnement virtuel..."
	if ! python3 -m venv .venv; then
		echo "Impossible de creer l'environnement virtuel."
		echo "Sous Debian/Ubuntu, installez : sudo apt install python3-venv"
		exit 1
	fi
fi

if ! .venv/bin/python -m pip install -r requirements.txt; then
	echo "Impossible d'installer les dependances de requirements.txt."
	exit 1
fi

exec .venv/bin/python label_app.py "$@"
