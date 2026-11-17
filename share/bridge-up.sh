#!/bin/sh
# Sourced by every xingchi-<agent> launcher: starts the local bridge if down.
# exit 1 after a failed wait means a shell that sourced this file exits too;
# install.sh runs it inside a subshell so an unreachable bridge is non-fatal.
XDIR=${XINGCHI_HOME:-$HOME/.xingchi}
. "$XDIR/env.sh"

if curl -fsS -o /dev/null 2>/dev/null "$XINGCHI_BRIDGE_URL/health/liveliness"; then
  return 0
fi

log="${TMPDIR:-/tmp}/xingchi-litellm.log"
nohup "$XDIR/start.sh" >>"$log" 2>&1 </dev/null &
attempt=0
until curl -fsS -o /dev/null 2>/dev/null "$XINGCHI_BRIDGE_URL/health/liveliness"; do
  attempt=$((attempt + 1))
  if [ "$attempt" -gt 120 ]; then
    echo "xingchi bridge did not start; see $log" >&2
    exit 1
  fi
  sleep 0.5
done
