#!/bin/sh
# Sourced by every xingchi-<agent> launcher: starts the local bridge if down.
# Can also be executed directly: ~/.xingchi/bridge-up.sh
XDIR=${XINGCHI_HOME:-$HOME/.xingchi}
. "$XDIR/env.sh"

_xingchi_ensure_bridge() {
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
      return 1
    fi
    sleep 0.5
  done
}

_xingchi_ensure_bridge || exit 1
