#!/usr/bin/env bash
# One-time setup: backend virtualenv + Python deps, frontend node_modules.
# Safe to re-run. Installs nothing globally and needs no sudo.
set -euo pipefail
cd "$(dirname "$0")"

die() { echo "setup: $*" >&2; exit 1; }

# --- Python 3.11+ -----------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  die "python3 not found. Install Python 3.11 or newer (https://www.python.org/downloads/ or 'brew install python')."
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  die "python3 is $(python3 -c 'import platform; print(platform.python_version())'); Python 3.11 or newer is required."
fi

# --- Node 18+ and npm -------------------------------------------------------
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  die "node/npm not found. Install Node.js 18 or newer (https://nodejs.org or 'brew install node')."
fi
if ! node -e 'process.exit(parseInt(process.versions.node, 10) >= 18 ? 0 : 1)'; then
  die "node is $(node -v); Node 18 or newer is required."
fi

# --- Backend: .venv + Python deps ---------------------------------------------
if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv ..."
  python3 -m venv .venv || die "could not create .venv (is the python3 'venv' module installed?)"
fi
echo "Installing backend dependencies ..."
.venv/bin/python -m pip install -q -r backend/requirements.txt || die "pip install failed (see messages above)"

# --- Frontend: node_modules ---------------------------------------------------
echo "Installing frontend dependencies ..."
cd frontend
if [ -f package-lock.json ]; then
  npm ci --no-audit --no-fund || die "npm ci failed (see messages above)"
else
  npm install --no-audit --no-fund || die "npm install failed (see messages above)"
fi
cd ..

echo ""
echo "Setup done. Next, run:  ./start.sh"
echo "Then open http://localhost:5173"
