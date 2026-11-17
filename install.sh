#!/bin/sh
# xingchi-agents installer for macOS and Linux.
set -eu

REPO=${XINGCHI_REPO:-kikiprojecto/xingchi-agents}
BRANCH=${XINGCHI_BRANCH:-main}
XDIR=${XINGCHI_HOME:-$HOME/.xingchi}
BIN=${XINGCHI_BIN:-$HOME/.local/bin}
ALL_AGENTS="claude hermes opencode codex pi kilo agy gemini openclaw"

die() { echo "error: $*" >&2; exit 1; }

usage() {
  cat <<EOF
usage: install.sh [--agents LIST] [--yes]

  --agents LIST   comma or space separated names, or "all"
                  ($ALL_AGENTS)
  --yes           never prompt; requires --agents or XINGCHI_API_KEY
EOF
}

AGENTS=""
ASSUME_YES=0
while [ $# -gt 0 ]; do
  case $1 in
    --agents) [ $# -ge 2 ] || die "--agents needs a value"; AGENTS=$2; shift 2 ;;
    --agents=*) AGENTS=${1#*=}; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)
if [ -z "$SRC" ] || [ ! -f "$SRC/lib/config.py" ]; then
  command -v curl >/dev/null 2>&1 || die "curl is required to download the installer"
  command -v tar >/dev/null 2>&1 || die "tar is required to unpack the installer"
  bootstrap=$(mktemp -d)
  echo "download $REPO ($BRANCH)..."
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" \
    | tar -xz -C "$bootstrap" || die "download failed"
  exec sh "$bootstrap/xingchi-agents-$BRANCH/install.sh" "$@"
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 missing, installing..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y python3 python3-venv
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm python
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 python3-virtualenv
  elif command -v apk >/dev/null 2>&1; then
    sudo apk add python3 py3-virtualenv
  elif command -v brew >/dev/null 2>&1; then
    brew install python
  fi
  command -v python3 >/dev/null 2>&1 || die "install python3, then re-run"
fi

umask 077
mkdir -p "$XDIR" "$BIN"
chmod 700 "$XDIR"

bridge_key=""
if [ -s "$XDIR/bridge.key" ]; then bridge_key=$(cat "$XDIR/bridge.key"); fi
if [ -z "$bridge_key" ] && [ -s "$XDIR/litellm.yaml" ]; then
  bridge_key=$(sed -n 's/^ *master_key: *//p' "$XDIR/litellm.yaml" | head -1)
fi
if [ -z "$bridge_key" ]; then
  bridge_key="sk-xingchi-$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
fi
printf '%s\n' "$bridge_key" > "$XDIR/bridge.key"
chmod 600 "$XDIR/bridge.key"

litellm_bin=""
if [ -x "$XDIR/venv/bin/litellm" ]; then
  litellm_bin="$XDIR/venv/bin/litellm"
elif command -v litellm >/dev/null 2>&1; then
  litellm_bin=$(command -v litellm)
else
  echo "installing litellm[proxy] into $XDIR/venv (one time)..."
  python3 -m venv "$XDIR/venv" || die "python3 venv failed; install python3-venv"
  "$XDIR/venv/bin/python" -m pip install -q --upgrade pip
  "$XDIR/venv/bin/pip" install -q 'litellm[proxy]' || die "litellm install failed"
  litellm_bin="$XDIR/venv/bin/litellm"
fi

cat > "$XDIR/litellm.yaml" <<EOF
model_list:
  - model_name: gpt-6-astra
    litellm_params:
      model: openai/gpt-6-astra
      api_base: https://api.xingchiapi.com/v1
      api_key: os.environ/XINGCHI_API_KEY
      extra_headers:
        user-agent: "opencode/0.9.0"
  - model_name: gpt-6.1-sol
    litellm_params:
      model: openai/gpt-6.1-sol
      api_base: https://api.xingchiapi.com/v1
      api_key: os.environ/XINGCHI_API_KEY
      extra_headers:
        user-agent: "opencode/0.9.0"

litellm_settings:
  # gpt-6-astra rejects some parameters clients send (reasoning_effort).
  drop_params: true

general_settings:
  master_key: $bridge_key
  disable_model_info_refresh: true
EOF
chmod 600 "$XDIR/litellm.yaml"

cat > "$XDIR/start.sh" <<EOF
#!/bin/sh
# Local OpenAI/Anthropic/Responses bridge to xingchiapi on 127.0.0.1:4010.
set -eu
XINGCHI_API_KEY=\$(cat "\$HOME/.xingchi/upstream.key")
export XINGCHI_API_KEY
exec "$litellm_bin" --config "\$HOME/.xingchi/litellm.yaml" --host 127.0.0.1 --port 4010
EOF
chmod 700 "$XDIR/start.sh"

cat > "$XDIR/env.sh" <<EOF
export XINGCHI_BRIDGE_URL=http://127.0.0.1:4010
export XINGCHI_BRIDGE_KEY=$bridge_key
EOF
chmod 600 "$XDIR/env.sh"

cp "$SRC/share/bridge-up.sh" "$XDIR/bridge-up.sh"
chmod 700 "$XDIR/bridge-up.sh"

agent_cmd() {
  case $1 in
    claude) echo claude ;; hermes) echo hermes ;; opencode) echo opencode ;;
    codex) echo codex ;; pi) echo pi ;; kilo) echo kilo ;; agy) echo agy ;;
    gemini) echo gemini ;; openclaw) echo openclaw ;;
  esac
}

