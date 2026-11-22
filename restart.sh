#!/bin/bash
# Restart only the app (keeps the tunnel URL) — run after editing .env
cd "$(dirname "$0")"
pkill -f "uvicorn rekindle.main" 2>/dev/null; sleep 1
.venv/bin/uvicorn rekindle.main:app --host 0.0.0.0 --port 8000 > data/server.log 2>&1 &
sleep 3; curl -s localhost:8000/api/config; echo
