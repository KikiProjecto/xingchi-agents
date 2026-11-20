#!/usr/bin/env bash
# Approximate static-context cost of the Claude setup. chars/4 = tokens.
set -u
D="${CLAUDE_DIR:-$HOME/.claude}"
tok() { echo $(( ($1 + 3) / 4 )); }
fm() {
  awk 'NR==1 && /^---$/{inf=1; next} inf && /^---$/{exit} !inf{next}
       /^description:/{cap=1; print; next}
       /^name:/{print}
       /^[A-Za-z_-]+:/{cap=0}
       cap{print}' "$1"
}

skills=0; schars=0; rows=""
for f in "$D"/skills/*/SKILL.md; do
  [ -f "$f" ] || continue
  c=$(fm "$f" | wc -c)
  skills=$((skills + 1)); schars=$((schars + c))
  rows+="$c $(basename "$(dirname "$f")")"$'\n'
done

agents=0; achars=0
for f in "$D"/agents/*.md; do
  [ -f "$f" ] || continue
  agents=$((agents + 1)); achars=$((achars + $(fm "$f" | wc -c)))
done

cmds=$(find "$D/commands" -name '*.md' 2>/dev/null | wc -l)

mdchars=0
for f in "$D/CLAUDE.md" "$HOME/CLAUDE.md" "$PWD/CLAUDE.md" "$PWD/AGENTS.md"; do
  [ -f "$f" ] && mdchars=$((mdchars + $(wc -c <"$f")))
done

mcp=$(jq -r '[(.mcpServers // {} | keys[])] | length' "$HOME/.claude.json" 2>/dev/null || echo 0)
proj_mcp=$(jq -r '[.projects // {} | to_entries[] | .value.mcpServers // {} | keys[]] | length' "$HOME/.claude.json" 2>/dev/null || echo 0)

printf 'component           count  ~tokens\n'
printf 'skills              %5d  %7d\n' "$skills" "$(tok $schars)"
printf 'agents              %5d  %7d\n' "$agents" "$(tok $achars)"
printf 'commands            %5d  %7s\n' "$cmds" '(on demand)'
printf 'CLAUDE.md+AGENTS.md %5s  %7d\n' '-' "$(tok $mdchars)"
printf 'MCP user/project    %5d  %7s\n' "$((mcp + proj_mcp))" '(names only)'
jq -r '(.mcpServers // {} | keys[]) as $k | "  user: \($k)"' "$HOME/.claude.json" 2>/dev/null
printf 'TOTAL static        %5s  %7d\n' '-' "$(tok $((schars + achars + mdchars)))"
printf '\nheaviest skills (chars):\n'
printf '%s' "$rows" | sort -rn | head -10 | while read -r c n; do printf '  %6d  %s\n' "$c" "$n"; done
