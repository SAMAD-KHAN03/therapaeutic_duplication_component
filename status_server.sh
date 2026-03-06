#!/bin/bash

###############################################################################
# status_server.sh
# ----------------
# Check the status of the Therapeutic Duplication Checker API server.
# Adapted from the IBR status script — includes PostgreSQL DB stats.
###############################################################################

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/server.pid"
LOG_FILE="${SCRIPT_DIR}/server.log"
SERVER_PORT="${SERVER_PORT:-8000}"
BASE_URL="http://localhost:${SERVER_PORT}"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║      Therapeutic Duplication Checker — Server Status        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Process status ────────────────────────────────────────────────────────────
echo -e "${BOLD}Process${NC}"
if [ -f "$PID_FILE" ]; then
    SERVER_PID=$(cat "$PID_FILE")
    echo -e "  PID file : ${GREEN}Found${NC} (PID: $SERVER_PID)"
    if ps -p "$SERVER_PID" > /dev/null 2>&1; then
        echo -e "  Process  : ${GREEN}Running${NC}"
        PS_INFO=$(ps -p "$SERVER_PID" -o %cpu,%mem,etime --no-headers 2>/dev/null || echo "n/a")
        echo -e "  CPU/MEM/uptime : $PS_INFO"
    else
        echo -e "  Process  : ${RED}Not Running${NC} (stale PID file)"
    fi
else
    echo -e "  PID file : ${RED}Not Found${NC}"
fi

# ── Port check ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Port $SERVER_PORT${NC}"
PORT_CHECK=$(sudo lsof -i:"$SERVER_PORT" 2>/dev/null || true)
if [ -n "$PORT_CHECK" ]; then
    echo -e "  Status : ${GREEN}In Use${NC}"
    echo "$PORT_CHECK" | awk 'NR<=3 {print "  " $0}'
else
    echo -e "  Status : ${RED}Free (server not listening)${NC}"
fi

# ── API Health ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}API Health${NC}"
HEALTH_RESP=$(curl -s --max-time 5 "${BASE_URL}/api/v1/health" 2>/dev/null || echo "")
if [ -n "$HEALTH_RESP" ]; then
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/api/v1/health" 2>/dev/null || echo "000")
    if [ "$HTTP_STATUS" = "200" ]; then
        echo -e "  HTTP     : ${GREEN}200 OK${NC}"
        DB_STATUS=$(echo "$HEALTH_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('db_status','unknown'))" 2>/dev/null || echo "unknown")
        if [ "$DB_STATUS" = "ok" ]; then
            echo -e "  Database : ${GREEN}ok${NC}"
        else
            echo -e "  Database : ${RED}$DB_STATUS${NC}"
        fi
    else
        echo -e "  HTTP     : ${RED}$HTTP_STATUS${NC}"
    fi
else
    echo -e "  Status   : ${RED}Unreachable${NC} (is the server running?)"
fi

# ── Database stats ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Database Stats${NC}"
DB_STATS=$(curl -s --max-time 5 "${BASE_URL}/api/v1/database/stats" 2>/dev/null || echo "")
if [ -n "$DB_STATS" ] && echo "$DB_STATS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo "$DB_STATS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  Drug profiles    : {d.get('drug_profiles', 'n/a')}\")
print(f\"  Combination rules: {d.get('combination_rules', 'n/a')}\")
print(f\"  Analysis results : {d.get('analysis_results', 'n/a')}\")
print(f\"  Last analysis at : {d.get('last_analysis_at', 'never')}\")
" 2>/dev/null || echo "  (parse error)"
else
    echo -e "  ${YELLOW}Unable to fetch database stats${NC}"
fi

# ── Recent analyses ───────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Recent Analyses (last 5)${NC}"
RECENT=$(curl -s --max-time 5 "${BASE_URL}/api/v1/database/recent?limit=5" 2>/dev/null || echo "")
if [ -n "$RECENT" ] && echo "$RECENT" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo "$RECENT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('results', [])
if not rows:
    print('  (no analyses yet)')
else:
    for r in rows:
        drugs = ', '.join(r.get('prescription', []))
        print(f\"  [{r.get('created_at','?')[:19]}] {r.get('case_name','?')} | {drugs}\")
" 2>/dev/null || echo "  (parse error)"
else
    echo -e "  ${YELLOW}Unable to fetch recent analyses${NC}"
fi

# ── Recent logs ───────────────────────────────────────────────────────────────
if [ -f "$LOG_FILE" ]; then
    echo ""
    echo -e "${BOLD}Recent Logs (last 10 lines)${NC}"
    echo "──────────────────────────────────────────────────────────────"
    tail -10 "$LOG_FILE"
    echo "──────────────────────────────────────────────────────────────"
fi

echo ""
echo -e "${BOLD}Commands${NC}"
echo "  Start  : ./start_server.sh"
echo "  Stop   : ./stop_server.sh"
echo "  Logs   : tail -f $LOG_FILE"