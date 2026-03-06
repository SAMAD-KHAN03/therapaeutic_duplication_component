#!/bin/bash

###############################################################################
# run_dev.sh
# ----------
# Run server.py in the FOREGROUND using the venv Python.
# Use this for local testing / debugging instead of calling python3 directly.
#
# Usage:
#   chmod +x run_dev.sh
#   ./run_dev.sh
#
# Why this exists:
#   Running `python3 server.py` or `python3.12 server.py` directly uses the
#   system Python, which does NOT have flask/psycopg2 installed (Ubuntu 24.04
#   uses an "externally managed" Python that blocks pip installs).
#   This script always uses ./venv/bin/python3 where packages are installed.
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/venv/bin/python3"
SERVER_FILE="${SCRIPT_DIR}/server.py"
ENV_FILE="${SCRIPT_DIR}/.env"
SERVER_PORT="${SERVER_PORT:-8000}"

# ── Guards ────────────────────────────────────────────────────────────────────
if [ ! -f "$VENV_PYTHON" ]; then
    echo "[ERROR] Venv Python not found at $VENV_PYTHON"
    echo "        Run ./install_dependencies.sh first."
    exit 1
fi

if [ ! -f "$SERVER_FILE" ]; then
    echo "[ERROR] server.py not found at $SERVER_FILE"
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "[ERROR] .env not found. Copy .env.template to .env and fill in DB credentials."
    exit 1
fi

# ── Quick sanity check ────────────────────────────────────────────────────────
echo "[INFO] Checking dependencies..."
"$VENV_PYTHON" -c "import flask, psycopg2, dotenv" 2>/dev/null || {
    echo "[ERROR] Required packages missing from venv."
    echo "        Run ./install_dependencies.sh to reinstall."
    exit 1
}
echo "[OK]   flask + psycopg2 + dotenv found in venv"

# ── Run ───────────────────────────────────────────────────────────────────────
echo ""
echo "[INFO] Starting server (foreground) on port $SERVER_PORT"
echo "[INFO] Python: $("$VENV_PYTHON" --version)"
echo "[INFO] Press Ctrl+C to stop"
echo ""

cd "$SCRIPT_DIR"
exec "$VENV_PYTHON" server.py --host 0.0.0.0 --port "$SERVER_PORT"