install_hint() {
  case $1 in
    claude) echo "npm install -g @anthropic-ai/claude-code" ;;
    hermes) echo "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash" ;;
    opencode) echo "npm install -g opencode-ai" ;;
    codex) echo "npm install -g @openai/codex" ;;
    pi) echo "npm install -g @earendil-works/pi-coding-agent" ;;
    kilo) echo "npm install -g @kilocode/cli" ;;
    agy) echo "curl -fsSL https://antigravity.google/cli/install.sh | bash" ;;
    gemini) echo "npm install -g @google/gemini-cli" ;;
    openclaw) echo "npm install -g openclaw" ;;
  esac
}

npm_package() {
  case $1 in
    claude) echo @anthropic-ai/claude-code ;;
    opencode) echo opencode-ai ;;
    codex) echo @openai/codex ;;
    gemini) echo @google/gemini-cli ;;
    kilo) echo @kilocode/cli ;;
    pi) echo @earendil-works/pi-coding-agent ;;
    openclaw) echo openclaw ;;
  esac
}

ensure_npm() {
  command -v npm >/dev/null 2>&1 && return 0
  echo "installing Node.js (needed for npm-based agents)..."
  if command -v brew >/dev/null 2>&1; then
    brew install node || true
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y nodejs npm || true
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y nodejs npm || true
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm nodejs npm || true
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y nodejs npm || true
  elif command -v apk >/dev/null 2>&1; then
    sudo apk add nodejs npm || true
  fi
  command -v npm >/dev/null 2>&1
}

install_agent_cli() {
  a=$1
  command -v "$(agent_cmd "$a")" >/dev/null 2>&1 && return 0
  echo "installing $a..."
  pkg=$(npm_package "$a")
  if [ -n "$pkg" ]; then
    if ensure_npm; then
      npm_root=$(npm root -g 2>/dev/null || true)
      if [ -n "$npm_root" ] && [ -w "$npm_root" ]; then
        npm install -g "$pkg" || true
      elif npm install -g "$pkg" 2>/dev/null; then
        : # prefix not created yet; npm created it as this user
      else
        sudo npm install -g "$pkg" || true
      fi
    fi
  elif [ "$a" = hermes ]; then
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash || true
  elif [ "$a" = agy ]; then
    curl -fsSL https://antigravity.google/cli/install.sh | bash || true
  fi
  PATH="$HOME/.local/bin:$PATH"; export PATH
  if command -v "$(agent_cmd "$a")" >/dev/null 2>&1; then
    echo "  installed $a"
  else
    printf '  note: %s still missing. Install manually: %s\n' "$a" "$(install_hint "$a")"
  fi
}

agent_at() {
  n=0
  for a in $ALL_AGENTS; do
    n=$((n + 1))
    if [ "$n" = "$1" ]; then echo "$a"; return 0; fi
  done
  return 1
}

parse_selection() {
  input=$1
  case $input in
    "") echo "$default"; return 0 ;;
    all|a) echo "$ALL_AGENTS"; return 0 ;;
  esac
  picked=""
  for token in $(echo "$input" | tr ',' ' '); do
    case $token in
      ''|*[!0-9]*) wanted=$token ;;
      *) wanted=$(agent_at "$token") || { echo "error: no agent $token" >&2; return 1; } ;;
    esac
    case " $ALL_AGENTS " in
      *" $wanted "*) picked="$picked $wanted" ;;
      *) echo "error: unknown agent: $token" >&2; return 1 ;;
    esac
  done
  echo "$picked"
}

installed=""
for a in $ALL_AGENTS; do
  if command -v "$(agent_cmd "$a")" >/dev/null 2>&1; then installed="$installed $a"; fi
