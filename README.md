# xingchi-agents

Point any coding agent at one local endpoint backed by the xingchi API.

The installer runs a LiteLLM bridge on `127.0.0.1:4010`, translates it into the
native config format of every agent you pick, and puts a `xingchi-<agent>`
launcher on your PATH. The bridge starts automatically when a launcher runs.

## How it works

```
xingchi-claude ─┐
xingchi-codex  ─┼─ HTTP 127.0.0.1:4010 ─ LiteLLM ─ HTTPS ─ api.xingchiapi.com/v1
xingchi-pi     ─┘   (local bridge key)                (your xingchi key)
```

The agents do not agree on a wire protocol. Claude Code and Hermes speak the
Anthropic Messages API, Codex speaks the OpenAI Responses API, and the others
speak OpenAI Chat Completions. The bridge accepts all three on the loopback
port and forwards each request to xingchiapi in the one OpenAI-compatible shape
it serves. It also pins the headers the upstream expects (`x-openai-actor-authorization: local-image-extension`, `user-agent: opencode/0.9.0`)
and drops parameters it rejects (`reasoning_effort` on `gpt-6-astra`). Everything else stays stock: the
installer writes each agent's own config file, and `xingchi-<agent>` only starts
the bridge when it is down, then execs the real binary.

## The Two Keys: Bridge Key vs Xingchi API Key

The bridge enforces a strict two-key security boundary. Your real, paid API key
never touches your agent configurations:

```
Agent (Claude, Pi, Codex...) ──[ BRIDGE KEY ]──> Local LiteLLM (127.0.0.1:4010) ──[ XINGCHI API KEY ]──> api.xingchiapi.com
```

### 1. Xingchi API Key (The Real Upstream Key)

