#!/bin/bash

###############################################################################
# install_dependencies.sh
# One-shot setup for the Therapeutic Duplication Checker on Ubuntu 22.04/24.04
#
# Usage:
#   chmod +x install_dependencies.sh && ./install_dependencies.sh
#
# Prerequisites:
#   - .env file in the same directory (DB_NAME, DB_USER, DB_PASSWORD required)
#   - sudo privileges
###############################################################################

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()    { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${BOLD}=== $* ===${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${SCRIPT_DIR}/venv"
VENV_PYTHON="${VENV_PATH}/bin/python3"
VENV_PIP="${VENV_PATH}/bin/pip"
PYTHON_CMD="python3.12"
ENV_FILE="${SCRIPT_DIR}/.env"
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"

echo ""
echo "=================================================="
echo "  Therapeutic Duplication Checker - EC2 Setup"
echo "=================================================="
echo ""

# ── Step 0: Check .env ────────────────────────────────────────────────────────
section "Step 0: Checking prerequisites"

[ -f "$ENV_FILE" ] || fail ".env not found at $ENV_FILE - create it first (see .env.template)"
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
success "DB credentials loaded (DB_NAME=$DB_NAME  DB_USER=$DB_USER  DB_HOST=$DB_HOST:$DB_PORT)"

# ── Step 1: System packages ───────────────────────────────────────────────────
section "Step 1: Updating system packages"

sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    software-properties-common curl wget git \
    build-essential libssl-dev libffi-dev libpq-dev \
    lsof
success "Base packages installed"

# Always add deadsnakes PPA and install ALL python3.12 packages together.
# This ensures python3.12-venv is present even if python3.12 was pre-installed
# without it (common on Ubuntu EC2 AMIs).
info "Adding deadsnakes PPA for Python 3.12..."
sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
sudo apt-get update -qq

info "Installing python3.12 + python3.12-venv + python3.12-dev ..."
sudo apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip

# Verify ensurepip is available (ships with python3.12-venv on Debian/Ubuntu)
if ! $PYTHON_CMD -c "import ensurepip" 2>/dev/null; then
    warn "ensurepip still missing - forcing reinstall of python3.12-venv..."
    sudo apt-get install -y --reinstall python3.12-venv
fi

$PYTHON_CMD -c "import ensurepip" \
    || fail "python3.12-venv is broken. Run manually: sudo apt-get install --reinstall python3.12-venv"

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

# ── Step 2: Configure PostgreSQL ──────────────────────────────────────────────
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
    || warn "Could not verify DB connection - double-check .env credentials"

# ── Step 3: Python virtual environment ────────────────────────────────────────
section "Step 3: Setting up Python virtual environment"

# If a venv directory exists but is broken (e.g. from a previous failed run),
# remove it so we get a clean rebuild.
if [ -d "$VENV_PATH" ]; then
    if "$VENV_PYTHON" -c "import sys" 2>/dev/null; then
        warn "Existing healthy venv found at $VENV_PATH - reusing it"
    else
        warn "Existing venv at $VENV_PATH is broken - removing and rebuilding..."
        rm -rf "$VENV_PATH"
    fi
fi

if [ ! -d "$VENV_PATH" ]; then
    info "Creating virtual environment at $VENV_PATH ..."
    $PYTHON_CMD -m venv "$VENV_PATH" \
        || fail "venv creation failed. Ensure python3.12-venv is installed."
    success "Virtual environment created"
fi

# ── Step 4: Install Python packages ──────────────────────────────────────────
section "Step 4: Installing Python packages"

# Always use the VENV pip - never system pip / pip3.
# The system Python is externally managed on Ubuntu 24.04 and will refuse installs.
info "Upgrading pip inside venv..."
"$VENV_PIP" install --upgrade pip setuptools wheel --quiet

if [ -f "$REQUIREMENTS" ]; then
    info "Installing from requirements.txt..."
    "$VENV_PIP" install -r "$REQUIREMENTS" --quiet
else
    info "requirements.txt not found - installing packages individually..."
    "$VENV_PIP" install flask psycopg2-binary python-dotenv requests gunicorn --quiet
fi

success "Python packages installed"

# ── Step 5: Validate imports ──────────────────────────────────────────────────
section "Step 5: Validating Python imports"

# Use venv Python explicitly - not the system python3 or python3.12
"$VENV_PYTHON" - <<'PYCHECK'
import flask, psycopg2, dotenv, gunicorn
print("  flask        :", flask.__version__)
print("  psycopg2     :", psycopg2.__version__)
print("  gunicorn     : ok")
print("  python-dotenv: ok")
PYCHECK

success "All imports validated"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=================================================="
echo "  Installation Complete!"
echo "=================================================="
echo ""
echo "  Project dir : $SCRIPT_DIR"
echo "  Virtual env : $VENV_PATH"
echo "  Python      : $($VENV_PYTHON --version)"
echo "  Database    : $DB_NAME @ $DB_HOST:$DB_PORT"
echo ""
echo "  IMPORTANT: Never run 'python3 server.py' directly."
echo "  Always use the venv or the provided scripts:"
echo ""
echo "    Start   : ./start_server.sh"
echo "    Status  : ./status_server.sh"
echo "    Stop    : ./stop_server.sh"
echo "    Manual  : ./run_dev.sh   (foreground, for testing)"
echo ""