#!/bin/bash

###############################################################################
# start_server.sh
# ---------------
# Start the Therapeutic Duplication Checker API server in the background.
# Adapted from the existing IBR start script with PostgreSQL-aware health check.
#
# Usage:
#   chmod +x start_server.sh
#   ./start_server.sh
###############################################################################

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()    { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── configuration ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${SCRIPT_DIR}/venv"
SERVER_FILE="${SCRIPT_DIR}/server.py"
LOG_FILE="${SCRIPT_DIR}/server.log"
PID_FILE="${SCRIPT_DIR}/server.pid"
PYTHON_CMD="${VENV_PATH}/bin/python3"
SERVER_PORT="${SERVER_PORT:-8000}"
STARTUP_WAIT=5   # seconds to wait before health check

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        Therapeutic Duplication Checker — Start Server       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

cd "$SCRIPT_DIR" || fail "Cannot cd to $SCRIPT_DIR"
info "Working directory: $SCRIPT_DIR"

# ── pre-flight checks ─────────────────────────────────────────────────────────
[ -d "$VENV_PATH" ]   || fail "Virtual environment not found at $VENV_PATH. Run ./install_dependencies.sh first."
[ -f "$SERVER_FILE" ] || fail "server.py not found at $SERVER_FILE"
[ -f "${SCRIPT_DIR}/.env" ] || fail ".env file not found. PostgreSQL credentials are required."
success "Pre-flight checks passed"

# ── check if already running ──────────────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        warn "Server already running (PID: $OLD_PID)"
        read -rp "Stop and restart? (y/n): " -n 1 REPLY
        echo
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            info "Stopping old server (PID $OLD_PID)..."
            kill -TERM "$OLD_PID" 2>/dev/null || kill -9 "$OLD_PID" 2>/dev/null || true
            sleep 2
            rm -f "$PID_FILE"
        else
            info "Exiting without restart."
            exit 0
        fi
    else
        info "Stale PID file found — removing"
        rm -f "$PID_FILE"
    fi
fi

# ── free port ─────────────────────────────────────────────────────────────────
info "Checking port $SERVER_PORT..."
PORT_PID=$(sudo lsof -ti:"$SERVER_PORT" 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    warn "Port $SERVER_PORT in use by PID $PORT_PID — killing..."
    sudo kill -9 "$PORT_PID" 2>/dev/null || true
    sleep 1
fi
success "Port $SERVER_PORT is free"

# ── start server ──────────────────────────────────────────────────────────────
info "Starting server in background..."

nohup bash -c "
    source '${VENV_PATH}/bin/activate'
    cd '${SCRIPT_DIR}'
    exec python3 server.py --host 0.0.0.0 --port ${SERVER_PORT}
" >> "$LOG_FILE" 2>&1 &

SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
info "Server process started (PID: $SERVER_PID) — waiting ${STARTUP_WAIT}s..."
sleep "$STARTUP_WAIT"

# ── verify process is still alive ────────────────────────────────────────────
if ! ps -p "$SERVER_PID" > /dev/null 2>&1; then
    echo -e "${RED}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║              Server failed to start!                        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo "Last 30 lines of $LOG_FILE :"
    tail -30 "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

# ── health check ──────────────────────────────────────────────────────────────
info "Running health check..."
for attempt in 1 2 3; do
    sleep 1
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        "http://localhost:${SERVER_PORT}/api/v1/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        break
    fi
    warn "Health check attempt $attempt failed (HTTP $HTTP_CODE)"
done

if [ "$HTTP_CODE" = "200" ]; then
    HEALTH_BODY=$(curl -s "http://localhost:${SERVER_PORT}/api/v1/health" 2>/dev/null || echo "{}")
    DB_STATUS=$(echo "$HEALTH_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('db_status','unknown'))" 2>/dev/null || echo "unknown")
    success "Health check passed  (db_status: $DB_STATUS)"
else
    warn "Health check did not return 200 — server may still be initialising"
    warn "Check logs: tail -f $LOG_FILE"
fi

# ── success banner ────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  Server Started!                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  PID      : $SERVER_PID"
echo "  Port     : $SERVER_PORT"
echo "  Log file : $LOG_FILE"
echo "  Base URL : http://localhost:${SERVER_PORT}"
echo ""
echo "  Endpoints:"
echo "    POST  /api/v1/check"
echo "    GET   /api/v1/health"
echo "    GET   /api/v1/guidelines"
echo "    GET   /api/v1/database/stats"
echo "    GET   /api/v1/database/recent"
echo ""
echo "  Commands:"
echo "    Logs  : tail -f $LOG_FILE"
echo "    Status: ./status_server.sh"
echo "    Stop  : ./stop_server.sh"
echo ""
echo "  Recent log:"
echo "──────────────────────────────────────────────────────────────"
tail -20 "$LOG_FILE"
echo "──────────────────────────────────────────────────────────────"