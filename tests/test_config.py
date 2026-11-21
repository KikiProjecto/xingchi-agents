import importlib.util
import json
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
        self.codex_home = patch.dict(os.environ, {"CODEX_HOME": "", "XINGCHI_HOME": ""})
        self.codex_home.start()
        self.addCleanup(self.codex_home.stop)

    def put(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_writes_provider_and_model(self):
        path = Path(config.configure_codex())
        settings = tomllib.loads(path.read_text())
        self.assertEqual(settings["model"], "gpt-6.1-sol")
        self.assertEqual(settings["model_provider"], "OpenAI")
        provider = settings["model_providers"]["OpenAI"]
        self.assertEqual(provider["base_url"], config.UPSTREAM)
        self.assertNotIn("model_catalog_url", provider)
        self.assertNotIn("model_reasoning_effort", settings)
        self.assertEqual(settings["features"], {
            "api_key_model_discovery": True, "image_generation": True, "goals": True,
        })
        catalog_path = Path(settings["model_catalog_json"])
        self.assertTrue(catalog_path.is_file())
        for entry in json.loads(catalog_path.read_text())["models"]:
            # Xingchi rejects the additional_tools item these fields produce.
            self.assertNotIn("multi_agent_version", entry)
            self.assertNotIn("multi_agent_reasoning_effort", entry)
        self.assertEqual(provider["wire_api"], "responses")
        self.assertFalse(provider["requires_openai_auth"])
        self.assertEqual(provider["env_key"], "XINGCHI_API_KEY")
        self.assertFalse(provider["supports_websockets"])
        self.assertNotIn("experimental_bearer_token", provider)
        self.assertNotIn("fake-key", path.read_text(encoding="utf-8"))
        self.assertEqual(provider["capabilities"]["remote_compaction"], "unsupported")
        self.assertEqual(
            provider["http_headers"]["x-openai-actor-authorization"],
            "local-image-extension",
        )
        self.assertNotIn("XingchiAstra", settings["model_providers"])
        astra_catalog = json.loads((path.parent / "xingchi-models-astra.json").read_text())
        self.assertEqual([m["slug"] for m in astra_catalog["models"]], config.group_model_ids("astra"))
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_catalog_matches_shipped_four_models_even_if_upstream_lists_only_sol(self):
        shipped = json.loads((ROOT / "lib/models.json").read_text(encoding="utf-8"))
        catalog = config.build_catalog(["gpt-6.1-sol"])
        self.assertEqual(catalog, shipped)
        self.assertEqual([model["slug"] for model in catalog["models"]], list(config.MODELS))
        for model in catalog["models"]:
            efforts = [level["effort"] for level in model["supported_reasoning_levels"]]
            expected = ["low", "medium", "high", "xhigh", "max"]
            if model["slug"] != "gpt-6-luna":
                expected.append("ultra")
            self.assertEqual(efforts, expected)

    def test_configures_separate_model_catalogs_for_each_key_group(self):
        sol = ["gpt-6.1-sol", "gpt-6", "gpt-5.6-sol"]
        astra = ["gpt-6.1-sol", "gpt-6-astra", "codex-auto-review",
                 "gpt-image-2.5-flare", "text-embedding-3-large"]
        path = Path(config.configure_codex(sol, astra))
        catalog = json.loads(Path(tomllib.loads(path.read_text())["model_catalog_json"]).read_text())
        self.assertEqual([entry["slug"] for entry in catalog["models"]], sol)
        astra_catalog = json.loads((Path(path).parent / "xingchi-models-astra.json").read_text())
        self.assertEqual([entry["slug"] for entry in astra_catalog["models"]],
                         list(dict.fromkeys((*config.group_model_ids("astra"), *astra))))
        self.assertFalse((self.home / ".xingchi/model-routes.json").exists())

    def test_reinstall_removes_legacy_astra_provider(self):
        self.put(
            ".codex/config.toml",
            '[model_providers.XingchiAstra]\nname = "old Astra provider"\n'
            'base_url = "https://example.invalid/v1"\n\n'
            '[model_providers.XingchiAstra.capabilities]\n'
            'remote_compaction = "unsupported"\n\n'
            '[features]\nimage_generation = false\n',
        )
        path = Path(config.configure_codex())
        text = path.read_text(encoding="utf-8")
        settings = tomllib.loads(text)
        self.assertNotIn("XingchiAstra", settings["model_providers"])
        self.assertNotIn("old Astra provider", text)
        self.assertFalse((self.home / ".xingchi/model-routes.json").exists())

    def test_bom_model_list_deduplicates_and_does_not_invent_reasoning_for_unknown_id(self):
        self.put(".xingchi/models.txt", "\ufeff# extras\ngpt-6-astra\ngpt-7-new # manual\ninvalid model\n")
        catalog = config.build_catalog(["gpt-6-astra", "gpt-6.1-terra"])["models"]
        self.assertEqual([model["slug"] for model in catalog],
                         [*config.MODELS, "gpt-6.1-terra", "gpt-7-new"])
        self.assertEqual(catalog[-1]["supported_reasoning_levels"], [])

    def test_reinstall_preserves_explicit_feature_choices(self):
        self.put(".codex/config.toml", '[features]\nimage_generation = false\ngoals = false\ncustom = true\n')
        path = Path(config.configure_codex())
        features = tomllib.loads(path.read_text())["features"]
        self.assertEqual(features, {
            "api_key_model_discovery": True, "image_generation": False,
            "goals": False, "custom": True,
        })

    def test_supported_cli_versions(self):
        for version in ("codex-cli 0.170.0", "codex-cli 0.170.1", "codex-cli 0.171.0", "codex-cli 1.0.0"):
            with self.subTest(version=version):
                self.assertTrue(config.compatible_cli(version))
        for version in ("", "codex-cli 0.169.9", "codex-cli 0.99.0", "codex-cli test"):
            with self.subTest(version=version):
                self.assertFalse(config.compatible_cli(version))

    def test_setup_status_handles_legacy_windows_output_encoding(self):
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT / 'lib')!r}); "
            "import config; "
            "config.discover_models = lambda: "
            "{'sol': ['gpt-6.1-sol'], 'astra': []}; "
            "sys.argv = ['config.py', 'codex']; config.main()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={
                **os.environ,
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                "CODEX_HOME": str(self.home / ".codex"),
                "XINGCHI_HOME": str(self.home / ".xingchi"),
                "XINGCHI_API_KEY": "test-key",
                "XINGCHI_ASTRA_API_KEY": "",
                "PYTHONIOENCODING": "cp1252:strict",
                "PYTHONUTF8": "0",
            },
            capture_output=True,
            text=True,
            encoding="cp1252",
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reasoning: choose per model", result.stdout)
        settings = tomllib.loads(
            (self.home / ".codex/config.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(settings["model"], "gpt-6.1-sol")

    def test_cli_version_check_does_not_require_key(self):
        for version, expected in (("codex-cli 0.170.0", 0), ("codex-cli 0.169.0", 1)):
            result = subprocess.run(
                [sys.executable, str(ROOT / "lib/config.py"), "check-cli", version],
                env={**os.environ, "XINGCHI_API_KEY": ""}, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, expected)
            self.assertNotIn("XINGCHI_API_KEY", result.stderr)

    def test_merges_existing_and_backs_up(self):
        path = self.put(
            ".codex/config.toml",
            'model = "old"\ncustom = true\n'
            "[features]\nkeep = true\n"
            '[model_providers.OpenAI]\nbase_url = "stale"\n'
            'model_catalog_url = "https://old.example/v1/models"\ncustom = "keep"\n'
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
        self.assertNotIn("model_catalog_url", settings["model_providers"]["OpenAI"])
        self.assertEqual(Path(str(path) + ".xingchi.bak").read_text(), first)

    def test_header_appended_to_bare_file(self):
        path = self.put(".codex/config.toml", "[model_providers.OpenAI]\n")
        config.configure_codex()
        settings = tomllib.loads(path.read_text())
        self.assertEqual(settings["model"], config.MODEL)
        self.assertEqual(settings["model_providers"]["OpenAI"]["wire_api"], "responses")

    def test_reinstall_preserves_saved_model_from_selected_group_and_effort(self):
        custom_home = self.home / "Custom Codex Home"
        with patch.dict(os.environ, {"CODEX_HOME": str(custom_home)}):
            discovered = ["gpt-6.1-sol", "gpt-6.1-terra"]
            path = Path(config.configure_codex(discovered))
            original = path.read_text(encoding="utf-8").replace(
                'model = "gpt-6.1-sol"', 'model = "gpt-6.1-terra"'
            )
            path.write_text('model_reasoning_effort = "high"\n' + original, encoding="utf-8")
            config.configure_codex(discovered)
        settings = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(path.parent, custom_home)
        self.assertEqual(Path(settings["model_catalog_json"]).parent, custom_home)
        self.assertEqual(settings["model_reasoning_effort"], "high")
        self.assertEqual(settings["model"], "gpt-6.1-terra")

    def test_compaction_override_preserves_other_provider_capabilities(self):
        for capabilities in (
            'capabilities = { remote_compaction = "v2", external_web_access = false }\n',
            'capabilities = { external_web_access = false, remote_compaction = "v2" }\n',
            'capabilities = { external_web_access = false }\n',
            'capabilities.remote_compaction = "v2"\ncapabilities.external_web_access = false\n',
            '[model_providers.OpenAI.capabilities]\nremote_compaction = "v2"\nexternal_web_access = false\n',
        ):
            with self.subTest(capabilities=capabilities):
                path = self.put(".codex/config.toml", '[model_providers.OpenAI]\n' + capabilities)
                config.configure_codex()
                config.configure_codex()
                provider = tomllib.loads(path.read_text())["model_providers"]["OpenAI"]
                self.assertEqual(provider["capabilities"], {
                    "remote_compaction": "unsupported", "external_web_access": False,
                })

    def test_multiline_capabilities_rejected_without_write(self):
        original = '[model_providers.OpenAI]\ncapabilities = {\nremote_compaction = "v2"\n}\n'
        path = self.put(".codex/config.toml", original)
        with self.assertRaises(SystemExit):
            config.configure_codex()
        self.assertEqual(path.read_text(), original)

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
