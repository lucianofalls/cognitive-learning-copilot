#!/usr/bin/env bash
# Stops a running instance started with scripts/start.sh by port lookup.
# Uvicorn/FastAPI does not daemonize itself in this project (start.sh runs
# it in the foreground), so this is a convenience for when it was
# backgrounded manually (e.g. `scripts/start.sh &`).

set -uo pipefail

PORT="${1:-8000}"

PID="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"

if [[ -z "$PID" ]]; then
  echo "No process is listening on port $PORT."
  exit 0
fi

echo "Stopping process $PID listening on port $PORT..."
kill "$PID"
sleep 1
if kill -0 "$PID" 2>/dev/null; then
  echo "Process still alive, sending SIGKILL..."
  kill -9 "$PID"
fi
echo "Stopped."
