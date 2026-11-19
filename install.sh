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

Configures Codex for Xingchi (default: $MODEL).
Stores your Xingchi API key in $XDIR/upstream.key (mode 600) and writes
config.toml and a four-model catalog under CODEX_HOME (default ~/.codex).
Connects directly to $UPSTREAM. Choose model and reasoning with /model.

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
if [ -z "$SRC" ] || [ ! -f "$SRC/lib/config.py" ] || [ ! -f "$SRC/lib/models.json" ]; then
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
echo " [1/3] Xingchi API key"
echo "============================================================"
upstream=${XINGCHI_API_KEY:-}
if [ -n "$upstream" ]; then
  echo "  using key from XINGCHI_API_KEY"
elif [ -s "$XDIR/upstream.key" ]; then
  upstream=$(cat "$XDIR/upstream.key")
  echo "  using key from $XDIR/upstream.key"
fi

if [ -z "$upstream" ]; then
  # A readable /dev/tty can still fail to open (CI, no controlling terminal).
  if [ "$ASSUME_YES" = 1 ] || ! (exec </dev/tty) 2>/dev/null; then
    die "set XINGCHI_API_KEY (your xingchiapi key) or run interactively"
  fi
  printf 'Your Xingchi API key spends paid account credits.\n' >/dev/tty
  printf 'It is stored only in %s/upstream.key (mode 600).\n' "$XDIR" >/dev/tty
  printf 'Create one at https://xingchiapi.com/keys, then paste it here\n' >/dev/tty
  printf '(input is hidden, press Enter): ' >/dev/tty
  stty -echo </dev/tty 2>/dev/null || true
  # Ctrl-C at the hidden prompt must not leave the terminal without echo.
  trap 'stty echo </dev/tty 2>/dev/null || true; exit 130' INT TERM HUP
  IFS= read -r upstream </dev/tty || upstream=""
  stty echo </dev/tty 2>/dev/null || true
  trap - INT TERM HUP
  printf '\n' >/dev/tty
  [ -n "$upstream" ] || die "no key read"
fi
# Pasting from a browser can carry spaces or CR; trim or the key fails with 401.
upstream=$(printf '%s' "$upstream" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
[ -n "$upstream" ] || die "empty API key"
printf '%s\n' "$upstream" > "$XDIR/upstream.key"
chmod 600 "$XDIR/upstream.key"

# -----------------------------------------------------------------------------
# STEP 2: Codex CLI
# -----------------------------------------------------------------------------
echo
echo "============================================================"
echo " [2/3] Codex CLI"
echo "============================================================"
cli_version=""
if command -v codex >/dev/null 2>&1; then
  cli_version=$(codex --version 2>/dev/null || true)
fi
if python3 "$SRC/lib/config.py" check-cli "$cli_version" >/dev/null 2>&1; then
  echo "  codex already installed: $cli_version"
else
  echo "  installing/updating @openai/codex (0.170.0 or newer required)..."
  if command -v npm >/dev/null 2>&1; then
    npm install -g @openai/codex || die "npm install -g @openai/codex failed"
  else
    die "npm is missing. Install Node.js, then: npm install -g @openai/codex"
  fi
  command -v codex >/dev/null 2>&1 || \
    die "codex is not on PATH; add npm's global bin directory, then rerun the installer"
  cli_version=$(codex --version 2>/dev/null || true)
  python3 "$SRC/lib/config.py" check-cli "$cli_version" || \
    die "Codex update did not install a compatible CLI"
fi

# -----------------------------------------------------------------------------
# STEP 3: Write Codex config and launchers
# -----------------------------------------------------------------------------
echo
echo "============================================================"
echo " [3/3] Installing the model catalog, reasoning menus and launchers"
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

echo
echo "============================================================"
echo " Installation complete"
echo "============================================================"
echo "  api:   $UPSTREAM"
echo
echo "Start Codex with:"
if command -v xingchi-codex >/dev/null 2>&1; then
  echo "  xingchi-codex"
else
  echo "  $BIN/xingchi-codex      (PATH updates in a new terminal)"
fi
echo 'Choose your model and reasoning level with /model in Codex.'
echo "Check the setup with:"
if command -v xingchi >/dev/null 2>&1; then
  echo "  xingchi"
else
  echo "  $BIN/xingchi"
fi
