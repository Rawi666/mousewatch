#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${1:-venv}"

if [[ "$VENV_DIR" = /* ]]; then
  VENV_PATH="$VENV_DIR"
else
  VENV_PATH="$SCRIPT_DIR/$VENV_DIR"
fi

echo "=== MouseWatch Build ==="
echo

echo "Creating/updating virtual environment..."
"$SCRIPT_DIR/create_venv.sh" "$VENV_PATH"

VENV_PY="$VENV_PATH/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "ERROR: Python executable not found in virtual environment: $VENV_PY"
  exit 1
fi

echo "Installing development/build dependencies from requirements-dev.txt..."
"$VENV_PY" -m pip install -r "$SCRIPT_DIR/requirements-dev.txt"

echo

echo "Running test suite..."
"$VENV_PY" -m pytest -q

echo

echo "Building MouseWatch binary..."
"$VENV_PY" -m PyInstaller --onefile --name MouseWatch src/mousewatch/mousewatch.py

echo

echo "Build complete: dist/MouseWatch"
