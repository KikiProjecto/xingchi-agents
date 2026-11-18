import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("xingchi_config", ROOT / "lib/config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.patch = patch.multiple(
            config,
            HOME=str(self.home),
            UPSTREAM="https://api.xingchiapi.com/v1",
            KEY="fake-key",
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def put(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_only_codex(self):
        self.assertEqual(config.MODELS, ("gpt-6.1-sol",))

    def test_writes_provider_and_model(self):
        path = Path(config.configure_codex())
        settings = tomllib.loads(path.read_text())
        self.assertEqual(settings["model"], "gpt-6.1-sol")
        self.assertEqual(settings["model_provider"], "OpenAI")
        provider = settings["model_providers"]["OpenAI"]
        self.assertEqual(provider["base_url"], config.UPSTREAM)
        self.assertEqual(provider["model_catalog_url"], config.UPSTREAM + "/models")
        self.assertEqual(provider["wire_api"], "responses")
        self.assertFalse(provider["requires_openai_auth"])
        self.assertEqual(provider["experimental_bearer_token"], "fake-key")
        self.assertEqual(
            provider["http_headers"]["x-openai-actor-authorization"],
            "local-image-extension",
        )
        self.assertTrue(settings["features"]["api_key_model_discovery"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_merges_existing_and_backs_up(self):
        path = self.put(
            ".codex/config.toml",
            'model = "old"\ncustom = true\n'
            "[features]\nkeep = true\n"
            '[model_providers.OpenAI]\nbase_url = "stale"\ncustom = "keep"\n'
            '[profiles.work]\nmodel = "keep"\n',
        )
        config.configure_codex()
        first = path.read_text()
        config.configure_codex()
        settings = tomllib.loads(path.read_text())
        self.assertTrue(settings["custom"])
        self.assertTrue(settings["features"]["keep"])
        self.assertEqual(settings["profiles"]["work"]["model"], "keep")
        self.assertEqual(settings["model_providers"]["OpenAI"]["custom"], "keep")
        self.assertEqual(settings["model"], "gpt-6.1-sol")
        self.assertEqual(settings["model_providers"]["OpenAI"]["base_url"], config.UPSTREAM)
        self.assertEqual(Path(str(path) + ".xingchi.bak").read_text(), first)

    def test_header_appended_to_bare_file(self):
        path = self.put(".codex/config.toml", "[model_providers.OpenAI]\n")
        config.configure_codex()
        settings = tomllib.loads(path.read_text())
        self.assertEqual(settings["model"], config.MODEL)
        self.assertEqual(settings["model_providers"]["OpenAI"]["wire_api"], "responses")

    def test_multiline_rejected_without_write(self):
        original = 'model = """old\nvalue"""\n'
        path = self.put(".codex/config.toml", original)
        with self.assertRaises(SystemExit):
            config.configure_codex()
        self.assertEqual(path.read_text(), original)

    def test_invalid_agent_rejected(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "lib/config.py"), "claude"],
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.home), "XINGCHI_API_KEY": "fake-key"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage:", result.stderr)

    def test_requires_key(self):
        config.KEY = ""
        with patch.object(sys, "argv", ["config.py", "codex"]), \
                self.assertRaises(SystemExit):
            config.main()


if __name__ == "__main__":
    unittest.main()
