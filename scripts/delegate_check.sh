#!/usr/bin/env bash
# Boot headless Chrome, click the dashboard's action buttons, tear down.
#
# What a delegated handler RECEIVES is a property of the running page: the
# markup was well-formed and the handler existed while every button silently
# passed one mangled string. Same shape as ui_check.sh, same fail-closed rule:
# no browser means exit 2, never a silent pass.
set -euo pipefail

PORT="${CHROME_DEBUG_PORT:-9224}"
PROFILE="$(mktemp -d)"

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
  echo "No Chrome/Chromium found. This check needs a real browser engine:" >&2
  echo "what a click actually passes cannot be read off the markup." >&2
  exit 2
fi

# --allow-file-access-from-files: the fixture loads the real stylesheet from
# disk, so the page and its CSS are both file:// origins.
"$CHROME" --headless=new --disable-gpu --no-first-run --allow-file-access-from-files \
  --remote-debugging-port="$PORT" --user-data-dir="$PROFILE" about:blank \
  >"$PROFILE/chrome.log" 2>&1 &
CHROME_PID=$!
# Wait for Chrome to actually exit before removing its profile, otherwise it
# is still writing and rm reports "Directory not empty" -- noise that reads
# like a failure in CI logs.
trap 'kill "$CHROME_PID" 2>/dev/null || true; wait "$CHROME_PID" 2>/dev/null || true; rm -rf "$PROFILE" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if curl -sf -m 2 "http://127.0.0.1:$PORT/json/version" >/dev/null; then break; fi
  sleep 1
done

CHROME_DEBUG_PORT="$PORT" node "$(dirname "$0")/delegate_check.mjs"
