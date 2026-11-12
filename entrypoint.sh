#!/bin/sh
# Everything the app creates is for its own user alone: the database and its
# WAL hold password hashes, payout addresses and the fleet layout, and the key
# files hold the session-signing key and the worker's own key. With the default
# 022 they were born world-readable, the key files until their chmod a moment
# later.
umask 077

# Already running as non-root (e.g. Unraid --user flag) — skip privilege setup
if [ "$(id -u)" != "0" ]; then
  exec "$@"
fi

# Ensure data and fleet directories are writable by cashpilot
chown cashpilot:root /data 2>/dev/null || true
# Closes the files an older release created world-readable: nobody else can
# reach them through a folder only its owner may enter.
chmod 700 /data 2>/dev/null || true
if [ -d "/fleet" ]; then
  chown cashpilot:root /fleet 2>/dev/null || true
fi

# If Docker socket exists, ensure the cashpilot user can access it
SOCK=/var/run/docker.sock
if [ -S "$SOCK" ]; then
  SOCK_GID=$(stat -c '%g' "$SOCK" 2>/dev/null || stat -f '%g' "$SOCK" 2>/dev/null)
  if [ -n "$SOCK_GID" ] && [ "$SOCK_GID" != "0" ]; then
    addgroup -g "$SOCK_GID" -S docker 2>/dev/null || true
    addgroup cashpilot docker 2>/dev/null || true
  else
    # GID 0 means root owns the socket — add cashpilot to root group
    addgroup cashpilot root 2>/dev/null || true
  fi
fi

exec su-exec cashpilot "$@"
