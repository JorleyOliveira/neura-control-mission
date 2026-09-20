#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$ROOT/data/agency-agents"
if [ -d "$TARGET/.git" ]; then
  git -C "$TARGET" pull --ff-only
else
  rm -rf "$TARGET"
  git clone --depth 1 https://github.com/msitarzewski/agency-agents.git "$TARGET"
fi
echo "Agency Agents ready at $TARGET"
