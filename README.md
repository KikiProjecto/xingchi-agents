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
it serves. It also pins the headers the upstream expects and drops parameters it
rejects (`reasoning_effort` on `gpt-6-astra`). Everything else stays stock: the
installer writes each agent's own config file, and `xingchi-<agent>` only starts
the bridge when it is down, then execs the real binary.

Keys never leave the machine:

- `~/.xingchi/upstream.key` (mode 600) holds your xingchi key and is read by the
  bridge process only.
- `~/.xingchi/bridge.key` is generated at install time. Every agent config gets
  this key instead — as a literal value, an env-var reference, or via the
  launcher environment, depending on what that agent supports.
- Rotating your xingchi key is one file write. No agent config changes, because
  no agent config ever contained it.

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

**Why not OpenRouter.** It is a hosted marketplace, not a router you own. You
would need an OpenRouter account and credits, pay a fee on top of xingchi, and
every request would transit a third party — while your xingchi key would still
be unusable there, because xingchi is not one of its providers. It solves a
problem this project does not have (shopping across providers) and creates ones
it must avoid (an account, a fee, an extra hop, another uptime dependency).

**Why not 9Router.** 9Router is a capable local gateway: MIT, Next.js, ~40
providers, format translation, multi-account rotation, fallback chains, a web
dashboard, and a "token saver" that compresses tool output. With exactly one
paid upstream, none of that is useful, and each piece adds surface: a Node app
plus SQLite, a dashboard listening on localhost, and code paths that can
rewrite prompts before they leave the machine. This repo deliberately avoids
prompt rewriting — the agent's request is the request.

**Why not configure each agent directly.** Each agent would need its own
translation glue: Claude Code cannot target a Chat Completions endpoint, Codex
cannot target an Anthropic endpoint, and both would need per-agent model alias
tables and the parameter dropping that the bridge does once. You would also
have to paste the real xingchi key into nine different files and re-edit all of
them on rotation. LiteLLM turns that into one YAML plus one generated key.

What this project intentionally is not: a multi-provider router, a failover
system, a quota dashboard, a prompt compressor, or a free-tier scraper. One
upstream, one local process, one key boundary.

## Install

macOS and Linux (any distro)

```sh
curl -fsSL https://raw.githubusercontent.com/kikiprojecto/xingchi-agents/main/install.sh | sh
```

Windows (PowerShell 5.1+)

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
default. Every selected agent that is not on your PATH is installed
automatically (see [Agent installation](#agent-installation)).

Next the installer asks for your xingchi API key, once. Create one at
[xingchiapi.com/keys](https://xingchiapi.com/keys) -> sign in/create your account first, click **Create key**,
then copy it and paste it at the prompt (input is hidden; press Enter):

```
Create a key at https://xingchiapi.com/keys, copy it, then
paste it here (input is hidden, press Enter):
```

That key goes only into `~/.xingchi/upstream.key` (mode 600), where the bridge
reads it. The installer then fills every selected agent's API key field itself,
using a generated local bridge key (literal value, env reference, or launcher
environment depending on the agent) — you never paste a key into an agent config.
No key is ever baked into this repo.

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

npm installs go to the global prefix; if that directory is not writable the
installer uses `sudo`. Hermes on macOS requires Apple Silicon. A failed install
prints the manual command and the installer moves on to the remaining agents.

## Agents

| Agent | Writes | Status |
| --- | --- | --- |
| Claude Code | `~/.xingchi/claude-settings.json` | tested |
| Hermes | `~/.hermes/config.yaml` (+ `.env`) | tested; run `hermes` once first so it creates `~/.hermes/config.yaml`, then re-run the installer |
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

Then remove the `xingchi` provider block from each agent config, or restore its
`.xingchi.bak` copy.
