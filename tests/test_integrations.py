import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("xingchi_integrations", ROOT / "lib/integrations.py")
integrations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(integrations)


def skill(path, name, body="content"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n{body}\n",
        encoding="utf-8",
    )


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.codex_home = self.home / ".codex"
        self.xingchi_home = self.home / ".xingchi"
        self.codex_home.mkdir()
        self.xingchi_home.mkdir()

    def test_reuses_existing_skill_alias_on_reinstall(self):
        source = self.codex_home / "skills" / "local-skill"
        shared = self.home / ".agents" / "skills"
        skill(source, "local-skill")
        shared.mkdir(parents=True)
        (self.home / "Projects").mkdir()

        with patch.dict(os.environ, {}, clear=False):
            integrations.configure(self.home, self.codex_home, self.xingchi_home)
            first = sorted(shared.glob("xingchi-*"))
            self.assertEqual(len(first), 1)
            self.assertTrue(first[0].is_symlink())
            self.assertEqual(first[0].resolve(), source.resolve())

            integrations.configure(self.home, self.codex_home, self.xingchi_home)
            second = sorted(shared.glob("xingchi-*"))
            self.assertEqual([item.name for item in second], [item.name for item in first])

    def test_duplicate_skill_name_has_one_active_winner(self):
        codex_source = self.codex_home / "skills" / "duplicate-codex"
        claude_source = self.home / ".claude" / "skills" / "duplicate-claude"
        shared = self.home / ".agents" / "skills"
        skill(codex_source, "duplicate")
        skill(claude_source, "duplicate")
        shared.mkdir(parents=True)
        (self.home / "Projects").mkdir()

        integrations.configure(self.home, self.codex_home, self.xingchi_home)
        aliases = list(shared.glob("xingchi-*"))
        self.assertEqual(len(aliases), 1)
        self.assertEqual(aliases[0].resolve(), codex_source.resolve())

        config = tomllib.loads((self.codex_home / "config.toml").read_text(encoding="utf-8"))
        disabled = [rule["path"] for rule in config["skills"]["config"] if not rule["enabled"]]
        self.assertIn(str(claude_source / "SKILL.md"), disabled)
        report = json.loads((self.xingchi_home / "skill-conflicts.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report), 1)

    def test_mcp_definitions_are_complete_and_unauthenticated_entries_are_inactive(self):
        (self.home / "Projects").mkdir()
        existing = self.codex_home / "config.toml"
        existing.write_text(
            '[mcp_servers.github]\nurl = "https://api.githubcopilot.com/mcp/"\n'
            'bearer_token_env_var = "GITHUB_PAT_TOKEN"\n\n'
            '[mcp_servers.supabase]\nurl = "https://mcp.supabase.com/mcp"\n',
            encoding="utf-8",
        )
        credentials = {
            "GITHUB_PAT_TOKEN", "FIRECRAWL_API_KEY", "DATABASE_URL",
            "EXA_API_KEY", "GITLAB_PERSONAL_ACCESS_TOKEN", "API_KEY",
            "MDB_MCP_CONNECTION_STRING",
        }
        env = {key: value for key, value in os.environ.items()
               if key not in credentials}
        with patch.dict(os.environ, env, clear=True):
            integrations.configure(self.home, self.codex_home, self.xingchi_home)

        settings = tomllib.loads(existing.read_text(encoding="utf-8"))
        for name in {
            "github", "exa", "gitlab", "magic", "mongodb", "postgres",
            "supabase", "linear", "atlassian", "figma", "filesystem",
            "firecrawl", "redis", "sqlite", "tavily",
        }:
            self.assertFalse(settings["mcp_servers"][name]["enabled"], name)
        for name in integrations.portable_servers(self.home, self.xingchi_home):
            self.assertIn(name, settings["mcp_servers"])
        text = existing.read_text(encoding="utf-8")
        self.assertEqual(text.count(integrations.SKILL_START), 0)
        self.assertEqual(text.count(integrations.SKILL_END), 0)

    def test_portable_mcp_inventory_is_explicit(self):
        (self.home / "Projects").mkdir()
        self.assertEqual(set(integrations.portable_servers(self.home, self.xingchi_home)), {
            "rust-anything", "openaiDeveloperDocs", "context7", "github", "exa",
            "gitlab", "magic", "mongodb", "filesystem", "sequential-thinking",
            "playwright", "postgres", "supabase", "linear", "atlassian", "figma",
            "chrome-devtools", "firecrawl", "redis", "repomix", "shadcn", "sqlite",
            "tavily", "time",
        })

    def test_credentials_enable_only_the_matching_mcp_servers(self):
        (self.home / "Projects").mkdir()
        existing = self.codex_home / "config.toml"
        with patch.dict(os.environ, {
            "EXA_API_KEY": "test-exa",
            "GITLAB_PERSONAL_ACCESS_TOKEN": "test-gitlab",
            "API_KEY": "test-magic",
            "MDB_MCP_CONNECTION_STRING": "mongodb://localhost/test",
            "GITHUB_PAT_TOKEN": "test-github",
            "FIRECRAWL_API_KEY": "test-firecrawl",
            "DATABASE_URL": "postgresql://localhost/test",
        }, clear=False):
            integrations.configure(self.home, self.codex_home, self.xingchi_home)
        settings = tomllib.loads(existing.read_text(encoding="utf-8"))
        for name in integrations.AUTHENTICATED_MCP:
            self.assertNotIn("enabled", settings["mcp_servers"][name], name)

    def test_repairs_only_known_legacy_mcp_placeholders(self):
        (self.home / "Projects").mkdir()
        existing = self.codex_home / "config.toml"
        legacy_postgres = "postgresql://user:" + "password" + "@localhost:5432/mydb"
        existing.write_text(
            '[mcp_servers.postgres]\n'
            'command = "npx"\n'
            'args = ["-y", "@modelcontextprotocol/server-postgres", '
            f'{legacy_postgres!r}]\n\n'
            '[mcp_servers.sqlite]\n'
            'command = "uvx"\n'
            'args = ["mcp-server-sqlite", "--db-path", "/path/to/database.db"]\n\n'
            '[mcp_servers.private-tool]\n'
            'command = "uvx"\n'
            'args = ["private-tool", "/path/to/database.db"]\n',
            encoding="utf-8",
        )
        integrations.configure(self.home, self.codex_home, self.xingchi_home)
        settings = tomllib.loads(existing.read_text(encoding="utf-8"))
        self.assertEqual(settings["mcp_servers"]["postgres"]["args"][-1], integrations.POSTGRES_DEFAULT)
        self.assertEqual(
            settings["mcp_servers"]["sqlite"]["args"][-1],
            str(self.xingchi_home / "workspace" / "codex.sqlite3"),
        )
        self.assertEqual(settings["mcp_servers"]["private-tool"]["args"][-1], "/path/to/database.db")

    def test_explicit_mcp_opt_in_is_preserved(self):
        (self.home / "Projects").mkdir()
        existing = self.codex_home / "config.toml"
        existing.write_text(
            '[mcp_servers.supabase]\nurl = "https://mcp.supabase.com/mcp"\n',
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"XINGCHI_ENABLE_MCP_SUPABASE": "1"}, clear=False):
            integrations.configure(self.home, self.codex_home, self.xingchi_home)
        settings = tomllib.loads(existing.read_text(encoding="utf-8"))
        self.assertNotIn("enabled", settings["mcp_servers"]["supabase"])

    def test_unknown_existing_mcp_definition_is_preserved(self):
        (self.home / "Projects").mkdir()
        existing = self.codex_home / "config.toml"
        existing.write_text(
            '[mcp_servers.private-tool]\n'
            'command = "uvx"\n'
            'args = ["private-tool", "--workspace", "/tmp/work"]\n\n',
            encoding="utf-8",
        )
        integrations.configure(self.home, self.codex_home, self.xingchi_home)
        settings = tomllib.loads(existing.read_text(encoding="utf-8"))
        self.assertEqual(settings["mcp_servers"]["private-tool"], {
            "command": "uvx",
            "args": ["private-tool", "--workspace", "/tmp/work"],
        })


if __name__ == "__main__":
    unittest.main()
