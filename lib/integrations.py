#!/usr/bin/env python3
"""Link local skills and register portable MCP defaults without exporting secrets."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib


SKILL_START = "# BEGIN Xingchi managed skill conflicts"
SKILL_END = "# END Xingchi managed skill conflicts"
SKILL_NAME = re.compile(r'^name:[ \t]*("[^"\n]+"|\'[^\'\n]+\'|[^#\r\n]+)', re.MULTILINE)
SKIP_DIRS = {"node_modules", "__pycache__"}
MANAGED_LINK_PREFIX = "xingchi-"
POSTGRES_DEFAULT = "postgresql://localhost:5432/mydb"

# These servers are useful once authenticated, but starting them by default
# without credentials makes Codex mark the whole MCP startup as incomplete.
# The installer keeps their definitions and enables them only when the local
# machine has the required credential or an explicit opt-in environment flag.
AUTHENTICATED_MCP = {
    "github": "GITHUB_PAT_TOKEN",
    "firecrawl": "FIRECRAWL_API_KEY",
    "postgres": "DATABASE_URL",
    "exa": "EXA_API_KEY",
    "gitlab": "GITLAB_PERSONAL_ACCESS_TOKEN",
    "magic": "API_KEY",
    "mongodb": "MDB_MCP_CONNECTION_STRING",
}
OAUTH_MCP = {"supabase", "linear", "atlassian", "figma"}


def skill_name(path):
    with path.open(encoding="utf-8-sig") as stream:
        lines = stream.read(32768).splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    header = []
    for line in lines[1:]:
        if line.strip() == "---":
            match = SKILL_NAME.search("\n".join(header))
            return (match[1].strip().strip("\"'") or None) if match else None
        header.append(line)
    return None


def scan_skills(root):
    pending = [root]
    seen = set()
    while pending:
        directory = pending.pop()
        if not directory.is_dir():
            continue
        canonical = directory.resolve()
        if canonical in seen:
            continue
        seen.add(canonical)
        skill = directory / "SKILL.md"
        if skill.is_file():
            # Keep the user's lexical path for config/report output. Use the
            # canonical path only for cycle detection and duplicate matching;
            # on macOS, /var and /private/var are equivalent but not identical
            # strings to callers and tests.
            yield skill
        pending.extend(reversed(sorted(p for p in directory.iterdir()
                                       if not p.name.startswith(".") and p.name not in SKIP_DIRS
                                       and p.is_dir())))


def is_enabled(name, path, rules):
    enabled = True
    for rule in rules:
        if rule.get("name") == name or ("path" in rule and Path(rule["path"]).resolve() == path.resolve()):
            enabled = rule["enabled"]
    return enabled


def plan_skills(home, codex_home, rules):
    shared = home / ".agents" / "skills"
    # Preserve bundled and Codex variants first, then prefer the library
    # already visible from the shared root over the Claude-only library.
    roots = [codex_home / "skills" / ".system", codex_home / "skills", shared,
             home / ".claude" / "skills", home / ".codex" / "skills"]
    inventories = {}
    shared_files = set()
    known = {}
    winners = {}
    conflicts = []
    for i, root in enumerate(roots):
        resolved = root.resolve()
        if resolved not in inventories:
            inventories[resolved] = list(scan_skills(resolved))
        paths = inventories[resolved]
        if root == shared:
            shared_files.update(path.resolve() for path in paths)
        for path in paths:
            canonical_path = path.resolve()
            if canonical_path in known:
                continue
            name = skill_name(path)
            known[canonical_path] = name
            if not name or not is_enabled(name, path, rules):
                continue
            key = name.casefold()
            if key in winners:
                conflicts.append((name, path, winners[key][1]))
            else:
                winners[key] = (i, path, name)

    occupied = {p.name.casefold() for p in shared.iterdir()} if shared.is_dir() else set()
    links = []
    reused = 0
    for source, path, name in winners.values():
        if source == 0:
            continue
        if path.resolve() in shared_files:
            if find_existing_link(shared, path.parent) is not None:
                reused += 1
            continue
        slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")[:75] or "skill"
        target = path.parent

        # Reuse an existing managed alias that resolves to this exact skill.
        # This is what makes repeated installer runs idempotent on both POSIX
        # symlinks and Windows junctions.
        existing = find_existing_link(shared, target)
        if existing is not None:
            reused += 1
            occupied.add(existing.name.casefold())
            continue

        # Prefix reserves the managed namespace and avoids Windows device names.
        candidates = [MANAGED_LINK_PREFIX + slug]
        digest = hashlib.sha256(os.fsencode(path)).hexdigest()[:12]
        candidates.append(f"{MANAGED_LINK_PREFIX}{slug}-{digest}")
        candidates.extend(
            f"{MANAGED_LINK_PREFIX}{slug}-{digest}-{counter}"
            for counter in range(1, 1000)
        )
        alias = next(candidate for candidate in candidates
                     if candidate.casefold() not in occupied
                     and not os.path.lexists(shared / candidate))
        occupied.add(alias.casefold())
        links.append((shared / alias, target))
    return links, conflicts, len(winners), sum(name is None for name in known.values()), reused


def find_existing_link(shared, target):
    """Return a managed alias already pointing at ``target``, if any."""
    target = target.resolve()
    if not shared.is_dir():
        return None
    for candidate in sorted(shared.iterdir(), key=lambda item: item.name.casefold()):
        if not candidate.name.casefold().startswith(MANAGED_LINK_PREFIX):
            continue
        try:
            if candidate.resolve() == target:
                return candidate
        except OSError:
            continue
    return None


def ensure_shared_root(shared):
    """Create the unified root when absent, without replacing user links."""
    if shared.is_symlink() or shared.exists():
        if not shared.is_dir():
            raise OSError(f"unified skill root is not a directory: {shared}")
        return
    shared.mkdir(parents=True)


def create_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 1314):
            raise
        # Windows directory junctions do not require symlink privilege.
        result = subprocess.run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
            "-Path $env:XINGCHI_LINK -Target $env:XINGCHI_TARGET | Out-Null",
        ], env={**os.environ, "XINGCHI_LINK": str(link), "XINGCHI_TARGET": str(target)},
            capture_output=True, timeout=30)
        if result.returncode or link.resolve() != target:
            raise OSError(f"could not create directory junction: {link}") from exc


def portable_servers(home, xingchi_home):
    workspace = home / "Projects"
    if not workspace.is_dir():
        workspace = xingchi_home / "workspace"
    npm = "npx.cmd" if os.name == "nt" else "npx"

    def stdio(*args, **fields):
        return {"command": npm, "args": ["-y", *args], **fields}

    return {
        "rust-anything": stdio("rust-anything", "mcp"),
        "openaiDeveloperDocs": {"url": "https://developers.openai.com/mcp"},
        "context7": stdio("@upstash/context7-mcp"),
        "github": {"url": "https://api.githubcopilot.com/mcp/",
                   "bearer_token_env_var": "GITHUB_PAT_TOKEN",
                   "enabled": False},
        "exa": stdio("exa-mcp-server", env_vars=["EXA_API_KEY"], enabled=False),
        "gitlab": stdio("@modelcontextprotocol/server-gitlab",
                         env_vars=["GITLAB_PERSONAL_ACCESS_TOKEN"], enabled=False),
        "magic": stdio("@21st-dev/magic@latest", env_vars=["API_KEY"], enabled=False),
        "mongodb": stdio("mongodb-mcp-server@latest",
                          env_vars=["MDB_MCP_CONNECTION_STRING"], enabled=False),
        "filesystem": stdio("@modelcontextprotocol/server-filesystem", str(workspace), enabled=False),
        "sequential-thinking": stdio("@modelcontextprotocol/server-sequential-thinking"),
        "playwright": stdio("@playwright/mcp@latest"),
        "postgres": stdio("@modelcontextprotocol/server-postgres",
                           POSTGRES_DEFAULT,
                           enabled=False),
        "supabase": {"url": "https://mcp.supabase.com/mcp", "enabled": False},
        "linear": {"url": "https://mcp.linear.app/mcp", "enabled": False},
        "atlassian": {"url": "https://mcp.atlassian.com/v2/mcp", "enabled": False},
        "figma": {"url": "https://mcp.figma.com/mcp", "enabled": False},
        "chrome-devtools": stdio("chrome-devtools-mcp@latest"),
        "firecrawl": stdio("firecrawl-mcp", env_vars=["FIRECRAWL_API_KEY"], enabled=False),
        "redis": stdio("@modelcontextprotocol/server-redis", "redis://localhost:6379", enabled=False),
        "repomix": stdio("repomix", "--mcp"),
        "shadcn": stdio("shadcn@latest", "mcp"),
        "sqlite": {
            "command": "uvx" if os.name != "nt" else "uvx.exe",
            "args": ["mcp-server-sqlite", "--db-path", str(xingchi_home / "workspace" / "codex.sqlite3")],
            "enabled": False,
        },
        "tavily": {"url": "https://mcp.tavily.com/mcp/", "enabled": False},
        "time": {
            "command": "uvx" if os.name != "nt" else "uvx.exe",
            "args": ["mcp-server-time"],
        },
    }


def explicit_mcp_opt_in(name):
    flag = "XINGCHI_ENABLE_MCP_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()
    return os.environ.get(flag) == "1"


def should_disable_mcp(name, fields, home):
    """Return whether an existing implicit MCP entry should be made inactive."""
    if fields.get("enabled") is not None or explicit_mcp_opt_in(name):
        return False
    if name in AUTHENTICATED_MCP:
        env_name = AUTHENTICATED_MCP[name]
        configured = fields.get("env", {})
        if os.environ.get(env_name) or (isinstance(configured, dict) and configured.get(env_name)):
            return False
        if name == "postgres":
            args = fields.get("args", [])
            if not isinstance(args, list) or len(args) < 3:
                return True
            connection = str(args[2])
            if connection == POSTGRES_DEFAULT:
                return True
            # Do not allow credentials embedded in a portable config to become
            # active accidentally. A real DATABASE_URL is checked above.
            return bool(re.search(r"://[^/\s:]+:[^@\s]+@", connection))
        return True
    if name in OAUTH_MCP:
        return True
    if name == "filesystem":
        # The current Codex MCP client can leave the latest filesystem package
        # in a half-started state on some machines. Keep it installed but
        # require an explicit opt-in until the user has verified that pair.
        if not explicit_mcp_opt_in(name):
            return True
        args = fields.get("args", [])
        if not isinstance(args, list) or len(args) < 3:
            return True
        return not Path(os.path.expandvars(os.path.expanduser(str(args[-1])))).is_dir()
    if name == "redis":
        return True
    if name == "sqlite":
        if not explicit_mcp_opt_in(name):
            return True
        args = fields.get("args", [])
        return not (isinstance(args, list) and len(args) >= 3
                    and Path(os.path.expandvars(os.path.expanduser(str(args[-1])))).parent.is_dir())
    if name == "tavily":
        # Tavily authentication is managed by Codex's OAuth flow. Preserve an
        # existing entry; fresh installs still add it disabled by default.
        return False
    return False


def can_enable_fresh_mcp(name, home):
    """Allow a new portable entry only when its local prerequisites exist."""
    if explicit_mcp_opt_in(name):
        if name == "filesystem":
            return Path(home / "Projects").is_dir() or Path(
                os.environ.get("XINGCHI_HOME", home / ".xingchi")
            ).joinpath("workspace").is_dir()
        return True
    env_name = AUTHENTICATED_MCP.get(name)
    return bool(env_name and os.environ.get(env_name))


def disable_mcp_server(text, name):
    """Set enabled=false in one top-level MCP section without reformatting it."""
    pattern = re.compile(
        rf"(?ms)^(?P<head>\[mcp_servers\.{re.escape(name)}\]\n)"
        r"(?P<body>.*?)(?=^\[|\Z)"
    )
    match = pattern.search(text)
    if not match:
        return text
    body = match.group("body")
    enabled = re.compile(r"(?m)^[ \t]*enabled[ \t]*=[^\n]*(?:\n|$)")
    if enabled.search(body):
        body = enabled.sub("enabled = false\n", body, count=1)
    else:
        body = body.rstrip("\n") + "\nenabled = false\n"
    return text[:match.start("body")] + body + text[match.end("body"):]


def migrate_legacy_mcp_placeholders(text, xingchi_home):
    """Repair only the placeholders shipped by older Xingchi installers."""
    replacements = {
        "sqlite": ("/path/to/database.db", str(xingchi_home / "workspace" / "codex.sqlite3")),
    }
    for name, (old, new) in replacements.items():
        pattern = re.compile(
            rf"(?ms)^(?P<head>\[mcp_servers\.{re.escape(name)}\]\n)"
            r"(?P<body>.*?)(?=^\[|\Z)"
        )
        match = pattern.search(text)
        if not match:
            continue
        body = match.group("body")
        old_value = json.dumps(old, ensure_ascii=False)
        new_value = json.dumps(new, ensure_ascii=False)
        if old_value in body:
            body = body.replace(old_value, new_value, 1)
            text = text[:match.start("body")] + body + text[match.end("body"):]
    postgres = re.compile(
        r"postgresql" + r"://user:" + r"[^@\s]+@localhost:5432/mydb"
    )
    pattern = re.compile(
        r"(?ms)^(?P<head>\[mcp_servers\.postgres\]\n)"
        r"(?P<body>.*?)(?=^\[|\Z)"
    )
    match = pattern.search(text)
    if match:
        body, count = postgres.subn(POSTGRES_DEFAULT, match.group("body"), count=1)
        if count:
            text = text[:match.start("body")] + body + text[match.end("body"):]
    return text


def without_managed_conflicts(text):
    if SKILL_START not in text and SKILL_END not in text:
        return text
    block = re.compile(rf"(?ms)^{re.escape(SKILL_START)}\n.*?^{re.escape(SKILL_END)}\n?")
    result, count = block.subn("", text)
    if count != 1 or SKILL_START in result or SKILL_END in result:
        raise ValueError("invalid Xingchi skill markers in config.toml")
    return result


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".xingchi-integrations-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure(home, codex_home, xingchi_home):
    path = codex_home / "config.toml"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    base = migrate_legacy_mcp_placeholders(
        without_managed_conflicts(original), xingchi_home
    )
    settings = tomllib.loads(base)
    servers = settings.get("mcp_servers", {})
    defaults = portable_servers(home, xingchi_home)
    missing = {}
    for name, fields in defaults.items():
        if name in servers:
            continue
        fields = dict(fields)
        if fields.get("enabled") is False and can_enable_fresh_mcp(name, home):
            fields.pop("enabled")
        missing[name] = fields
    rules = settings.get("skills", {}).get("config", [])
    ensure_shared_root(home / ".agents" / "skills")
    links, conflicts, skill_count, invalid, reused = plan_skills(home, codex_home, rules)
    disabled = [name for name, fields in servers.items()
                if should_disable_mcp(name, fields, home)]

    sections = [base.rstrip()] if base.strip() else []
    for name, fields in missing.items():
        entries = [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()]
        sections.append(f"[mcp_servers.{name}]\n" + "\n".join(entries))
    if conflicts:
        entries = [f"[[skills.config]]\npath = {json.dumps(str(loser), ensure_ascii=False)}\nenabled = false"
                   for _, loser, _ in conflicts]
        sections.append(SKILL_START + "\n" + "\n\n".join(entries) + "\n" + SKILL_END)
    updated = "\n\n".join(sections) + "\n"
    for name in disabled:
        updated = disable_mcp_server(updated, name)
    tomllib.loads(updated)  # Validate the merge before touching files or links.

    created = []
    try:
        if "filesystem" in missing:
            Path(defaults["filesystem"]["args"][-1]).mkdir(parents=True, exist_ok=True)
        if "sqlite" in missing:
            Path(defaults["sqlite"]["args"][-1]).parent.mkdir(parents=True, exist_ok=True)
        for link, target in links:
            link.parent.mkdir(parents=True, exist_ok=True)
            create_link(link, target)
            created.append(link)
        if updated != original:
            if path.exists():
                atomic_write(codex_home / "config.toml.integrations.xingchi.bak", original)
            atomic_write(path, updated)
    except (OSError, subprocess.SubprocessError):
        for link in reversed(created):
            if link.is_symlink():
                link.unlink()
            else:
                link.rmdir()  # Removes the Windows junction, not its target.
        raise

    # Keep all variants available on disk. The report shows where each lives.
    report = [{"name": name, "inactive": str(loser), "active": str(winner)}
              for name, loser, winner in conflicts]
    report_path = xingchi_home / "skill-conflicts.json"
    report_text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if not report_path.exists() or report_path.read_text(encoding="utf-8") != report_text:
        atomic_write(report_path, report_text)
    print(f"  skills: {skill_count} active names, {len(created)} new links, {reused} existing links reused, {len(conflicts)} conflicting variants kept inactive")
    if invalid:
        print(f"  [WARN] {invalid} skill files lack a readable name in their front matter")
    print(f"  MCP: {len(missing)} portable definitions added, {len(servers)} existing definitions kept")
    gated = sorted(set(name for name, fields in missing.items() if fields.get("enabled") is False) | set(disabled))
    if gated:
        print("  MCP inactive until credentials/auth are configured: " + ", ".join(gated))


def main():
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex").resolve()
    xingchi_home = Path(os.environ.get("XINGCHI_HOME") or home / ".xingchi").resolve()
    try:
        configure(home, codex_home, xingchi_home)
    except (tomllib.TOMLDecodeError, UnicodeError):
        sys.exit("error: could not parse MCP or skills configuration; no changes applied by the integration step")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit(f"error: integration setup failed: {exc}")


if __name__ == "__main__":
    main()
