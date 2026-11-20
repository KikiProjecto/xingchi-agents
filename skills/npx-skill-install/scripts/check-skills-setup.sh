#!/usr/bin/env bash
#
# check-skills-setup.sh — one-shot diagnostic for the npx-skill-install workflow.
#
# It answers the two questions you need before installing a skill with `npx skills`:
#
#   1. Is a given skill already installed?   (so you don't reinstall it)
#   2. Do the agents' skills directories all converge on a single shared hub
#      directory via symlinks?               (so you know: install ONCE vs install to MANY)
#
# Usage:
#   check-skills-setup.sh [skill-name ...]
#
#   - With no arguments: prints every installed skill plus the convergence report.
#   - With skill names:  also reports, per name, whether it is already installed.
#
# The script never modifies anything. To actually create the symlinks, use
# setup-symlinks.sh (run only after the user agrees).
#
# Output ends with a machine-readable SUMMARY block so the calling agent can act
# without re-parsing the prose above it.

set -uo pipefail

HOME_DIR="${HOME:?HOME not set}"

# Candidate agent skills directories at user/global scope, as "Display Name|path".
# These mirror the agents that `npx skills` supports. A directory that does not
# exist simply means that agent isn't set up on this machine.
AGENT_DIRS=(
  "Claude Code|$HOME_DIR/.claude/skills"
  "Codex|$HOME_DIR/.codex/skills"
  "Cursor|$HOME_DIR/.cursor/skills"
  "Gemini CLI|$HOME_DIR/.gemini/skills"
  "GitHub Copilot|$HOME_DIR/.copilot/skills"
  "OpenCode|$HOME_DIR/.config/opencode/skills"
)

# The conventional shared hub. Detection does not depend on this exact path —
# the hub is inferred from where the agent dirs actually resolve — but when no
# symlinks exist yet this is the recommended target to converge on.
DEFAULT_HUB="$HOME_DIR/.agents/skills"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }

# realpath helper that tolerates non-existent / dangling targets.
resolve() {
  # readlink -f resolves symlink chains (e.g. .claude -> .codex -> .agents).
  readlink -f -- "$1" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# 1) Installed skills
# ---------------------------------------------------------------------------
bold "== Installed skills (npx skills list -g) =="

INSTALLED_JSON=""
if command -v npx >/dev/null 2>&1; then
  # First run may download the `skills` package; it is cached afterwards.
  INSTALLED_JSON="$(npx -y skills list -g --json 2>/dev/null)"
fi

INSTALLED_NAMES=""
if [ -n "$INSTALLED_JSON" ]; then
  # Extract "name" values without requiring jq.
  INSTALLED_NAMES="$(printf '%s' "$INSTALLED_JSON" \
    | grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | sed -E 's/.*"name"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/' \
    | sort -u)"
fi

if [ -n "$INSTALLED_NAMES" ]; then
  printf '%s\n' "$INSTALLED_NAMES" | sed 's/^/  - /'
else
  echo "  (could not read installed skills — npx unavailable or offline)"
fi
echo

# ---------------------------------------------------------------------------
# 2) Convergence of agent skills directories
# ---------------------------------------------------------------------------
bold "== Agent skills directories =="

declare -A REAL_OF       # display name -> resolved real path
declare -A KIND_OF       # display name -> symlink | dir | missing
EXISTING_AGENTS=()
RESOLVED_PATHS=()

for entry in "${AGENT_DIRS[@]}"; do
  name="${entry%%|*}"
  path="${entry#*|}"
  if [ -L "$path" ]; then
    kind="symlink"
  elif [ -d "$path" ]; then
    kind="dir"
  else
    kind="missing"
  fi
  KIND_OF["$name"]="$kind"

  if [ "$kind" = "missing" ]; then
    printf '  %-16s %-8s %s\n' "$name" "[$kind]" "$path"
    continue
  fi

  real="$(resolve "$path")"
  REAL_OF["$name"]="$real"
  EXISTING_AGENTS+=("$name")
  RESOLVED_PATHS+=("$real")

  if [ "$kind" = "symlink" ]; then
    target="$(readlink -- "$path")"
    printf '  %-16s %-8s %s -> %s  (resolves to %s)\n' "$name" "[$kind]" "$path" "$target" "$real"
  else
    printf '  %-16s %-8s %s\n' "$name" "[$kind]" "$path"
  fi
done
echo

# Determine the most common resolved path (the de-facto hub).
HUB=""
if [ "${#RESOLVED_PATHS[@]}" -gt 0 ]; then
  HUB="$(printf '%s\n' "${RESOLVED_PATHS[@]}" | sort | uniq -c | sort -rn | head -1 | sed -E 's/^[[:space:]]*[0-9]+[[:space:]]+//')"
fi

# Converged == every existing agent dir resolves to the same path.
CONVERGED="no"
UNIQUE_COUNT="$(printf '%s\n' "${RESOLVED_PATHS[@]:-}" | sort -u | grep -c . || true)"
if [ "${#EXISTING_AGENTS[@]}" -ge 1 ] && [ "$UNIQUE_COUNT" = "1" ]; then
  CONVERGED="yes"
fi

# Agents that are NOT yet pointing at the hub (independent real dirs, or missing).
NOT_CONVERGED_AGENTS=()
for name in "${!KIND_OF[@]}"; do
  case "${KIND_OF[$name]}" in
    missing) NOT_CONVERGED_AGENTS+=("$name") ;;
    *) [ "${REAL_OF[$name]:-}" = "$HUB" ] || NOT_CONVERGED_AGENTS+=("$name") ;;
  esac
done

bold "== Verdict =="
if [ "$CONVERGED" = "yes" ]; then
  echo "  All present agent dirs share ONE hub: $HUB"
  echo "  -> Installing a skill ONCE makes it visible to every agent."
else
  echo "  Agent dirs do NOT all converge on one hub."
  echo "  Recommended hub: ${HUB:-$DEFAULT_HUB}"
  echo "  -> Either set up symlinks first (recommended), or install to each agent."
fi
echo

# ---------------------------------------------------------------------------
# 3) Per-skill installed check (only if names were passed)
# ---------------------------------------------------------------------------
if [ "$#" -gt 0 ]; then
  bold "== Requested skills =="
  for want in "$@"; do
    if printf '%s\n' "$INSTALLED_NAMES" | grep -qx -- "$want"; then
      echo "  - $want: INSTALLED"
    else
      echo "  - $want: not installed"
    fi
  done
  echo
fi

# ---------------------------------------------------------------------------
# Machine-readable summary
# ---------------------------------------------------------------------------
bold "== SUMMARY =="
echo "CONVERGED=$CONVERGED"
echo "HUB=${HUB:-$DEFAULT_HUB}"
echo "DEFAULT_HUB=$DEFAULT_HUB"
echo "EXISTING_AGENTS=${EXISTING_AGENTS[*]:-}"
echo "NOT_CONVERGED_AGENTS=${NOT_CONVERGED_AGENTS[*]:-}"
if [ "$#" -gt 0 ]; then
  for want in "$@"; do
    if printf '%s\n' "$INSTALLED_NAMES" | grep -qx -- "$want"; then
      echo "SKILL_INSTALLED:$want=yes"
    else
      echo "SKILL_INSTALLED:$want=no"
    fi
  done
fi
