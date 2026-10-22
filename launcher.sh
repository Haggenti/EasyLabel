#!/bin/sh

cd "$(dirname "$0")" || exit 1
python3 -m pip install --break-system-packages -r requirements.txt || exit 1
exec python3 label_app.py "$@"
