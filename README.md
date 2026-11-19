# xingchi-codex

Point the **Codex CLI** at the Xingchi API and pick your model and reasoning
level with `/model`. Setup uses one key and connects directly to Xingchi.

```
codex ── HTTPS (OpenAI Responses API) ──> api.xingchiapi.com/v1
```

Both installers configure Codex to use Xingchi's **Responses API** directly,
with the coding-client headers used by the local setup. There is no bridge
process, local proxy port, or second key.

## Models and reasoning

| Model ID | Selectable reasoning levels |
| --- | --- |
| `gpt-6.1-sol` | Low, Medium, High, Extra High, Max, Ultra |
| `gpt-6-astra` | Low, Medium, High, Extra High, Max, Ultra |
| `gpt-6-luna` | Low, Medium, High, Extra High, Max |
| `gpt-6-terra` | Low, Medium, High, Extra High, Max, Ultra |

Ultra is a Codex preset. In the reference CLI, 0.170.0, selecting Ultra sends
`reasoning.effort = "max"` to the API.

Both installers use the same bundled catalog in `lib/models.json`, matching
the local four-model setup. These four entries stay in `/model` even if
Xingchi's `/v1/models` lists only Sol. Other GPT IDs returned for your key,
such as `gpt-6.1-terra`, are added alongside them.

The menu and its reasoning choices are local configuration. **They do not
grant account access.** If Xingchi returns `model_not_found` for Astra, Luna,
or Terra, that exact model must be enabled for your key's account group.

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
2. Installs or updates the Codex CLI (`npm install -g @openai/codex`) when it
   is missing or older than the supported minimum, 0.170.0.
3. Checks your key and reads the list of models from `/v1/models`, then writes
   the four-model catalog, reasoning presets, feature defaults and launchers.

If the upstream rejects the key (`401`/`403`) the installer exits non-zero and
tells you to get a new key, so a failed check never looks like a finished
install. Paste the key with or without surrounding spaces; it is trimmed.

Non-interactive:

```sh
XINGCHI_API_KEY=... sh install.sh --yes
```

To install from this checkout using your saved key:

```sh
sh install.sh --yes
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Yes
```

## What it writes

`~/.codex/config.toml` (existing settings are merged, the old file is copied to
`config.toml.xingchi.bak`):

```toml
model_provider = "OpenAI"
model = "gpt-6.1-sol"
model_catalog_json = "/absolute/path/to/.codex/xingchi-models.json"

[model_providers.OpenAI]
name = "OpenAI"
base_url = "https://api.xingchiapi.com/v1"
wire_api = "responses"
requires_openai_auth = false
experimental_bearer_token = "<your key>"
http_headers = { "x-openai-actor-authorization" = "local-image-extension" }

[features]
api_key_model_discovery = true
image_generation = true
goals = true
```

The installer builds the model catalog beside `config.toml` and uses
`CODEX_HOME` when set. Codex reads the model and reasoning choices from that
catalog. The feature values above are defaults for a fresh install; explicitly
saved feature choices are retained on reinstall. The installer also preserves
your saved model (if still in the catalog) and reasoning level. It does not
force one reasoning level for every model.

On Windows, the default Codex directory is `%USERPROFILE%\.codex`, and the
launchers are installed under `%LOCALAPPDATA%\xingchi\bin`.

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

`xingchi-codex` passes your arguments to `codex` and adds `--no-daemon` so
each launch reads the installed catalog. Codex's shared background server can
keep an older model list even after you quit and reopen the terminal UI.

Rerun the updated installer and restart `xingchi-codex`. Open `/model`,
select a model, and choose a reasoning level. Max and Ultra appear under
**More reasoning** where available. Reinstalling keeps your saved reasoning
level and any saved model that is still in the catalog.
The installers check for Codex CLI 0.170.0 or newer and update older versions.

## Requirements

- curl and tar (macOS/Linux); PowerShell 5.1+ (Windows)
- Python 3 (checks model availability and writes the Codex configuration)
- Node.js with npm (to install the Codex CLI)

## Security

- Your Xingchi key is stored in `~/.xingchi/upstream.key` and the Codex
  provider configuration. These files and their backups use mode 600 on
  macOS/Linux. The key is never committed to this repository or passed on a
  command line.
- The launcher reads the key file at runtime; the repository contains no
  credentials.
- Codex connects to the upstream directly over HTTPS.

## Adding other GPT model IDs

If your account can use a GPT model that Xingchi's `/v1/models` omits, add its
exact ID to `~/.xingchi/models.txt` (`%USERPROFILE%\.xingchi\models.txt` on
Windows, or under `XINGCHI_HOME` if set). Use one model ID per line, save as
UTF-8, then rerun the installer and restart Codex. An ID with no known
reasoning metadata appears without a reasoning submenu.

You can also try a specific model and reasoning setting from the terminal.

```powershell
xingchi-codex -m gpt-6-astra -c 'model_reasoning_effort="high"'
```

Changing the reasoning level in `/model` saves it for the next launch. A
command-line `-c` override applies to that invocation.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `No connected db` | Something points Codex at an old LiteLLM proxy. Remove any `127.0.0.1:4010` base URL and restart Codex. |
| `No models are available` | Rerun the installer to rebuild the catalog, then restart Codex. |
| `/model` shows only `gpt-6.1-sol` despite a four-model catalog | An existing shared background server still has the old list. Use the updated `xingchi-codex` launcher, or run `codex --no-daemon`. |
| `client_not_allowed` | The upstream rejects scripts/SDKs/proxies. Use the Codex CLI directly, not curl or a proxy. |
| `model_not_found` | Xingchi rejected that exact model ID for your account group. Check which ID Xingchi lists during install, or ask Xingchi to enable it. |
| `Upstream request failed` (`upstream_error`, HTTP 400) | Xingchi rejects the `custom_tool_call` items Codex writes for its experimental Code Mode `exec` tool. The generated catalog keeps that tool off; a session started before this fix still replays those items, so start a new `xingchi-codex` session instead of resuming the old one. |
| `401` on install | The key is wrong or expired. Create a new one at <https://xingchiapi.com/keys>. |
| Restart needed | If Codex was already running, fully quit it so it reloads `~/.codex/config.toml`. |

Restore the previous Codex config with:

```sh
mv ~/.codex/config.toml.xingchi.bak ~/.codex/config.toml
```

The installer adds the launcher directory to your shell PATH if needed.

## Development checks

With Python 3.11+:

```sh
python3 -m unittest discover -s tests
```

The tests cover fresh installs, CLI upgrades, saved selections, all advertised
reasoning values, and the real Codex model/effort menus against a local fake
upstream. Native Windows installer tests run on Windows. No paid API requests
are used by the suite.

## Uninstall

```sh
rm -f ~/.local/bin/xingchi ~/.local/bin/xingchi-codex
rm -rf ~/.xingchi
```

Windows:

```powershell
Remove-Item "$env:LOCALAPPDATA\xingchi" -Recurse -Force
```
