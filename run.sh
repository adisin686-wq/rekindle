#!/bin/bash
# Starts RekindleNow + a public tunnel. Prints the webhook URL for Twilio.
cd "$(dirname "$0")"
pkill -f "uvicorn rekindle.main" 2>/dev/null; pkill -f "cloudflared tunnel" 2>/dev/null
mkdir -p data
.venv/bin/uvicorn rekindle.main:app --host 0.0.0.0 --port 8000 > data/server.log 2>&1 &
./bin/cloudflared tunnel --url http://localhost:8000 --no-autoupdate > data/tunnel.log 2>&1 &
for i in $(seq 1 30); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' data/tunnel.log | head -1)
  [ -n "$URL" ] && break; sleep 1
done
echo "$URL" > data/base_url.txt
echo "Dashboard:      http://localhost:8000"
echo "Public URL:     $URL"
echo "Twilio webhook: $URL/whatsapp"
echo "Voice (iPhone): $URL/voice"
