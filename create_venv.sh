#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${1:-venv}"

if [[ "$VENV_DIR" = /* ]]; then
	VENV_PATH="$VENV_DIR"
else
	VENV_PATH="$SCRIPT_DIR/$VENV_DIR"
fi

python3 -m venv "$VENV_PATH"
"$VENV_PATH/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo "Virtual environment created at: $VENV_PATH"
