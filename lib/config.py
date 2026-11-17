#!/usr/bin/env python3
"""Apply xingchi bridge settings to one agent's config file.

Called by install.sh and install.ps1 with XINGCHI_BRIDGE_KEY set, plus
XINGCHI_URL (default http://127.0.0.1:4010) and XINGCHI_HOME (default
~/.xingchi). Every subcommand is idempotent and backs up any file it
rewrites to <file>.xingchi.bak.
"""

import json
import os
import re
import shutil
import sys

HOME = os.path.expanduser("~")
URL = os.environ.get("XINGCHI_URL", "http://127.0.0.1:4010").rstrip("/")
KEY = os.environ.get("XINGCHI_BRIDGE_KEY", "")
XDIR = os.environ.get("XINGCHI_HOME", os.path.join(HOME, ".xingchi"))
MODELS = ("gpt-6.1-sol", "gpt-6-astra")
PRIMARY = MODELS[0]


def fail(message):
    sys.exit("error: " + message)


def read_text(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def backup(path):
    if os.path.exists(path):
        bak = path + ".xingchi.bak"
        shutil.copyfile(path, bak)
        os.chmod(bak, 0o600)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    backup(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def write_json(path, data):
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path, default):
    text = read_text(path)
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON ({exc}); fix it and re-run")


def strip_jsonc(text):
    """Drop // and /* */ comments plus trailing commas, keeping strings intact."""
    out = []
    i, n = 0, len(text)
    in_str = False
    esc = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(c)
            i += 1
    cleaned = "".join(out)
    out = []
    i, n = 0, len(cleaned)
    in_str = False
    esc = False
    while i < n:
        c = cleaned[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == ",":
            j = i + 1
            while j < n and cleaned[j] in " \t\r\n":
                j += 1
            if j < n and cleaned[j] in "}]":
                i += 1
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def read_jsonc(path, default):
    text = read_text(path)
    if not text.strip():
        return default
    try:
        return json.loads(strip_jsonc(text))
    except json.JSONDecodeError as exc:
        fail(f"{path} is JSON5/JSONC that this installer cannot parse ({exc}); "
             "fix it and re-run")


def configure_claude():
    path = os.path.join(XDIR, "claude-settings.json")
    settings = {
        "env": {
            "ANTHROPIC_BASE_URL": URL,
            "ANTHROPIC_AUTH_TOKEN": KEY,
            "ANTHROPIC_MODEL": PRIMARY,
            "ANTHROPIC_SMALL_FAST_MODEL": PRIMARY,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": PRIMARY,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": PRIMARY,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": PRIMARY,
            "CLAUDE_CODE_SUBAGENT_MODEL": PRIMARY,
            "MAX_THINKING_TOKENS": "0",
            "ENABLE_TOOL_SEARCH": "auto",
            "MCP_CONNECTION_NONBLOCKING": "1",
            "CLAUDE_CODE_AUTO_MODE_SERVER": "0",
        },
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
                "Bash(git show:*)", "Bash(git branch:*)", "Bash(ls:*)",
                "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
                "Bash(pwd)", "Bash(rg:*)", "Bash(grep:*)", "Bash(find:*)",
                "Bash(tree:*)", "Bash(which:*)", "Bash(command -v:*)",
                "Bash(jq:*)", "Bash(diff:*)", "Bash(basename:*)",
                "Bash(dirname:*)", "Bash(realpath:*)", "Bash(du:*)",
                "Bash(df:*)", "Bash(stat:*)", "Bash(date)", "Bash(uname:*)",
                "Bash(curl -fsS -o /dev/null:*)",
            ],
        },
    }
    write_json(path, settings)
    return path


def configure_hermes():
    path = os.path.join(HOME, ".hermes", "config.yaml")
    if not os.path.exists(path):
        fail("~/.hermes/config.yaml not found; install Hermes Agent first")
    text = read_text(path)
    if not re.search(r"(?m)^\s+xingchi:\s*$", text):
        entry = (
            "  xingchi:\n"
            f'    base_url: "{URL}/v1"\n'
            '    key_env: "XINGCHI_BRIDGE_KEY"\n'
            "    models:\n" + "".join(f"      - {m}\n" for m in MODELS)
        )
        match = re.search(r"(?m)^providers:\s*$", text)
        if match:
            text = text[: match.end()] + "\n" + entry + text[match.end():]
        else:
            text = text.rstrip("\n") + "\n\nproviders:\n" + entry
        write_text(path, text)
    env_path = os.path.join(HOME, ".hermes", ".env")
    env_text = read_text(env_path)
    if not re.search(r"(?m)^XINGCHI_BRIDGE_KEY=", env_text):
        if env_text and not env_text.endswith("\n"):
            env_text += "\n"
        write_text(env_path, env_text + f"XINGCHI_BRIDGE_KEY={KEY}\n")
    return path


