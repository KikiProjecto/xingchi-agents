# xingchi-codex

Point the **Codex CLI** at the Xingchi API and start coding. One key, one
model, no local proxy.

```
codex ── HTTPS (OpenAI Responses API) ──> api.xingchiapi.com/v1
```

The processor's upstream does not accept LiteLLM, SDKs, or plain scripts — it
serves the OpenAI **Responses** API only to known coding clients. Codex speaks
that protocol natively, so it talks to the upstream **directly**. There is no
bridge process, no `127.0.0.1:4010` port, and no second "bridge key".

## The one real model

```
GET https://api.xingchiapi.com/v1/models  ->  gpt-6.1-sol
```

`gpt-6.1-sol` is the only model the upstream account serves. Any other name
(`gpt-6-astra`, `gpt-5`, `gpt-4o`, …) is rejected server-side with
`model_not_found`:

```json
{"error":{"message":"Model \"gpt-6-astra\" is not supported by any configured account in this group",
          "type":"model_not_found"}}
```

So a one-model list is correct, not a bug. Adding another name to the config
cannot make the server serve it; see [Checking for other models](#checking-for-other-models-eg-gpt-6-astra)
for how to tell whether your account's group has one.

## Install

macOS and Linux

```sh
curl -fsSL https://raw.githubusercontent.com/kikiprojecto/xingchi-codex/main/install.sh | sh
```

Windows (PowerShell 5.1+)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/kikiprojecto/xingchi-codex/main/install.ps1 | iex"
```

The installer:

1. Asks for your Xingchi API key and stores it in `~/.xingchi/upstream.key`
   (mode 600). It never writes the key into this repository.
2. Installs the Codex CLI (`npm install -g @openai/codex`) if it is missing.
3. Writes `~/.codex/config.toml` and installs the `xingchi-codex` / `xingchi`
   launchers.
4. Checks your key with a real request to `https://api.xingchiapi.com/v1/models`.

Non-interactive:

```sh
XINGCHI_API_KEY=... sh install.sh --yes
```

## What it writes

`~/.codex/config.toml` (existing settings are merged, the old file is copied to
`config.toml.xingchi.bak`):

```toml
model_provider = "OpenAI"
model = "gpt-6.1-sol"
model_reasoning_effort = "max"

[model_providers.OpenAI]
name = "OpenAI"
base_url = "https://api.xingchiapi.com/v1"
model_catalog_url = "https://api.xingchiapi.com/v1/models"
wire_api = "responses"
requires_openai_auth = false
experimental_bearer_token = "<your key>"
http_headers = { "x-openai-actor-authorization" = "local-image-extension" }

[features]
api_key_model_discovery = true
```

`~/.xingchi/upstream.key` — your Xingchi API key, mode 600.
`~/.local/bin/xingchi-codex` — reads that key at runtime, exports
`OPENAI_BASE_URL` / `OPENAI_API_KEY`, and execs `codex`.
`~/.local/bin/xingchi` — prints the current setup.

## Use

```sh
xingchi-codex                 # interactive Codex TUI
xingchi-codex exec "..."      # non-interactive
xingchi                       # show API, model, key and codex status
xingchi --doctor              # run codex doctor; reports model/provider status
codex doctor                  # full health check
```

`xingchi-codex` passes every argument straight through to `codex`.

## Requirements

- curl and tar (macOS/Linux); PowerShell 5.1+ (Windows)
- Python 3 (used only to merge `~/.codex/config.toml`)
- Node.js with npm (to install the Codex CLI)

## Security

- Your Xingchi key lives only in `~/.xingchi/upstream.key` (mode 600). It is
  never committed to this repository and never passed on a command line.
- The launcher reads the key file at runtime; the repository contains no
  credentials.
- Codex connects to the upstream directly over HTTPS.

## Checking for other models (e.g. `gpt-6-astra`)

A model name that is not in `GET /v1/models` is still worth probing: the
upstream reports `model_not_found` **per account group**, so a model may exist
for a different key even though this one cannot use it.

```sh
sh scripts/probe-astra.sh
# or with a different key:
XINGCHI_KEY_FILE=/path/to/other.key sh scripts/probe-astra.sh
```

The script tries several model ids, endpoints and client user-agents, prints
only status codes and short bodies, and redacts the key. Interpretation:

- **HTTP 200** — the model works with that id and those headers. Send the
  output and the id can be added as a Codex profile.
- `model_not_found … in this group` — this key's group does not include the
  model. Use a key from the group that does, or ask Xingchi to enable it.
- `client_not_allowed` — that endpoint/client combination is blocked.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `No connected db` | Something points Codex at an old LiteLLM proxy. Remove any `127.0.0.1:4010` base URL and restart Codex. |
| `No models are available` | `model = "gpt-6.1-sol"` is missing from `~/.codex/config.toml`. Re-run the installer. |
| `client_not_allowed` | The upstream rejects scripts/SDKs/proxies. Use the Codex CLI directly, not curl or a proxy. |
| `model_not_found` | You requested a model the account does not serve. Only `gpt-6.1-sol` exists. |
| `401` on install | The key is wrong or expired. Create a new one at <https://xingchiapi.com/keys>. |
| Restart needed | If Codex was already running, fully quit it so it reloads `~/.codex/config.toml`. |

Restore the previous Codex config with:

```sh
mv ~/.codex/config.toml.xingchi.bak ~/.codex/config.toml
```

`xingchi` never touches your shell startup files beyond adding one PATH line.

## Uninstall

```sh
rm -f ~/.local/bin/xingchi ~/.local/bin/xingchi-codex
rm -rf ~/.xingchi
```

Windows:

```powershell
Remove-Item "$env:LOCALAPPDATA\xingchi" -Recurse -Force
```