- **What it is**: Your actual paid account key created at [xingchiapi.com/keys](https://xingchiapi.com/keys). This key has monetary value and spends upstream API credits.
- **Where it lives**: `~/.xingchi/upstream.key` (mode 600, readable only by your user).
- **Who uses it**: Only the local LiteLLM bridge process (`start.sh`). It loads the key into memory as `XINGCHI_API_KEY` to authenticate outbound HTTPS requests to `api.xingchiapi.com`.
- **Where it must NEVER be**: Never in any agent config files, git repositories, or shell history.

### 2. Bridge Key (The Local Gateway Key)

- **What it is**: A random string generated locally on your machine at install time (`sk-xingchi-...`). It has zero value outside of `127.0.0.1`.
- **Where it lives**:
  - `~/.xingchi/bridge.key` (mode 600) — reference copy.
  - `~/.xingchi/litellm.yaml` — configured under `general_settings.master_key`.
  - `~/.xingchi/env.sh` — exported as `XINGCHI_BRIDGE_KEY`.
  - Inside each agent's configuration file (e.g. `~/.xingchi/claude-settings.json`, `~/.config/opencode/opencode.json`, `~/.pi/agent/models.json`).
- **Who uses it**: Your coding agents send this key in their HTTP headers to authenticate with the local bridge on `127.0.0.1:4010`.

### Key Comparison

| Feature | Xingchi API Key (Upstream) | Bridge Key (Local) |
| :--- | :--- | :--- |
| **Origin** | Generated at `xingchiapi.com/keys` | Generated locally on your machine |
| **Purpose** | Spends upstream API credits | Unlocks local loopback port (`4010`) |
| **Storage** | `~/.xingchi/upstream.key` (mode 600) only | `~/.xingchi/bridge.key` + agent configs |
| **Scope** | Remote (Internet / Xingchi API) | Local only (`127.0.0.1:4010`) |
| **Leak Risk** | High (could drain account balance) | Zero (completely useless outside your localhost) |

### Why Two Keys?

1. **Zero Secret Leakage**: If an agent dumps its configuration into logs, an error report, or a public repository, only the local `bridge.key` is revealed. Your paid Xingchi API key is completely safe.
2. **Instant Rotation**: If you rotate your Xingchi key, you update exactly **one file** (`~/.xingchi/upstream.key`) and restart the bridge. You never have to reconfigure or touch 9 different agent configuration files.

## Alignment with Official Xingchi Guides

Xingchi provides 3 official patterns for developer tooling:
- **Option 1 (Codex CLI via Responses API)**: Direct connection in `~/.codex/config.toml` with `x-openai-actor-authorization: local-image-extension`.
- **Option 2 (Codex CLI via WebSockets)**: High-performance streaming mode for Codex.
- **Option 3 (xingchi-agents Multi-Agent Standard)**: OpenCode / OpenAI-compatible endpoint standard with `store: false`. `xingchi-agents` implements this official Option 3 pattern, extending it to seamlessly power all 9 major coding agents simultaneously.

## Why LiteLLM, and not OpenRouter, 9Router, or direct config

The whole job is: take three client protocols, one upstream, one API key, and
make them line up. LiteLLM is the smallest tool that does exactly that without
adding an account, a dashboard, or a second network hop.

| | LiteLLM (this repo) | OpenRouter | 9Router | direct config per agent |
| --- | --- | --- | --- | --- |
| Where it runs | local process, `127.0.0.1:4010` | hosted third-party service | local Node/Next.js app | inside each agent |
| Account besides xingchi | none | OpenRouter account + purchased credits | none | none |
| Can spend your own xingchi key | yes | no — it routes only to providers in its marketplace | yes | yes |
| Extra cost | none | fee on credit purchases; some routes carry a provider markup | none | none |
| Request path | agent → loopback → xingchiapi | agent → OpenRouter → provider | agent → loopback → provider | agent → xingchiapi |
| Protocols served in one process | OpenAI Chat, OpenAI Responses, Anthropic Messages | vendor API (OpenAI-compatible) | OpenAI ↔ Anthropic ↔ Gemini translation | only the one protocol each agent speaks |
| State you maintain | one YAML, one venv | nothing local, vendor console | app + SQLite + web dashboard | duplicated config per agent |
| Multi-provider fallback, quota dashboards, prompt compression | no (single upstream) | yes (marketplace) | yes | no |
| Real key exposure | one 600 file, one process | your OpenRouter key sits in each agent | every provider key in the router database | the real key in every agent config |

## Install

macOS and Linux (any distro)

```sh
curl -fsSL https://raw.githubusercontent.com/kikiprojecto/xingchi-agents/main/install.sh | sh
```

Windows (PowerShell 5.1+)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/kikiprojecto/xingchi-agents/main/install.ps1 | iex"
```

The adaptive installer guides you cleanly through 5 clear steps:

1. **Choose Agents**: Pick which coding agents to configure (`claude`, `codex`, `pi`, `gemini`, etc., or `all`). Missing agents are installed automatically.
2. **Upstream Xingchi API Key**: Enter your real key from [xingchiapi.com/keys](https://xingchiapi.com/keys). Stored securely in `~/.xingchi/upstream.key` (mode 600).
3. **Bridge Key Generation**: A local random secret (`sk-xingchi-...`) is created in `~/.xingchi/bridge.key` to protect your real key.
4. **Agent Configuration**: Writes each selected agent's native config file, injecting the local bridge key.
5. **Conflict Resolution & Verification**: Resolves zombie processes on port 4010, starts the local bridge on `127.0.0.1:4010`, and executes a live health check.

Non-interactive:

```sh
XINGCHI_API_KEY=... sh install.sh --agents claude,codex --yes
```

## Requirements

- curl and tar (macOS/Linux); curl.exe (Windows 10 1803+)
- Python 3.8+ with venv (installed automatically with apt/dnf/pacman/zypper/apk/brew or winget when missing)
- Node.js for the npm-based agents (installed automatically via brew/apt/dnf/pacman/zypper/apk or winget when missing)

## Agent installation

A selected agent that is already on PATH is left alone. A selected agent that is
missing is installed with its vendor's official command:

| Agent | macOS / Linux | Windows |
| --- | --- | --- |
| Claude Code | `npm install -g @anthropic-ai/claude-code` | same |
| opencode | `npm install -g opencode-ai` | same |
| Codex | `npm install -g @openai/codex` | same |
| Pi | `npm install -g @earendil-works/pi-coding-agent` | same |
| Kilo | `npm install -g @kilocode/cli` | same |
| Gemini CLI | `npm install -g @google/gemini-cli` | same |
| OpenClaw | `npm install -g openclaw` | same |
| Hermes | `curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash` | `iex (irm 'https://hermes-agent.nousresearch.com/install.ps1')` |
| Antigravity (`agy`) | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` | `iex (irm 'https://antigravity.google/cli/install.ps1')` |

## Agents

| Agent | Writes | Status |
| --- | --- | --- |
| Claude Code | `~/.xingchi/claude-settings.json` | tested |
| Hermes | `~/.hermes/config.yaml` (+ `.env`) | tested; run `hermes` once first so it creates `~/.hermes/config.yaml`, then re-run the installer |
| opencode | `~/.config/opencode/opencode.json` | tested |
| Kilo | `~/.config/kilo/kilo.jsonc` | tested |
| Pi | `~/.pi/agent/models.json` | tested |
| Gemini CLI | `~/.gemini/settings.json` | tested |
| Codex | `~/.codex/config.toml` | tested |
| OpenClaw | `~/.openclaw/openclaw.json` | tested |
| Antigravity (`agy`) | `~/.gemini/antigravity-cli/settings.json` | tested |

Models: `gpt-6.1-sol` (default), `gpt-6-astra`, `gpt-6`, `gpt-5.6`, `gpt-5.2`.

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
| `bridge-up.sh` | health check + lazy start, sourced or executed directly |
| `env.sh` | `XINGCHI_BRIDGE_URL`, `XINGCHI_BRIDGE_KEY` |
| `upstream.key` | your xingchi API key (600) |
| `bridge.key` | generated local bridge key (600) |
| `claude-settings.json` | Claude Code settings passed by the launcher |
| `venv/` | LiteLLM installed with pip |

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
  that model or balance is depleted.
- `command not found: xingchi-claude`: open a new terminal, or add
  `~/.local/bin` (Windows: `%LOCALAPPDATA%\xingchi\bin`) to PATH yourself.
- Restore an agent config: `mv <file>.xingchi.bak <file>`.

## Security

- The bridge binds to `127.0.0.1` only and requires the generated local key.
- Secrets live in `~/.xingchi` (mode 600/700), never in this repository.
- Agent configs contain the local bridge key, not your xingchi key.
- The installer never edits shell startup file content beyond adding one PATH
  line, and never touches `~/.claude/settings.json`.
- Missing agents are installed only with npm and the vendors' HTTPS installers
  listed in [Agent installation](#agent-installation).

## Uninstall

```sh
rm -f ~/.local/bin/xingchi ~/.local/bin/xingchi-*
rm -rf ~/.xingchi
```

Windows:

```powershell
Remove-Item "$env:LOCALAPPDATA\xingchi" -Recurse -Force
```
