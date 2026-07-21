#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${1:-venv}"

if [[ "$VENV_DIR" = /* ]]; then
  VENV_PATH="$VENV_DIR"
else
  VENV_PATH="$SCRIPT_DIR/$VENV_DIR"
fi

if [[ ! -x "$VENV_PATH/bin/python" ]]; then
  echo "Creating virtual environment at: $VENV_PATH"
  "$SCRIPT_DIR/create_venv.sh" "$VENV_PATH"
fi

exec "$VENV_PATH/bin/python" "$SCRIPT_DIR/mousewatch.py"
