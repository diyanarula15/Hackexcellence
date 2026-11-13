#!/usr/bin/env bash
# Starts the backend (FastAPI/uvicorn) and the frontend dev server (Vite) together.
# Ctrl+C stops both. Env overrides: BACKEND_PORT (default 8000), FRONTEND_PORT (default 5173).
set -euo pipefail
cd "$(dirname "$0")"

export BACKEND_PORT="${BACKEND_PORT:-8000}"
export FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_HOST=127.0.0.1

die() { echo "start: $*" >&2; exit 1; }

# --- Setup must have run -------------------------------------------------------
if [ ! -x .venv/bin/uvicorn ]; then
  die "backend is not set up (no .venv). Run ./setup.sh first."
fi
if [ ! -f frontend/node_modules/vite/bin/vite.js ]; then
  die "frontend is not set up (no frontend/node_modules). Run ./setup.sh first."
fi
command -v curl >/dev/null 2>&1 || die "curl is needed to check the backend health. Install curl and retry."

# --- Ports must be free ----------------------------------------------------------
# Binds a probe socket on 127.0.0.1; fails (exit 1) if something is already listening there.
port_free() {
  .venv/bin/python - "$1" <<'PY'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}
if ! port_free "$BACKEND_PORT"; then
  die "port $BACKEND_PORT (backend) is already in use. Stop that process or run with BACKEND_PORT=<free port>."
fi
if ! port_free "$FRONTEND_PORT"; then
  die "port $FRONTEND_PORT (frontend) is already in use. Stop that process or run with FRONTEND_PORT=<free port>."
fi

# --- Start both, each in its own process group so Ctrl+C can stop everything ----
BE_PID=""
FE_PID=""
set -m
cleanup() {
  trap - EXIT INT TERM HUP
  echo ""
  echo "Stopping backend and frontend ..."
  [ -n "$FE_PID" ] && kill -TERM -- "-$FE_PID" 2>/dev/null || true
  [ -n "$BE_PID" ] && kill -TERM -- "-$BE_PID" 2>/dev/null || true
  [ -n "$FE_PID" ] && kill -TERM "$FE_PID" 2>/dev/null || true
  [ -n "$BE_PID" ] && kill -TERM "$BE_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "Stopped."
}
trap 'cleanup; exit 0' INT TERM HUP
trap 'cleanup' EXIT

echo "Starting backend on 127.0.0.1:$BACKEND_PORT ..."
.venv/bin/uvicorn app.main:app --app-dir backend --port "$BACKEND_PORT" &
BE_PID=$!

# Wait for the backend to answer its health check before starting the frontend.
i=0
until curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; do
  if ! kill -0 "$BE_PID" 2>/dev/null; then
    die "backend exited during startup (see messages above)."
  fi
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    die "backend did not answer http://127.0.0.1:$BACKEND_PORT/api/health within 60s."
  fi
  sleep 1
done
echo "Backend is up."

echo "Starting frontend on $FRONTEND_HOST:$FRONTEND_PORT ..."
node frontend/node_modules/vite/bin/vite.js --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort frontend &
FE_PID=$!

i=0
until curl -fsS "http://$FRONTEND_HOST:$FRONTEND_PORT/" >/dev/null 2>&1; do
  if ! kill -0 "$FE_PID" 2>/dev/null; then
    die "frontend exited during startup (see messages above)."
  fi
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    die "frontend did not answer on port $FRONTEND_PORT within 60s."
  fi
  sleep 1
done

echo ""
echo "Backend:   http://127.0.0.1:$BACKEND_PORT   (API docs: http://127.0.0.1:$BACKEND_PORT/docs)"
echo "Frontend:  Open http://localhost:$FRONTEND_PORT"
echo "Press Ctrl+C to stop both."
echo ""

# Keep running until one of the two processes exits, then stop the other.
while kill -0 "$BE_PID" 2>/dev/null && kill -0 "$FE_PID" 2>/dev/null; do
  sleep 1
done
echo "One of the servers exited; stopping the other."
exit 1
