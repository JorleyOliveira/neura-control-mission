#!/usr/bin/env bash
# Live A2A monitor: follow a run's full inter-agent transcript plus seller negotiations.
# All database reads happen INSIDE the marcelo container (host must never open the
# containers' SQLite files directly - WAL over the mount boundary corrupts them).
#
# Usage: scripts/monitor.sh [run_id]        (defaults to the most recent run)
# Env:   SELLER_URL (default http://127.0.0.1:8020)
set -euo pipefail
cd "$(dirname "$0")/.."

SELLER_URL="${SELLER_URL:-}"
if [ -z "$SELLER_URL" ]; then
  for candidate in http://127.0.0.1:8020 http://127.0.0.1:18020; do
    if curl -sf -m 2 "$candidate/health" > /dev/null; then SELLER_URL="$candidate"; break; fi
  done
fi
RUN_ID="${1:-}"

if [ -z "$RUN_ID" ]; then
  RUN_ID=$(docker compose exec -T marcelo python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/state/neura.db")
row = conn.execute("SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
print(row[0] if row else "")
PY
)
fi

[ -n "$RUN_ID" ] || { echo "No runs found in the marcelo container state."; exit 1; }

echo "=== Seller negotiations so far (explicit buyer/seller messages) ==="
curl -sf "$SELLER_URL/negotiations" | python -m json.tool 2>/dev/null || echo "(seller unreachable at $SELLER_URL)"
echo
echo "=== Following run $RUN_ID inside the marcelo container (Ctrl+C to stop) ==="
exec docker compose exec -T marcelo python scripts/show_transcript.py --follow \
  --orchestration-db /app/state/neura.db \
  --gateway-db /app/state/neura-worker.db \
  "$RUN_ID"