def configure_opencode():
    path = os.path.join(HOME, ".config", "opencode", "opencode.json")
    cfg = read_json(path, {})
    cfg.setdefault("provider", {})["openai"] = {
        "options": {"baseURL": f"{URL}/v1", "apiKey": KEY},
        "models": {
            m: {
                "name": m,
                "options": {"store": False}
            } for m in MODELS
        },
    }
    write_json(path, cfg)
    return path


def configure_codex():
    path = os.path.join(HOME, ".codex", "config.toml")
    text = read_text(path)
    if "[model_providers.OpenAI]" not in text:
        block = (
            'model_provider = "OpenAI"\n'
            f'model = "{PRIMARY}"\n'
            f'review_model = "{PRIMARY}"\n'
            'web_search = "live"\n'
            'disable_response_storage = true\n'
            'network_access = "enabled"\n\n'
            "[model_providers.OpenAI]\n"
            'name = "OpenAI"\n'
            f'base_url = "{URL}/v1"\n'
            f'model_catalog_url = "{URL}/v1/models"\n'
            'wire_api = "responses"\n'
            'requires_openai_auth = false\n'
            'experimental_bearer_token = "env:XINGCHI_BRIDGE_KEY"\n'
            'http_headers = { "x-openai-actor-authorization" = "local-image-extension" }\n'
        )
        text = block + ("\n" + text if text.strip() else "")
    write_text(path, text)
    return path


def configure_pi():
    path = os.path.join(HOME, ".pi", "agent", "models.json")
    cfg = read_json(path, {})
    cfg.setdefault("$schema", "https://pi.dev/schemas/models.schema.json")
    cfg.setdefault("providers", {})["xingchi"] = {
        "name": "xingchi",
        "baseUrl": f"{URL}/v1",
        "api": "openai-completions",
        "apiKey": "$XINGCHI_BRIDGE_KEY",
        "models": [{"id": m} for m in MODELS],
    }
    write_json(path, cfg)
    return path


def configure_kilo():
    path = os.path.join(HOME, ".config", "kilo", "kilo.jsonc")
    cfg = read_jsonc(path, {})
    cfg.setdefault("provider", {})["xingchi"] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "xingchi",
        "options": {"baseURL": f"{URL}/v1", "apiKey": KEY},
        "models": {m: {"name": m} for m in MODELS},
    }
    cfg["model"] = "xingchi/" + PRIMARY
    write_json(path, cfg)
    return path


def configure_agy():
    path = os.path.join(HOME, ".gemini", "antigravity-cli", "settings.json")
    cfg = read_json(path, {})
    block = dict(cfg.get("customModelsConfig") or {})
    kept = [
        m for m in block.get("custom_models", [])
        if not (isinstance(m, dict) and m.get("provider_id") == "xingchi")
    ]
    kept += [
        {"model_name": m, "base_url": f"{URL}/v1", "api_key": KEY,
         "provider_id": "xingchi"}
        for m in MODELS
    ]
    block["custom_models"] = kept
    cfg["customModelsConfig"] = block
    cfg["model"] = PRIMARY
    write_json(path, cfg)
    return path


def configure_gemini():
    path = os.path.join(HOME, ".gemini", "settings.json")
    cfg = read_json(path, {})
    cfg.setdefault("security", {}).setdefault("auth", {})[
        "selectedType"
    ] = "gemini-api-key"
    write_json(path, cfg)
    return path


def configure_openclaw():
    path = os.path.join(HOME, ".openclaw", "openclaw.json")
    cfg = read_jsonc(path, {})
    cfg.setdefault("models", {}).setdefault("providers", {})["xingchi"] = {
        "baseUrl": f"{URL}/v1",
        "apiKey": "${XINGCHI_BRIDGE_KEY}",
        "api": "openai-completions",
        "models": [{"id": m, "name": m} for m in MODELS],
    }
    cfg.setdefault("agents", {}).setdefault("defaults", {}).setdefault(
        "model", {}
    )["primary"] = "xingchi/" + PRIMARY
    write_json(path, cfg)
    return path


AGENTS = {
    "claude": configure_claude,
    "hermes": configure_hermes,
    "opencode": configure_opencode,
    "codex": configure_codex,
    "pi": configure_pi,
    "kilo": configure_kilo,
    "agy": configure_agy,
    "gemini": configure_gemini,
    "openclaw": configure_openclaw,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in AGENTS:
        fail("usage: config.py <" + "|".join(AGENTS) + ">")
    if not KEY:
        fail("XINGCHI_BRIDGE_KEY is not set")
    path = AGENTS[sys.argv[1]]()
    print(f"  configured {path}")


if __name__ == "__main__":
    main()
