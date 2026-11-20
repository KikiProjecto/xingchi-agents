#!/usr/bin/env bash
#
# setup-symlinks.sh — converge every agent's skills directory onto one shared hub.
#
# After this runs, installing a skill once (to the hub) makes it visible to every
# agent, because each agent's `skills` dir becomes a symlink to the hub.
#
# Only run this after the user has agreed to it (see check-skills-setup.sh / SKILL.md).
#
# Usage:
#   setup-symlinks.sh [--hub <path>] [--dry-run]
#
#   --hub <path>   Hub directory to point everything at. Default: ~/.agents/skills
#   --dry-run      Print what would happen without changing anything.
#
# Safety:
#   - A directory already pointing at the hub is left untouched.
#   - A real (non-symlink) skills dir has its contents copied into the hub
#     WITHOUT overwriting (cp -rn), then the original is moved aside to a
#     timestamped .backup-* directory before the symlink is created. Nothing is
#     deleted; the backup path is printed so you can remove it later yourself.

set -euo pipefail

HOME_DIR="${HOME:?HOME not set}"
HUB="$HOME_DIR/.agents/skills"
DRY_RUN="no"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --hub) HUB="$2"; shift 2 ;;
    --dry-run) DRY_RUN="yes"; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

AGENT_DIRS=(
  "Claude Code|$HOME_DIR/.claude/skills"
  "Codex|$HOME_DIR/.codex/skills"
  "Cursor|$HOME_DIR/.cursor/skills"
  "Gemini CLI|$HOME_DIR/.gemini/skills"
  "GitHub Copilot|$HOME_DIR/.copilot/skills"
  "OpenCode|$HOME_DIR/.config/opencode/skills"
)

STAMP="$(date +%Y%m%d-%H%M%S)"

run() {
  if [ "$DRY_RUN" = "yes" ]; then
    echo "  DRY-RUN> $*"
  else
    eval "$@"
  fi
}

echo "Hub: $HUB"
[ "$DRY_RUN" = "yes" ] && echo "(dry run — no changes will be made)"
echo

run "mkdir -p \"$HUB\""

for entry in "${AGENT_DIRS[@]}"; do
  name="${entry%%|*}"
  path="${entry#*|}"
  parent="$(dirname "$path")"

  # Skip agents whose parent app dir doesn't exist (agent not installed).
  if [ ! -d "$parent" ]; then
    echo "- $name: skip (no $parent)"
    continue
  fi

  # Already a symlink resolving to the hub? Done.
  if [ -L "$path" ] && [ "$(readlink -f -- "$path" 2>/dev/null)" = "$(readlink -f -- "$HUB")" ]; then
    echo "- $name: already linked -> hub"
    continue
  fi

  # A symlink pointing elsewhere: replace it (symlinks hold no data).
  if [ -L "$path" ]; then
    echo "- $name: relinking stale symlink -> hub"
    run "rm -f \"$path\""
    run "ln -s \"$HUB\" \"$path\""
    continue
  fi

  # A real directory with contents: preserve them, then convert to a symlink.
  if [ -d "$path" ]; then
    echo "- $name: real dir -> merging into hub, then linking"
    run "cp -rn \"$path/.\" \"$HUB/\" 2>/dev/null || true"
    run "mv \"$path\" \"$path.backup-$STAMP\""
    run "ln -s \"$HUB\" \"$path\""
    echo "    backup: $path.backup-$STAMP"
    continue
  fi

  # Nothing there yet: just create the link.
  echo "- $name: creating symlink -> hub"
  run "ln -s \"$HUB\" \"$path\""
done

echo
echo "Done. Re-run check-skills-setup.sh to confirm CONVERGED=yes."
