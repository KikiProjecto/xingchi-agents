# xingchi-agents

Point any coding agent at one local endpoint backed by the xingchi API.

The installer runs a LiteLLM bridge on `127.0.0.1:4010`, translates it into the
native config format of every agent you pick, and puts a `xingchi-<agent>`
launcher on your PATH. The bridge starts automatically when a launcher runs.

## Install

macOS and Linux (any distro):

```sh
curl -fsSL https://raw.githubusercontent.com/kikiprojecto/xingchi-agents/main/install.sh | sh
```

Windows (PowerShell 5.1+):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/kikiprojecto/xingchi-agents/main/install.ps1 | iex"
```

Both commands print a menu:

```
CHOOSE AGENTS YOU WANT TO SET:
  1) claude    [installed]
  2) hermes    [missing]
  ...
Numbers, names or "all" (blank = installed agents):
```

Enter numbers (`1 4`), names (`claude codex`), `all`, or press Enter to take the
default. Agents marked `[missing]` are still configured, so the CLI works as
soon as you install it.

You need a xingchi API key. Create one at
[xingchiapi.com/keys](https://xingchiapi.com/keys) -> sign in/create your account first, click **Create key**,
then copy it. The installer asks for it once and stores it in
`~/.xingchi/upstream.key` (mode 600). It generates a separate random key for
the local bridge, so no key is ever baked into this repo.

Non-interactive:

```sh
XINGCHI_API_KEY=... sh install.sh --agents claude,codex --yes
```

## Requirements

- curl and tar (macOS/Linux); curl.exe (Windows 10 1803+)
- Python 3.8+ with venv (installed automatically with apt/dnf/pacman/zypper/apk/brew or winget when missing)
- An agent CLI to launch. The installer does not install the agents themselves.

## Agents

| Agent | Writes | Status |
| --- | --- | --- |
| Claude Code | `~/.xingchi/claude-settings.json` | tested |
| Hermes | `~/.hermes/config.yaml` (+ `.env`) | tested; needs `~/.hermes` to exist first |
| opencode | `~/.config/opencode/opencode.json` | tested |
| Kilo | `~/.config/kilo/kilo.jsonc` | tested |
| Pi | `~/.pi/agent/models.json` | tested |
| Gemini CLI | `~/.gemini/settings.json` | tested |
| Codex | `~/.codex/config.toml` | config follows the official docs; not run against the Codex binary |
| OpenClaw | `~/.openclaw/openclaw.json` | config follows the official docs; not run against the OpenClaw binary |
| Antigravity (`agy`) | `~/.gemini/antigravity-cli/settings.json` | needs Google sign-in; routing unverified |

Models: `gpt-6-astra` (default) and `gpt-6.1-sol`.

Existing files are merged, not replaced: unrelated settings survive, and every
file the installer rewrites is copied to `<file>.xingchi.bak` first. `agy`
entries with `provider_id: "xingchi"` are refreshed in place on re-run.

## Use

```sh
xingchi-claude
xingchi-codex
xingchi-pi
xingchi-gemini
xingchi            # bridge status + which agent CLIs are installed
```

Each launcher starts the bridge if it is down, waits for it, then execs the
agent. On Windows the launchers are `xingchi-<agent>.cmd` in
`%LOCALAPPDATA%\xingchi\bin`.

## What lands on disk

macOS/Linux, under `~/.xingchi`:

| File | Purpose |
| --- | --- |
| `litellm.yaml` | bridge config, master key = local bridge key |
| `start.sh` | starts the bridge on 127.0.0.1:4010 |
| `bridge-up.sh` | health check + lazy start, sourced by launchers |
| `env.sh` | `XINGCHI_BRIDGE_URL`, `XINGCHI_BRIDGE_KEY` |
| `upstream.key` | your xingchi API key (600) |
| `bridge.key` | generated local bridge key (600) |
| `claude-settings.json` | Claude Code settings passed by the launcher |
| `venv/` | LiteLLM installed with pip |

Windows uses `%USERPROFILE%\.xingchi` with `start.cmd`, `env.cmd`,
`bridge-up.cmd` equivalents.

## Troubleshooting

```sh
curl http://127.0.0.1:4010/health/liveliness   # bridge alive?
tail -n 50 "${TMPDIR:-/tmp}/xingchi-litellm.log"
```

- `bridge: down`: run `~/.xingchi/start.sh` in the foreground to see the error.
- `bridge check: upstream returned HTTP 401`: the xingchi key is wrong or
  expired. Re-run the installer with `XINGCHI_API_KEY=...` or delete
  `~/.xingchi/upstream.key` and run it interactively.
- `bridge check: upstream returned HTTP 403`: the upstream account cannot use
  that model.
- `command not found: xingchi-claude`: open a new terminal, or add
  `~/.local/bin` (Windows: `%LOCALAPPDATA%\xingchi\bin`) to PATH yourself.
- Restore an agent config: `mv <file>.xingchi.bak <file>`.

The smoke test after install is informational. A DNS or upstream outage at
install time does not break the local bridge; retry the launcher later.

## Security

- The bridge binds to `127.0.0.1` only and requires the generated local key.
- Secrets live in `~/.xingchi` (mode 600/700), never in this repository.
- Agent configs contain the local bridge key, not your xingchi key.
- The installer never edits shell startup file content beyond adding one PATH
  line, and never touches `~/.claude/settings.json`.

## Uninstall

```sh
rm -f ~/.local/bin/xingchi ~/.local/bin/xingchi-*
rm -rf ~/.xingchi
```

Windows:

```powershell
Remove-Item "$env:LOCALAPPDATA\xingchi" -Recurse -Force
```

Then remove the `xingchi` provider block from each agent config, or restore its
`.xingchi.bak` copy.
