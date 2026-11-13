#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000
