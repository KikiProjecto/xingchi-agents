#!/bin/sh
# Probe the Xingchi upstream for a model that GET /v1/models may not advertise.
# It tries several model ids, endpoints and client user-agents, prints only the
# status code and a short body, and redacts your API key from all output.
#
# usage:
#   sh scripts/probe-astra.sh
#   XINGCHI_KEY_FILE=/path/to/key sh scripts/probe-astra.sh
set -u

UPSTREAM=${XINGCHI_UPSTREAM:-https://api.xingchiapi.com/v1}
KEY_FILE=${XINGCHI_KEY_FILE:-${XINGCHI_HOME:-$HOME/.xingchi}/upstream.key}
KEY=$(cat "$KEY_FILE" 2>/dev/null)
[ -n "$KEY" ] || { echo "error: no API key at $KEY_FILE" >&2; exit 1; }

redact() { sed "s#$KEY#<redacted>#g"; }

probe() { # label method url user-agent data
  label=$1
  method=$2
  url=$3
  ua=$4
  data=${5:-}
  printf '\n### %s\n' "$label"
  if [ "$method" = POST ]; then
    curl -sS --max-time 30 -X POST "$url" \
      -H "Authorization: Bearer $KEY" \
      -H "Content-Type: application/json" \
      -H "User-Agent: $ua" \
      -H "x-openai-actor-authorization: local-image-extension" \
      -d "$data" -w '\nHTTP %{http_code}\n' 2>&1 | redact | head -c 600
  else
    curl -sS --max-time 30 "$url" \
      -H "Authorization: Bearer $KEY" \
      -H "User-Agent: $ua" \
      -w '\nHTTP %{http_code}\n' 2>&1 | redact | head -c 600
  fi
  printf '\n'
}

CODEX_UA='codex_cli_rs/0.170.0'
OPENCODE_UA='opencode/0.9.0'
CLAUDE_UA='claude-cli/2.0.0 (external, cli)'

echo "upstream: $UPSTREAM"
echo "key file: $KEY_FILE (contents not shown)"

probe 'catalog as codex' GET "$UPSTREAM/models" "$CODEX_UA"
probe 'catalog as opencode' GET "$UPSTREAM/models" "$OPENCODE_UA"
probe 'catalog as claude' GET "$UPSTREAM/models" "$CLAUDE_UA"

for model in gpt-6-astra gpt-6.1-astra gpt-6-astra-code gpt-6-astra-thinking astra; do
  body=$(printf '{"model":"%s","input":"hi"}' "$model")
  probe "responses/$model (codex UA)" POST "$UPSTREAM/responses" "$CODEX_UA" "$body"
  probe "responses/$model (opencode UA)" POST "$UPSTREAM/responses" "$OPENCODE_UA" "$body"
done

for model in gpt-6-astra gpt-6.1-astra; do
  body=$(printf '{"model":"%s","messages":[{"role":"user","content":"hi"}]}' "$model")
  probe "chat/$model (opencode UA)" POST "$UPSTREAM/chat/completions" "$OPENCODE_UA" "$body"
done

probe 'model detail gpt-6-astra' GET "$UPSTREAM/models/gpt-6-astra" "$CODEX_UA"

echo
echo 'done. Paste this whole output back (it contains no key).'
