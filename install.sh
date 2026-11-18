#!/bin/sh
# xingchi-codex installer for macOS and Linux.
# Points the Codex CLI at the Xingchi upstream (OpenAI Responses API).
# No local proxy, one key.
set -eu

REPO=${XINGCHI_REPO:-kikiprojecto/xingchi-codex}
BRANCH=${XINGCHI_BRANCH:-main}
XDIR=${XINGCHI_HOME:-$HOME/.xingchi}
BIN=${XINGCHI_BIN:-$HOME/.local/bin}
UPSTREAM=${XINGCHI_UPSTREAM:-https://api.xingchiapi.com/v1}
MODEL=gpt-6.1-sol

die() { echo "error: $*" >&2; exit 1; }

usage() {
  cat <<EOF
usage: install.sh [--yes]

Configures the Codex CLI for the Xingchi upstream (model $MODEL).
Stores your Xingchi API key in $XDIR/upstream.key (mode 600) and writes
~/.codex/config.toml to use $UPSTREAM.

  --yes     never prompt; requires XINGCHI_API_KEY
EOF
}

ASSUME_YES=0
while [ $# -gt 0 ]; do
  case $1 in
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
  echo "downloading $REPO ($BRANCH)..."
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" \
    | tar -xz -C "$bootstrap" || die "download failed"
  exec sh "$bootstrap/xingchi-codex-$BRANCH/install.sh" "$@"
fi

# Pre-flight: Python 3 (used to merge ~/.codex/config.toml safely)
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 missing, attempting automatic installation..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y python3
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm python
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3
  elif command -v apk >/dev/null 2>&1; then
    sudo apk add python3
  elif command -v brew >/dev/null 2>&1; then
    brew install python
  fi
  command -v python3 >/dev/null 2>&1 || die "install python3, then re-run installer"
fi

umask 077
mkdir -p "$XDIR" "$BIN"
chmod 700 "$XDIR"

# -----------------------------------------------------------------------------
# STEP 1: Xingchi API key
# -----------------------------------------------------------------------------
echo
echo "============================================================"
echo " [1/4] Xingchi API key"
echo "============================================================"
upstream=${XINGCHI_API_KEY:-}
if [ -n "$upstream" ]; then
  echo "  using key from XINGCHI_API_KEY"
elif [ -s "$XDIR/upstream.key" ]; then
  upstream=$(cat "$XDIR/upstream.key")
  echo "  using key from $XDIR/upstream.key"
fi

if [ -z "$upstream" ]; then
  if [ "$ASSUME_YES" = 1 ] || [ ! -r /dev/tty ]; then
    die "set XINGCHI_API_KEY (your xingchiapi key) or run interactively"
  fi
  printf 'Your Xingchi API key spends paid account credits.\n' >/dev/tty
  printf 'It is stored only in %s/upstream.key (mode 600).\n' "$XDIR" >/dev/tty
  printf 'Create one at https://xingchiapi.com/keys, then paste it here\n' >/dev/tty
  printf '(input is hidden, press Enter): ' >/dev/tty
  stty -echo </dev/tty 2>/dev/null || true
  IFS= read -r upstream </dev/tty || die "no key read"
  stty echo </dev/tty 2>/dev/null || true
  printf '\n' >/dev/tty
fi
[ -n "$upstream" ] || die "empty API key"
printf '%s\n' "$upstream" > "$XDIR/upstream.key"
chmod 600 "$XDIR/upstream.key"

# -----------------------------------------------------------------------------
# STEP 2: Codex CLI
# -----------------------------------------------------------------------------
echo
echo "============================================================"
echo " [2/4] Codex CLI"
echo "============================================================"
if command -v codex >/dev/null 2>&1; then
  echo "  codex already installed: $(codex --version 2>/dev/null | head -n 1)"
else
  echo "  codex not found, installing @openai/codex..."
  if command -v npm >/dev/null 2>&1; then
    npm install -g @openai/codex || die "npm install -g @openai/codex failed"
  else
    die "npm is missing. Install Node.js, then: npm install -g @openai/codex"
  fi
  command -v codex >/dev/null 2>&1 || \
    echo "  note: codex installed but not on PATH yet; open a new terminal or add npm's global bin"
fi

# -----------------------------------------------------------------------------
# STEP 3: Write Codex config and launchers
# -----------------------------------------------------------------------------
echo
echo "============================================================"
echo " [3/4] Configuring Codex and installing launchers"
echo "============================================================"
XINGCHI_API_KEY=$upstream XINGCHI_UPSTREAM=$UPSTREAM XINGCHI_HOME=$XDIR \
  python3 "$SRC/lib/config.py" codex || die "config for codex failed"

cp "$SRC/bin/xingchi-codex" "$BIN/xingchi-codex"
cp "$SRC/bin/xingchi" "$BIN/xingchi"
chmod 755 "$BIN/xingchi-codex" "$BIN/xingchi"
echo "  installed $BIN/xingchi-codex"

# Ensure PATH in shell rc
case ":$PATH:" in
  *":$BIN:"*) : ;;
  *)
    case "${SHELL:-}" in
      */fish)
        rc="$HOME/.config/fish/config.fish"
        mkdir -p "$(dirname "$rc")"
        if ! grep -qs "xingchi-codex PATH" "$rc"; then
          printf '\n# xingchi-codex PATH\nfish_add_path "%s"\n' "$BIN" >> "$rc"
        fi
        ;;
      *)
        rc="$HOME/.profile"
        case "${SHELL:-}" in
          */zsh) rc="$HOME/.zshrc" ;;
          */bash) rc="$HOME/.bashrc" ;;
        esac
        if ! grep -qs "xingchi-codex PATH" "$rc"; then
          printf '\n# xingchi-codex PATH\nexport PATH="%s:$PATH"\n' "$BIN" >> "$rc"
        fi
        ;;
    esac
    echo "  PATH added to $rc (open a new terminal if commands are not found)"
    ;;
esac

# -----------------------------------------------------------------------------
# STEP 4: Verify the key against the upstream
# -----------------------------------------------------------------------------
echo
echo "============================================================"
echo " [4/4] Verification"
echo "============================================================"
resp=$(mktemp)
code=$(curl -s -o "$resp" -w '%{http_code}' --max-time 20 \
  -H "Authorization: Bearer $upstream" \
  -H 'User-Agent: codex_cli_rs/0.170.0' \
  "$UPSTREAM/models" || true)
case "$code" in
  200) echo "  [OK] key accepted; upstream offers: $(tr -d '\n' < "$resp" | head -c 200)" ;;
  401) echo "  [WARN] upstream returned 401: check your key at https://xingchiapi.com/keys" ;;
  403) echo "  [WARN] upstream returned 403: account balance or permission check required" ;;
  *)   echo "  [INFO] upstream /models returned HTTP $code" ;;
esac
rm -f "$resp"

echo
echo "============================================================"
echo " Installation complete"
echo "============================================================"
echo "  model: $MODEL"
echo "  api:   $UPSTREAM"
echo
echo "Start Codex with:"
echo "  xingchi-codex"
echo "Check the setup with:"
echo "  xingchi"
