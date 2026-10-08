#!/usr/bin/env bash
# Start NetHealers with one command and check it is healthy.
#
#   scripts/start.sh          one server: builds the game if needed, serves it at http://localhost:8010
#   scripts/start.sh --dev    backend on :8010 and the game's dev server on http://localhost:5173
#
# Logs go to out/backend.log and out/game.log. Stop with: pkill -f scripts/serve.py; pkill -f vite
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# 1. Database (decision log and knowledge base). Optional: without it, everything falls back to local files.
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  docker compose up -d >/dev/null && say "Database: running (port 5435)"
else
  say "Database: Docker is not running; using local files instead"
fi

# 2. Things that must be built once.
[ -f models/diagnosis.joblib ] || { say "No diagnosis model yet. Run once:"; echo "  uv run python scripts/make_dataset.py && uv run python scripts/train_diagnosis.py"; exit 1; }
[ -f .env ] || say "No .env: the language-model roles and the policy adviser will use plain rules (copy .env.example to .env and add a key)"
[ -d web/node_modules ] || (say "Installing the game's packages..." && npm --prefix web install --silent)

# 3. Start.
pkill -f scripts/serve.py 2>/dev/null || true
if [ "${1:-}" = "--dev" ]; then
  nohup uv run python scripts/serve.py > out/backend.log 2>&1 &
  pkill -f "vite --port 5173" 2>/dev/null || true
  nohup npm --prefix web run dev -- --port 5173 --strictPort > out/game.log 2>&1 &
  url=http://localhost:5173
else
  [ -d web/dist ] && [ -z "$(find web/src -newer web/dist -type f | head -1)" ] || (say "Building the game..." && npm --prefix web run build >/dev/null)
  nohup uv run python scripts/serve.py > out/backend.log 2>&1 &
  url=http://localhost:8010
fi

# 4. Health check.
for _ in $(seq 1 40); do
  if curl -fs http://localhost:8010/health >/dev/null; then
    kb=$(curl -fs http://localhost:8010/kb | uv run python -c "import sys, json; print(json.load(sys.stdin)['passages'])" 2>/dev/null || echo 0)
    say "Backend: healthy. Knowledge base: ${kb} passages$([ "$kb" = 0 ] && echo ' (empty: run uv run python scripts/build_library.py)')"
    for _ in $(seq 1 40); do curl -fs -o /dev/null "$url" && break; sleep 0.5; done  # the dev server takes a moment
    say "Open ${url}"
    exit 0
  fi
  sleep 0.5
done
say "The backend did not start; see out/backend.log"
exit 1
