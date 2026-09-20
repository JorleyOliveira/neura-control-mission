#!/usr/bin/env bash
# One-command deploy of the full stack (backend + frontend) to the Lightsail box.
# Usage: scripts/deploy-lightsail.sh [key-path]
# Default key: ~/.ssh/LightsailDefaultKey-us-east-1.pem (copy it there from Downloads first:
#   cp ~/Downloads/LightsailDefaultKey-us-east-1.pem ~/.ssh/LightsailDefaultKey-us-east-1.pem
#   chmod 600 ~/.ssh/LightsailDefaultKey-us-east-1.pem )
set -euo pipefail
# /Users/jorley/.ssh/LightsailDefaultKey-us-east-1.pem
KEY="${1:-$HOME/.ssh/LightsailDefaultKey-us-east-1.pem}"
SERVER="ubuntu@3.83.26.181"
BACKEND="/Users/jorley/Workspace/Repositorios/Publicos/neura-marketplace"
FRONTEND="/Users/jorley/Workspace/Repositorios/Publicos/autonomous-agent-swarm"

[ -f "$KEY" ] || { echo "Key not found: $KEY (see usage note at the top of this script)"; exit 1; }

echo "== 1/3 rsync backend + frontend (secrets in .env travel over encrypted SSH) =="
rsync -az --delete \
  --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'tmp-a2a-workspace' --exclude 'tmp-docker-workspace' --exclude 'tmp-docker-state' \
  --exclude '*.db' --exclude '*.db-shm' --exclude '*.db-wal' \
  --exclude 'output.xml' \
  -e "ssh -i $KEY" \
  "$BACKEND" "$SERVER":~/

rsync -az --delete \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '.lovable' \
  -e "ssh -i $KEY" \
  "$FRONTEND" "$SERVER":~/

echo "== 2/3 rebuild stack on the server (canonical public ports: 8080 UI, 8000 API) =="
ssh -i "$KEY" "$SERVER" bash -s <<'EOF'
set -e
cd ~/neura-marketplace
sudo docker compose down
sudo docker compose up -d --build
echo "-- waiting for health..."
for i in $(seq 1 30); do
  ok=1
  for p in 8000 8001 8002 8010 8020 8080; do
    curl -sf -m 2 "http://127.0.0.1:$p/health" > /dev/null || ok=0
  done
  [ "$ok" = "1" ] && break
  sleep 5
done
sudo docker ps --format '{{.Names}}\t{{.Status}}'
EOF

echo "== 3/3 done =="f
echo "UI :  http://3.83.26.181:8080"
echo "API:  http://3.83.26.181:8000/health"
