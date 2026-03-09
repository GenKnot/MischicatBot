#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

VENV_DIR=${VENV_DIR:-venv}

if [ ! -x "$VENV_DIR/bin/python" ] && [ ! -x "$VENV_DIR/Scripts/python.exe" ]; then
  echo "[run.sh] venv not found, creating '$VENV_DIR'..."
  if command -v python3 >/dev/null 2>&1; then
    PY=python3
  elif command -v python >/dev/null 2>&1; then
    PY=python
  else
    echo "[run.sh] Python not found. Please install Python 3." >&2
    exit 1
  fi

  "$PY" -m venv "$VENV_DIR"

  if [ -x "$VENV_DIR/bin/python" ]; then
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    [ -f requirements.txt ] && "$VENV_DIR/bin/python" -m pip install -r requirements.txt
  elif [ -x "$VENV_DIR/Scripts/python.exe" ]; then
    "$VENV_DIR/Scripts/python.exe" -m pip install --upgrade pip
    [ -f requirements.txt ] && "$VENV_DIR/Scripts/python.exe" -m pip install -r requirements.txt
  fi
fi

if [ -f "$VENV_DIR/bin/activate" ]; then
  . "$VENV_DIR/bin/activate"
elif [ -f "$VENV_DIR/Scripts/activate" ]; then
  . "$VENV_DIR/Scripts/activate"
else
  echo "[run.sh] Unable to find activate script under '$VENV_DIR'." >&2
  exit 1
fi

python run.py

