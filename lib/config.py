#!/usr/bin/env python3
"""Point the Codex CLI at the Xingchi upstream.

The Xingchi upstream only serves the OpenAI *Responses* API, and only to known
coding clients. Codex speaks that protocol natively. The GPT公益 key and
optional Astra key are stored separately; the launcher selects one group and
connects directly.

Called by install.sh and install.ps1 with XINGCHI_API_KEY set. It writes
``config.toml`` in the Codex home, merging into any existing file and copying
the previous version to ``<file>.xingchi.bak`` first.

The API keys stay outside Codex config. The launcher selects one key per run:
Sol by default, or Astra with ``xingchi-codex --astra``.
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
ASTRA_KEY = os.environ.get("XINGCHI_ASTRA_API_KEY", "").strip()
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
}
# Xingchi can advertise GPT, Codex, and image model IDs. Keep the validation
# conservative while allowing every standard model identifier returned by the
# OpenAI-compatible /v1/models endpoint.
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


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


def discover_models_for(api_key):
    if not api_key:
        return []
    request = Request(UPSTREAM + "/models", headers={"User-Agent": "codex_cli_rs/0.170.0"})
    # urllib must not forward our API key if the endpoint redirects.
    request.add_unredirected_header("Authorization", "Bearer " + api_key)
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            fail(f"upstream returned {exc.code}; check your Xingchi key and model access")
        print(f"  [WARN] model discovery returned HTTP {exc.code}; using the configured catalog")
        return []
    except (OSError, ValueError):
        print("  [WARN] could not read upstream /models; the key was not verified")
        return []

    items = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    return [model for model in ids if isinstance(model, str) and MODEL_ID.fullmatch(model)]


def discover_models():
    """Discover model IDs independently for each configured API key."""
    return {
        "sol": discover_models_for(KEY),
        "astra": discover_models_for(ASTRA_KEY),
    }


def _catalog_from_ids(model_ids):
    with open(os.path.join(os.path.dirname(__file__), "models.json"), encoding="utf-8") as f:
        shipped = json.load(f)["models"]
    templates = {entry["slug"]: entry for entry in shipped}
    template = templates[MODEL]
    models = []
    for priority, model in enumerate(dict.fromkeys(model_ids), start=1):
        if not MODEL_ID.fullmatch(model):
            continue
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


def group_model_ids(group):
    if group not in ("sol", "astra"):
        raise ValueError("unknown Xingchi model group")
    with open(os.path.join(os.path.dirname(__file__), "model-groups.json"), encoding="utf-8") as f:
        return json.load(f)[group]


def build_catalog(discovered=(), astra_discovered=()):
    """Build a combined catalog for display and legacy callers."""
    xingchi_dir = os.environ.get("XINGCHI_HOME") or os.path.join(HOME, ".xingchi")
    local_file = os.path.join(xingchi_dir, "models.txt")
    with open(os.path.join(os.path.dirname(__file__), "models.json"), encoding="utf-8") as f:
        templates = [entry["slug"] for entry in json.load(f)["models"]]
    ids = list(dict.fromkeys((*templates, *discovered, *astra_discovered)))
    # Preserve the legacy general-purpose manual additions in the combined view.
    if os.path.isfile(local_file):
        with open(local_file, encoding="utf-8-sig") as f:
            ids.extend(line.partition("#")[0].strip() for line in f)
    return _catalog_from_ids([model for model in ids
                              if isinstance(model, str) and MODEL_ID.fullmatch(model)])


def build_group_catalog(group, discovered=()):
    """Build a catalog scoped to one key group, plus its current discovery."""
    known = group_model_ids(group)
    valid_discovered = [model for model in discovered
                        if isinstance(model, str) and MODEL_ID.fullmatch(model)]
    custom = []
    xingchi_dir = os.environ.get("XINGCHI_HOME") or os.path.join(HOME, ".xingchi")
    local_file = os.path.join(xingchi_dir, "models.txt")
    if os.path.isfile(local_file):
        with open(local_file, encoding="utf-8-sig") as f:
            for line in f:
                value = line.partition("#")[0].strip()
                prefix, separator, model = value.partition(":")
                if separator and prefix == group and MODEL_ID.fullmatch(model):
                    custom.append(model)
    return _catalog_from_ids(dict.fromkeys((*known, *valid_discovered, *custom)))


def configure_codex(discovered=(), astra_discovered=()):
    codex_dir = os.path.abspath(os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex"))
    path = os.path.join(codex_dir, "config.toml")
    catalog_path = os.path.join(codex_dir, "xingchi-models.json")
    astra_catalog_path = os.path.join(codex_dir, "xingchi-models-astra.json")
    xingchi_dir = os.environ.get("XINGCHI_HOME") or os.path.join(HOME, ".xingchi")
    text = read_text(path)
    if re.search(r"(?m)^[ \t]*\[model_providers\.OpenAI\.http_headers\]", text):
        fail("Codex http_headers must be an inline table; config unchanged")

    catalog = build_group_catalog("sol", discovered)
    astra_catalog = build_group_catalog("astra", astra_discovered)
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
        "env_key": '"XINGCHI_API_KEY"',
        "supports_websockets": "false",
        # Remove the legacy inline credential written by older installers.
        "experimental_bearer_token": None,
        "bearer_token": None,
        "http_headers": '{ "x-openai-actor-authorization" = "local-image-extension" }',
    }
    blocks = re.split(r"(?m)(?=^[ \t]*\[)", text)
    # Migrate from the former model-based dual-provider setup. Key selection is
    # now explicit in the launcher; the OpenAI provider always reads the
    # selected key from XINGCHI_API_KEY.
    blocks = [block for block in blocks if not re.match(
        r"[ \t]*\[model_providers\.XingchiAstra(?:\.[^\]\n]+)?\]", block
    )]
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
    targets = {
        "": root,
        "[model_providers.OpenAI]": provider,
        "[features]": features,
    }
    # OpenAI-named providers default to remote compaction v2. Xingchi rejects
    # its compaction_trigger input, so summarize through ordinary Responses.
    capability_header = "[model_providers.OpenAI.capabilities]"
    if capability_header in headers:
        targets[capability_header] = {"remote_compaction": '"unsupported"'}
    else:
        body = blocks[headers.index("[model_providers.OpenAI]")] if "[model_providers.OpenAI]" in headers else ""
        inline = re.search(r"(?m)^[ \t]*capabilities[ \t]*=[ \t]*([^\n]*)", body)
        if inline:
            match = re.fullmatch(r"\{([^{}]*)\}[ \t]*(?:#.*)?", inline[1].strip())
            if not match:
                fail("Codex capabilities must use a single-line inline table or a section; config unchanged")
            fields = re.sub(r'''(?:\bremote_compaction|"remote_compaction"|'remote_compaction')[ \t]*=[ \t]*(?:"[^"\n]*"|'[^'\n]*')[ \t]*,?''', "", match[1]).strip().rstrip(",")
            provider["capabilities"] = "{ " + (fields + ", " if fields else "") + 'remote_compaction = "unsupported" }'
        else:
            provider["capabilities.remote_compaction"] = '"unsupported"'

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
    write_text(astra_catalog_path, json.dumps(astra_catalog, indent=2) + "\n")
    write_text(path, "".join(blocks).lstrip("\n"))
    return path


def main():
    # Redirected Windows output can use a legacy code page. Status messages
    # must not abort setup when a group label or user path is unrepresentable.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if len(sys.argv) == 3 and sys.argv[1] == "check-cli":
        sys.exit(0 if compatible_cli(sys.argv[2]) else 1)
    if len(sys.argv) != 2 or sys.argv[1] != "codex":
        fail("usage: config.py codex | config.py check-cli VERSION")
    if not KEY:
        fail("XINGCHI_API_KEY is not set")
    discovered = discover_models()
    sol_models = discovered["sol"]
    astra_models = discovered["astra"]
    if sol_models:
        print("  [OK] Sol upstream lists: " + ", ".join(dict.fromkeys(sol_models)))
    if astra_models:
        print("  [OK] Astra upstream lists: " + ", ".join(dict.fromkeys(astra_models)))
    print(f"  configured {configure_codex(sol_models, astra_models)}")
    sol_catalog = build_group_catalog("sol", sol_models)
    astra_catalog = build_group_catalog("astra", astra_models)
    print("  GPT公益 /model: " + str(len(sol_catalog["models"])) + " models")
    print("  Astra /model: " + str(len(astra_catalog["models"])) + " models")
    print("  reasoning: choose per model; saved model and effort are preserved")
    print("  compaction: summarize through ordinary Responses requests")
    if sol_models and MODEL not in sol_models:
        print("  [NOTE] gpt-6.1-sol was not listed for the GPT公益 key.")
        print("  Catalog entries do not grant model access; Xingchi may reject them.")
    if ASTRA_KEY and not astra_models:
        print("  [NOTE] Astra key returned no models; keeping the known Astra group catalog.")


if __name__ == "__main__":
    main()
