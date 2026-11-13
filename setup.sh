#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements.txt
echo "Setup done. Run ./start.sh"