done
installed=${installed# }
default=${installed:-$ALL_AGENTS}

if [ -n "$AGENTS" ]; then
  selected=$(parse_selection "$AGENTS") || exit 1
elif [ "$ASSUME_YES" = 1 ]; then
  selected=$default
else
  echo
  echo "CHOOSE AGENTS YOU WANT TO SET:"
  n=0
  for a in $ALL_AGENTS; do
    n=$((n + 1))
    if command -v "$(agent_cmd "$a")" >/dev/null 2>&1; then state=installed; else state=missing; fi
    printf '  %d) %-9s [%s]\n' "$n" "$a" "$state"
  done
  printf '\nNumbers, names or "all" (blank = %s): ' "$default"
  IFS= read -r answer </dev/tty || die "no input; pass --agents"
  selected=$(parse_selection "$answer") || exit 1
fi
[ -n "$selected" ] || die "no agents selected"

upstream=${XINGCHI_API_KEY:-}
if [ -z "$upstream" ] && [ -s "$XDIR/key" ]; then upstream=$(cat "$XDIR/key"); fi
if [ -z "$upstream" ] && [ -s "$XDIR/upstream.key" ]; then upstream=$(cat "$XDIR/upstream.key"); fi
if [ -z "$upstream" ]; then
  if [ "$ASSUME_YES" = 1 ] || [ ! -r /dev/tty ]; then
    die "set XINGCHI_API_KEY (your xingchiapi key) or run interactively"
  fi
  printf '\nCreate a key at https://xingchiapi.com/keys, copy it, then\n' >/dev/tty
  printf 'paste it here (input is hidden, press Enter): ' >/dev/tty
  stty -echo </dev/tty 2>/dev/null || true
  IFS= read -r upstream </dev/tty || die "no key read"
  stty echo </dev/tty 2>/dev/null || true
  printf '\n' >/dev/tty
fi
[ -n "$upstream" ] || die "empty API key"
printf '%s\n' "$upstream" > "$XDIR/upstream.key"
chmod 600 "$XDIR/upstream.key"

configure_agent() {
  a=$1
  install_agent_cli "$a"
  if [ "$a" = hermes ] && [ ! -f "$HOME/.hermes/config.yaml" ]; then
    echo "skip hermes: run 'hermes' once to create ~/.hermes/config.yaml, then re-run"
    return 0
  fi
  XINGCHI_BRIDGE_KEY=$bridge_key XINGCHI_URL=http://127.0.0.1:4010 \
    XINGCHI_HOME=$XDIR python3 "$SRC/lib/config.py" "$a" \
    || die "config for $a failed"
  cp "$SRC/bin/xingchi-$a" "$BIN/xingchi-$a"
  chmod 755 "$BIN/xingchi-$a"
}

for a in $selected; do configure_agent "$a"; done

cp "$SRC/bin/xingchi" "$BIN/xingchi"
chmod 755 "$BIN/xingchi"

case ":$PATH:" in
  *":$BIN:"*) : ;;
  *)
    case "${SHELL:-}" in
      */fish)
        rc="$HOME/.config/fish/config.fish"
        mkdir -p "$(dirname "$rc")"
        if ! grep -qs "xingchi-agents PATH" "$rc"; then
          printf '\n# xingchi-agents PATH\nfish_add_path "%s"\n' "$BIN" >> "$rc"
        fi
        ;;
      *)
        rc="$HOME/.profile"
        case "${SHELL:-}" in
          */zsh) rc="$HOME/.zshrc" ;;
          */bash) rc="$HOME/.bashrc" ;;
        esac
        if ! grep -qs "xingchi-agents PATH" "$rc"; then
          printf '\n# xingchi-agents PATH\nexport PATH="%s:$PATH"\n' "$BIN" >> "$rc"
        fi
        ;;
    esac
    echo "PATH updated in $rc (open a new terminal)"
    ;;
esac

echo
echo "starting bridge..."
XINGCHI_HOME=$XDIR; export XINGCHI_HOME
( . "$XDIR/bridge-up.sh" ) || echo "warning: bridge did not start (see ${TMPDIR:-/tmp}/xingchi-litellm.log)"

smoke=$(mktemp)
code=$(curl -s -o "$smoke" -w '%{http_code}' --max-time 60 \
  -H "Authorization: Bearer $bridge_key" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-6-astra","messages":[{"role":"user","content":"Reply with OK"}],"max_tokens":4}' \
  http://127.0.0.1:4010/v1/chat/completions || true)
if [ "$code" = 200 ]; then
  echo "bridge check: OK"
else
  echo "bridge check: upstream returned HTTP $code"
  head -c 300 "$smoke"
  echo
fi
rm -f "$smoke"

echo
echo "done. configured:$selected"
echo "start an agent with: xingchi-claude | xingchi-pi | xingchi-gemini ..."
echo "status: xingchi"
