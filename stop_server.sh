#!/bin/bash

###############################################################################
# stop_server.sh
# --------------
# Safely stop the Therapeutic Duplication Checker background server process.
# Adapted from the IBR stop script.
###############################################################################

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/server.pid"
SERVER_PORT="${SERVER_PORT:-8000}"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        Therapeutic Duplication Checker — Stop Server        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

cd "$SCRIPT_DIR" || exit 1

# ── no PID file ───────────────────────────────────────────────────────────────
if [ ! -f "$PID_FILE" ]; then
    echo -e "${YELLOW}⚠  PID file not found${NC}"
    echo "   Server may not be running or was started manually."

    PORT_PID=$(sudo lsof -ti:"$SERVER_PORT" 2>/dev/null || true)
    if [ -n "$PORT_PID" ]; then
        echo -e "${YELLOW}   Found process on port $SERVER_PORT (PID: $PORT_PID)${NC}"
        read -rp "   Kill this process? (y/n): " -n 1 REPLY
        echo
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            sudo kill -9 "$PORT_PID" 2>/dev/null || true
            echo -e "${GREEN}✓  Process killed${NC}"
        fi
    else
        echo "   No process found on port $SERVER_PORT"
    fi
    exit 0
fi

# ── graceful shutdown ─────────────────────────────────────────────────────────
SERVER_PID=$(cat "$PID_FILE")
echo "  Server PID : $SERVER_PID"

if ! ps -p "$SERVER_PID" > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠  Process $SERVER_PID not running (stale PID file)${NC}"
    rm -f "$PID_FILE"
    exit 0
fi

echo "  Attempting graceful shutdown (SIGTERM)..."
kill -TERM "$SERVER_PID" 2>/dev/null || true

for i in $(seq 1 10); do
    if ! ps -p "$SERVER_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✓  Server stopped gracefully (after ${i}s)${NC}"
        rm -f "$PID_FILE"
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo ""
echo -e "${YELLOW}⚠  Graceful shutdown timed out — forcing SIGKILL...${NC}"
kill -9 "$SERVER_PID" 2>/dev/null || true
sleep 1

if ps -p "$SERVER_PID" > /dev/null 2>&1; then
    echo -e "${RED}✗  Failed to stop server (PID $SERVER_PID still alive)${NC}"
    exit 1
fi

echo -e "${GREEN}✓  Server killed (SIGKILL)${NC}"
rm -f "$PID_FILE"

# Clean up anything still on the port
PORT_PID=$(sudo lsof -ti:"$SERVER_PORT" 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    sudo kill -9 "$PORT_PID" 2>/dev/null || true
fi

echo -e "${GREEN}✓  Port $SERVER_PORT freed${NC}"