#!/usr/bin/env python3
"""Point the Codex CLI at the Xingchi upstream.

The Xingchi upstream only serves the OpenAI *Responses* API, and only to known
coding clients. Codex speaks that protocol natively, so it talks to the
upstream directly - there is no local proxy and no second key.

Called by install.sh and install.ps1 with XINGCHI_API_KEY set. It writes
``config.toml`` in the Codex home, merging into any existing file and copying
the previous version to ``<file>.xingchi.bak`` first.
"""

import json
import os
import re
import shutil
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HOME = os.path.expanduser("~")
UPSTREAM = os.environ.get("XINGCHI_UPSTREAM", "https://api.xingchiapi.com/v1").rstrip("/")
KEY = os.environ.get("XINGCHI_API_KEY", "").strip()
MODEL = "gpt-6.1-sol"
MODELS = (MODEL, "gpt-6-astra", "gpt-6-luna", "gpt-6-terra")
MIN_CODEX_VERSION = (0, 170, 0)
FEATURE_DEFAULTS = {
    "api_key_model_discovery": "true",
    "image_generation": "true",
    "goals": "true",
}
# The model list endpoint may report a versioned Terra ID. Keep it selectable
# under its exact name as well, so Codex sends the ID the account advertises.
KNOWN_MODELS = {
    "gpt-6.1-terra": ("GPT-6.1 Terra", 500000),
    "gpt-6.2-astra": ("GPT-6.2 Astra", 272000),
}
MODEL_ID = re.compile(r"gpt-[0-9][a-zA-Z0-9._:-]*\Z")


def fail(message):
    sys.exit("error: " + message)


def compatible_cli(version):
    match = re.search(r"\bcodex-cli\s+(\d+)\.(\d+)\.(\d+)\b", version)
    return bool(match and tuple(map(int, match.groups())) >= MIN_CODEX_VERSION)


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


def assign(section, values, label):
    """Set or remove ``name = value`` pairs in one section."""
    for name, value in values.items():
        pattern = r"(?m)^[ \t]*" + re.escape(name) + r"[ \t]*=[^\n]*(?:\n|$)"
        for found in re.findall(pattern, section):
            previous = found.split("=", 1)[1].strip()
            if (previous.startswith(('"""', "'''", "["))
                    or (previous.startswith("{") and "}" not in previous)):
                fail(f"Codex {name} in {label} must use a single-line value; "
                     "config unchanged")
        section = re.sub(pattern, "", section)
        if value is not None:
            section = section.rstrip("\n") + f"\n{name} = {value}\n"
    return section


def discover_models():
    request = Request(UPSTREAM + "/models", headers={"User-Agent": "codex_cli_rs/0.170.0"})
    # urllib must not forward our API key if the endpoint redirects.
    request.add_unredirected_header("Authorization", "Bearer " + KEY)
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            fail(f"upstream returned {exc.code}; check your Xingchi key and model access")
        print(f"  [WARN] model discovery returned HTTP {exc.code}; using the default model list")
        return []
    except (OSError, ValueError):
        print("  [WARN] could not read upstream /models; the key was not verified")
        return []

    items = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    return [model for model in ids if isinstance(model, str) and MODEL_ID.fullmatch(model)]


def build_catalog(discovered):
    xingchi_dir = os.environ.get("XINGCHI_HOME") or os.path.join(HOME, ".xingchi")
    local_file = os.path.join(xingchi_dir, "models.txt")
    with open(os.path.join(os.path.dirname(__file__), "models.json"), encoding="utf-8") as f:
        shipped = json.load(f)["models"]
    templates = {entry["slug"]: entry for entry in shipped}
    template = templates[MODEL]

    ids = dict.fromkeys((*templates, *discovered))
    # Windows PowerShell can add a BOM when writing a UTF-8 text file.
    if os.path.isfile(local_file):
        with open(local_file, encoding="utf-8-sig") as f:
            for line in f:
                model = line.partition("#")[0].strip()
                if MODEL_ID.fullmatch(model):
                    ids.setdefault(model)
    models = []
    for priority, model in enumerate(ids, start=1):
        entry = dict(templates.get(model, template), slug=model, priority=priority)
        if model in KNOWN_MODELS:
            entry["display_name"], entry["context_window"] = KNOWN_MODELS[model]
        elif model not in templates:
            # An ID alone doesn't tell us which reasoning efforts the model accepts.
            entry = {
                "slug": model,
                "display_name": model,
                "priority": priority,
                "base_instructions": template["base_instructions"],
                "shell_type": "unified_exec",
                "visibility": "list",
                "supported_in_api": True,
                "truncation_policy": template["truncation_policy"],
                "supported_reasoning_levels": [],
                "support_verbosity": False,
                "experimental_supported_tools": [],
            }
        # Xingchi's Responses endpoint rejects the ``additional_tools`` item
        # that Codex emits when a model advertises multi-agent v2 tool
        # namespaces, answering HTTP 400 "Upstream request failed".
        entry.pop("multi_agent_version", None)
        entry.pop("multi_agent_reasoning_effort", None)
        entry["description"] = f"{entry['display_name']} on Xingchi"
        models.append(entry)
    return {"models": models}


