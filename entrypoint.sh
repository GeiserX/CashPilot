#!/bin/sh
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
