#!/bin/bash

###############################################################################
# install_dependencies.sh
# ------------------------
# One-shot setup script for the Therapeutic Duplication Checker on a fresh
# Ubuntu 22.04 / 24.04 EC2 instance.
#
# What this script does:
#   1. Updates apt and installs system packages (Python 3.12, PostgreSQL)
#   2. Creates the PostgreSQL database and user (reads credentials from .env)
#   3. Creates a Python virtual environment
#   4. Installs all Python dependencies
#   5. Validates the setup by importing key modules
#
# Usage:
#   chmod +x install_dependencies.sh
#   ./install_dependencies.sh
#
# Prerequisites:
#   - .env file must exist in the same directory as this script
#   - Script must be run as a user with sudo privileges
###############################################################################

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()    { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${BOLD}══ $* ══${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${SCRIPT_DIR}/venv"
PYTHON_CMD="python3.12"
ENV_FILE="${SCRIPT_DIR}/.env"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Therapeutic Duplication Checker — EC2 Dependency Setup    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 0. check .env ─────────────────────────────────────────────────────────────
section "Step 0: Checking prerequisites"

[ -f "$ENV_FILE" ] || fail ".env not found at $ENV_FILE. Create it before running this script."
success ".env file found"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${DB_NAME:?DB_NAME must be set in .env}"
: "${DB_USER:?DB_USER must be set in .env}"
: "${DB_PASSWORD:?DB_PASSWORD must be set in .env}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
success "DB credentials loaded  (DB_NAME=$DB_NAME  DB_USER=$DB_USER  DB_HOST=$DB_HOST:$DB_PORT)"

# ── 1. system packages ────────────────────────────────────────────────────────
section "Step 1: Updating system packages"

sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    software-properties-common curl wget git unzip \
    build-essential libssl-dev libffi-dev libpq-dev \
    lsof
success "Base system packages installed"

# Python 3.12 — always add PPA and ensure ALL required packages are present,
# even if the python3.12 binary already exists (venv/dev may still be missing).
info "Adding deadsnakes PPA for Python 3.12..."
sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
sudo apt-get update -qq

info "Installing / verifying python3.12, python3.12-venv, python3.12-dev..."
sudo apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip

# Verify the venv module is actually importable before proceeding
if ! $PYTHON_CMD -c "import ensurepip" 2>/dev/null; then
    # ensurepip ships with python3.12-venv on Debian/Ubuntu — if still missing, force reinstall
    warn "ensurepip not found after install — forcing reinstall of python3.12-venv..."
    sudo apt-get install -y --reinstall python3.12-venv
fi

$PYTHON_CMD -c "import ensurepip" \
    || fail "python3.12-venv is still broken. Run: sudo apt-get install --reinstall python3.12-venv"

success "Python $($PYTHON_CMD --version) ready (venv module confirmed)"

# PostgreSQL
if ! command -v psql &>/dev/null; then
    info "Installing PostgreSQL..."
    sudo apt-get install -y postgresql postgresql-contrib
    sudo systemctl enable --now postgresql
    sleep 3
else
    info "PostgreSQL already installed: $(psql --version)"
    sudo systemctl start postgresql 2>/dev/null || true
fi
success "PostgreSQL service running"

# ── 2. configure PostgreSQL ───────────────────────────────────────────────────
section "Step 2: Configuring PostgreSQL"

PG_MAJOR=$(psql --version | grep -oP '\d+' | head -1)
info "PostgreSQL major version: $PG_MAJOR"

PG_HBA="/etc/postgresql/${PG_MAJOR}/main/pg_hba.conf"
if [ -f "$PG_HBA" ]; then
    if ! sudo grep -qP "^host\s+${DB_NAME}\s+${DB_USER}" "$PG_HBA" 2>/dev/null; then
        printf "host    %s    %s    127.0.0.1/32    md5\n" "$DB_NAME" "$DB_USER" \
            | sudo tee -a "$PG_HBA" > /dev/null
        printf "host    %s    %s    ::1/128         md5\n" "$DB_NAME" "$DB_USER" \
            | sudo tee -a "$PG_HBA" > /dev/null
        sudo systemctl reload postgresql
        info "pg_hba.conf updated"
    fi
fi

sudo -u postgres psql -v ON_ERROR_STOP=0 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE "${DB_USER}" LOGIN PASSWORD '${DB_PASSWORD}';
    RAISE NOTICE 'Created role ${DB_USER}';
  ELSE
    ALTER ROLE "${DB_USER}" LOGIN PASSWORD '${DB_PASSWORD}';
    RAISE NOTICE 'Updated password for ${DB_USER}';
  END IF;
END
\$\$;

SELECT 'CREATE DATABASE "${DB_NAME}" OWNER "${DB_USER}"'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')
\gexec

GRANT ALL PRIVILEGES ON DATABASE "${DB_NAME}" TO "${DB_USER}";
SQL

PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -c "SELECT version();" > /dev/null 2>&1 \
    && success "Database connection verified" \
    || warn "Could not verify DB connection — double-check credentials in .env"

# ── 3. Python virtual environment ─────────────────────────────────────────────
section "Step 3: Setting up Python virtual environment"

# If a venv directory exists but the python binary inside is broken/missing,
# remove it so we get a clean rebuild.
if [ -d "$VENV_PATH" ]; then
    if "${VENV_PATH}/bin/python3" -c "import sys" 2>/dev/null; then
        warn "Virtual environment already exists and is healthy — reusing it"
    else
        warn "Existing venv at $VENV_PATH appears broken — removing and rebuilding..."
        rm -rf "$VENV_PATH"
    fi
fi

if [ ! -d "$VENV_PATH" ]; then
    info "Creating virtual environment at $VENV_PATH ..."
    $PYTHON_CMD -m venv "$VENV_PATH" \
        || fail "venv creation failed. Ensure python3.12-venv is installed: sudo apt-get install python3.12-venv"
    success "Virtual environment created at $VENV_PATH"
fi

# shellcheck disable=SC1091
source "${VENV_PATH}/bin/activate"
pip install --upgrade pip setuptools wheel --quiet
success "pip upgraded inside venv"

# ── 4. Python dependencies ────────────────────────────────────────────────────
section "Step 4: Installing Python packages"

pip install \
    flask \
    psycopg2-binary \
    python-dotenv \
    requests \
    gunicorn \
    --quiet

success "Python packages installed"

# ── 5. Validate imports ───────────────────────────────────────────────────────
section "Step 5: Validating Python imports"

"${VENV_PATH}/bin/python3" - <<'PYCHECK'
import flask, psycopg2, dotenv, gunicorn
print("  flask        :", flask.__version__)
print("  psycopg2     :", psycopg2.__version__)
print("  gunicorn     : ok")
print("  python-dotenv: ok")
PYCHECK
success "All imports validated"

deactivate

# ── done ──────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  Installation Complete!                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  Project dir : $SCRIPT_DIR"
echo "  Virtual env : $VENV_PATH"
echo "  Database    : $DB_NAME @ $DB_HOST:$DB_PORT"
echo ""
echo "  Next steps:"
echo "    1. Confirm all .py source files are in  $SCRIPT_DIR"
echo "    2. Start server :  ./start_server.sh"
echo "    3. Check status :  ./status_server.sh"
echo "    4. Stop server  :  ./stop_server.sh"