#!/usr/bin/env bash
# Boot headless Chrome, point ui_check.mjs at a running CashPilot UI, tear down.
#
# Verifies in a real browser what static analysis cannot see: that no CSP
# violation fires and no handler silently stopped working.
set -euo pipefail

URL="${1:-http://127.0.0.1:8099/onboarding}"
PORT="${CHROME_DEBUG_PORT:-9222}"
PROFILE="$(mktemp -d)"

CHROME=""
for candidate in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  "$(command -v google-chrome || true)" \
  "$(command -v chromium || true)"; do
  if [ -x "$candidate" ]; then CHROME="$candidate"; break; fi
done
if [ -z "$CHROME" ]; then
  echo "No Chrome/Chromium found. This check needs a real browser engine; a" >&2
  echo "static parse cannot see a CSP violation." >&2
  exit 2
fi

"$CHROME" --headless=new --disable-gpu --no-first-run \
  --remote-debugging-port="$PORT" --user-data-dir="$PROFILE" about:blank \
  >"$PROFILE/chrome.log" 2>&1 &
CHROME_PID=$!
trap 'kill "$CHROME_PID" 2>/dev/null || true; rm -rf "$PROFILE"' EXIT

for _ in $(seq 1 30); do
  if curl -sf -m 2 "http://127.0.0.1:$PORT/json/version" >/dev/null; then break; fi
  sleep 1
done

node "$(dirname "$0")/ui_check.mjs" "$URL"