def configure_codex(discovered=()):
    codex_dir = os.path.abspath(os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex"))
    path = os.path.join(codex_dir, "config.toml")
    catalog_path = os.path.join(codex_dir, "xingchi-models.json")
    text = read_text(path)
    if re.search(r"(?m)^[ \t]*\[model_providers\.OpenAI\.http_headers\]", text):
        fail("Codex http_headers must be an inline table; config unchanged")

    catalog = build_catalog(discovered)
    root = {
        "model_provider": '"OpenAI"',
        "model_catalog_json": json.dumps(catalog_path, ensure_ascii=False),
    }
    provider = {
        "name": '"OpenAI"',
        "base_url": json.dumps(UPSTREAM),
        "model_catalog_url": None,
        "wire_api": '"responses"',
        "requires_openai_auth": "false",
        "experimental_bearer_token": json.dumps(KEY),
        "http_headers": '{ "x-openai-actor-authorization" = "local-image-extension" }',
    }
    blocks = re.split(r"(?m)(?=^[ \t]*\[)", text)
    saved = re.search(r'''(?m)^[ \t]*model[ \t]*=[ \t]*(["'])([^"'\n]+)\1[ \t]*(?:#.*)?$''', blocks[0])
    if not saved or saved[2] not in {entry["slug"] for entry in catalog["models"]}:
        root["model"] = json.dumps(MODEL)
    headers = [""]
    for block in blocks[1:]:
        match = re.match(r"[ \t]*(\[[^\]\n]*\])", block)
        headers.append(match.group(1) if match else None)

    # Match the local setup on a fresh install, while retaining explicit user
    # choices (including false) when reinstalling.
    features = dict(FEATURE_DEFAULTS)
    if "[features]" in headers:
        body = blocks[headers.index("[features]")]
        features = {name: value for name, value in features.items()
                    if not re.search(r"(?m)^[ \t]*" + re.escape(name) + r"[ \t]*=", body)}
    targets = {"": root, "[model_providers.OpenAI]": provider, "[features]": features}

    for header, values in targets.items():
        if header in headers:
            index = headers.index(header)
            if index == 0:
                blocks[0] = assign(blocks[0], values, "root")
            else:
                head, _, body = blocks[index].partition("\n")
                blocks[index] = head + "\n" + assign(body, values, header).lstrip("\n")
        elif header:
            blocks.append(header + "\n" + assign("", values, header).lstrip("\n"))
            headers.append(header)

    # The upstream model list contains IDs. Codex needs the reasoning presets
    # and other model metadata from a native catalog to build the /model menu.
    write_text(catalog_path, json.dumps(catalog, indent=2) + "\n")
    write_text(path, "".join(blocks).lstrip("\n"))
    return path


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "check-cli":
        sys.exit(0 if compatible_cli(sys.argv[2]) else 1)
    if len(sys.argv) != 2 or sys.argv[1] != "codex":
        fail("usage: config.py codex | config.py check-cli VERSION")
    if not KEY:
        fail("XINGCHI_API_KEY is not set")
    discovered = discover_models()
    if discovered:
        print("  [OK] upstream lists: " + ", ".join(dict.fromkeys(discovered)))
    print(f"  configured {configure_codex(discovered)}")
    print("  /model: " + ", ".join(MODELS))
    print("  reasoning: choose per model; saved model and effort are preserved")
    if discovered:
        missing = [model for model in MODELS if model not in discovered]
        if missing:
            print("  [NOTE] not listed for this key: " + ", ".join(missing))
            print("  Catalog entries do not grant model access; Xingchi may reject them.")


if __name__ == "__main__":
    main()
