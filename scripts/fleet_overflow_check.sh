#!/usr/bin/env bash
# Boot headless Chrome and the demo UI, check that /fleet never scrolls
# sideways at 320 to 2560 px, tear both down. See fleet_overflow_check.mjs.
#
# Same fail-closed shape as legibility_check.sh: no browser or no UI means
# exit 2, never a silent pass.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CDP_PORT="${CHROME_DEBUG_PORT:-9224}"
UI_PORT="${UI_PORT:-8110}"
PROFILE="$(mktemp -d)"
DATA="$(mktemp -d)/cp-fleet-overflow"

CHROME=""
for candidate in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  "$(command -v google-chrome || true)" \
  "$(command -v chromium || true)" \
  "$(command -v chromium-browser || true)"; do
  if [ -x "$candidate" ]; then CHROME="$candidate"; break; fi
done
if [ -z "$CHROME" ]; then
  echo "No Chrome/Chromium found. Whether a page overflows is a property of" >&2
  echo "the rendered page, so this check needs a real browser." >&2
  exit 2
fi

"$CHROME" --headless=new --disable-gpu --no-first-run \
  --remote-debugging-port="$CDP_PORT" --user-data-dir="$PROFILE" about:blank \
  >"$PROFILE/chrome.log" 2>&1 &
CHROME_PID=$!
(cd "$ROOT" && exec uv run python scripts/ui_demo_seed.py "$DATA" --serve "$UI_PORT" >"$PROFILE/ui.log" 2>&1) &
UI_PID=$!
cleanup() {
  kill "$CHROME_PID" 2>/dev/null || true
  # The seed's --serve also starts two sibling UIs on the next ports.
  pkill -P "$UI_PID" 2>/dev/null || true
  kill "$UI_PID" 2>/dev/null || true
  pkill -f "ui_demo_seed.py $DATA" 2>/dev/null || true
  wait 2>/dev/null || true
  rm -rf "$PROFILE" "$(dirname "$DATA")" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  if curl -sf -m 2 "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null \
    && curl -s -m 2 -o /dev/null "http://127.0.0.1:$UI_PORT/login"; then break; fi
  sleep 1
done
if ! curl -s -m 2 -o /dev/null "http://127.0.0.1:$UI_PORT/login"; then
  echo "The demo UI did not come up on :$UI_PORT. Its log:" >&2
  cat "$PROFILE/ui.log" >&2
  exit 2
fi

CHROME_DEBUG_PORT="$CDP_PORT" UI_URL="http://127.0.0.1:$UI_PORT" node "$ROOT/scripts/fleet_overflow_check.mjs"
