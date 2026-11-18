#!/usr/bin/env python3
"""Point the Codex CLI at the Xingchi upstream.

The Xingchi upstream only serves the OpenAI *Responses* API, and only to known
coding clients. Codex speaks that protocol natively, so it talks to the
upstream directly - there is no local proxy and no second key.

Called by install.sh and install.ps1 with XINGCHI_API_KEY set. It writes
``~/.codex/config.toml``, merging into any existing file and copying the
previous version to ``<file>.xingchi.bak`` first.
"""

import json
import os
import re
import shutil
import sys

HOME = os.path.expanduser("~")
UPSTREAM = os.environ.get("XINGCHI_UPSTREAM", "https://api.xingchiapi.com/v1").rstrip("/")
KEY = os.environ.get("XINGCHI_API_KEY", "")
MODEL = "gpt-6.1-sol"
MODELS = (MODEL,)


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


def assign(section, values, label):
    """Replace (or append) top-level ``name = value`` pairs in one section."""
    for name, value in values.items():
        pattern = r"(?m)^[ \t]*" + re.escape(name) + r"[ \t]*=[^\n]*(?:\n|$)"
        for found in re.findall(pattern, section):
            previous = found.split("=", 1)[1].strip()
            if (previous.startswith(('"""', "'''", "["))
                    or (previous.startswith("{") and "}" not in previous)):
                fail(f"Codex {name} in {label} must use a single-line value; "
                     "config unchanged")
        section = re.sub(pattern, "", section)
        section = section.rstrip("\n") + f"\n{name} = {value}\n"
    return section


def configure_codex():
    path = os.path.join(HOME, ".codex", "config.toml")
    text = read_text(path)
    if re.search(r"(?m)^[ \t]*\[model_providers\.OpenAI\.http_headers\]", text):
        fail("Codex http_headers must be an inline table; config unchanged")

    root = {
        "model_provider": '"OpenAI"',
        "model": json.dumps(MODEL),
        "model_reasoning_effort": '"max"',
    }
    provider = {
        "name": '"OpenAI"',
        "base_url": json.dumps(UPSTREAM),
        "model_catalog_url": json.dumps(UPSTREAM + "/models"),
        "wire_api": '"responses"',
        "requires_openai_auth": "false",
        "experimental_bearer_token": json.dumps(KEY),
        "http_headers": '{ "x-openai-actor-authorization" = "local-image-extension" }',
    }
    features = {"api_key_model_discovery": "true"}
    targets = {"": root, "[model_providers.OpenAI]": provider, "[features]": features}

    blocks = re.split(r"(?m)(?=^[ \t]*\[)", text)
    headers = [""]
    for block in blocks[1:]:
        match = re.match(r"[ \t]*(\[[^\]\n]*\])", block)
        headers.append(match.group(1) if match else None)

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

    write_text(path, "".join(blocks).lstrip("\n"))
    return path


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "codex":
        fail("usage: config.py codex")
    if not KEY:
        fail("XINGCHI_API_KEY is not set")
    print(f"  configured {configure_codex()}")
    print(f"  model {MODEL} via {UPSTREAM} (Responses API)")


if __name__ == "__main__":
    main()
