import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == "nt", "POSIX launchers are tested on macOS/Linux")
class LauncherTests(unittest.TestCase):
    def test_codex_launcher_forwards_args_and_reads_key(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            xdir = home / ".xingchi"
            xdir.mkdir()
            (xdir / "upstream.key").write_text("local-test-key\n")

            fake = home / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "print(json.dumps({'args': sys.argv[1:], "
                "'url': os.getenv('OPENAI_BASE_URL'), "
                "'key': os.getenv('OPENAI_API_KEY')}))\n"
            )
            fake.chmod(0o755)

            result = subprocess.run(
                ["sh", str(ROOT / "bin/xingchi-codex"), "--model", "two words", "*"],
                env={
                    "PATH": str(home) + os.pathsep + os.environ["PATH"],
                    "HOME": str(home),
                    "XINGCHI_HOME": str(xdir),
                },
                capture_output=True,
                text=True,
                check=True,
            )
            output = json.loads(result.stdout)
            # A shared daemon can retain the catalog from before installation.
            self.assertEqual(output["args"], ["--no-daemon", "--model", "two words", "*"])
            self.assertEqual(output["url"], "https://api.xingchiapi.com/v1")
            self.assertEqual(output["key"], "local-test-key")

    def test_codex_launcher_errors_without_key(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = subprocess.run(
                ["sh", str(ROOT / "bin/xingchi-codex"), "--help"],
                env={"PATH": os.environ["PATH"], "HOME": str(home)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("API key missing", result.stderr)

    def test_doctor_reports_model_and_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fake = home / "codex"
            fake.write_text(
                "#!/bin/sh\n"
                "echo '  model                    gpt-6.1-sol · OpenAI'\n"
                "echo '  default model provider   OpenAI'\n"
                "echo '  OpenAI API inference URL https://api.xingchiapi.com/v1/x reachable (HTTP 404)'\n"
                "echo '  unrelated noise line'\n"
                "exit 0\n"
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["sh", str(ROOT / "bin/xingchi"), "--doctor"],
                env={"PATH": str(home) + os.pathsep + os.environ["PATH"], "HOME": str(home)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("gpt-6.1-sol", result.stdout)
            self.assertIn("OpenAI", result.stdout)
            self.assertNotIn("unrelated noise", result.stdout)
            self.assertIn("codex doctor: healthy", result.stdout)

    def test_doctor_propagates_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fake = home / "codex"
            fake.write_text(
                "#!/bin/sh\n"
                "echo '  model                    gpt-6.1-sol · OpenAI'\n"
                "echo 'failed check'\n"
                "exit 3\n"
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["sh", str(ROOT / "bin/xingchi"), "--doctor"],
                env={"PATH": str(home) + os.pathsep + os.environ["PATH"], "HOME": str(home)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("reported problems (exit 3)", result.stdout)

    def test_unknown_option_rejected(self):
        result = subprocess.run(
            ["sh", str(ROOT / "bin/xingchi"), "--bogus"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown option", result.stderr)

    def test_repo_is_codex_only(self):
        self.assertEqual(sorted(p.name for p in (ROOT / "bin").iterdir()),
                         ["xingchi", "xingchi-codex"])
        self.assertFalse((ROOT / "share").exists())

    def test_installers_match_direct_upstream(self):
        unix = (ROOT / "install.sh").read_text()
        windows = (ROOT / "install.ps1").read_text()
        for text in (unix, windows):
            self.assertIn("gpt-6.1-sol", text)
            self.assertIn("https://api.xingchiapi.com/v1", text)
            self.assertIn("xingchi-codex", text)
            for leftover in ("litellm", "4010", "bridge.key", "bridge-up"):
                self.assertNotIn(leftover, text.lower())

    def test_readme_matches_direct_upstream(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("gpt-6.1-sol", readme)
        self.assertIn("api.xingchiapi.com", readme)
        self.assertIn("Responses", readme)
        self.assertNotIn("master_key", readme)
        self.assertNotIn("litellm.yaml", readme.lower())

    def test_installer_trims_padded_key_and_writes_everything(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fakepath = home / "fakebin"
            fakepath.mkdir()
            (fakepath / "codex").write_text("#!/bin/sh\necho 'codex-cli 0.170.0'\n")
            (fakepath / "codex").chmod(0o755)

            result = subprocess.run(
                ["sh", str(ROOT / "install.sh"), "--yes"],
                env={
                    "HOME": str(home),
                    "PATH": str(fakepath) + os.pathsep + "/usr/bin:/bin",
                    "XINGCHI_HOME": str(home / ".xingchi"),
                    "XINGCHI_BIN": str(home / "bin"),
                    "XINGCHI_UPSTREAM": "http://127.0.0.1:9/v1",
                    "XINGCHI_API_KEY": "  padded-key  \r",
                    "SHELL": "/bin/sh",
                },
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Installation complete", result.stdout)
            # The pasted key is trimmed before it reaches any file.
            self.assertEqual((home / ".xingchi/upstream.key").read_text(), "padded-key\n")
            config_text = (home / ".codex/config.toml").read_text()
            self.assertIn('experimental_bearer_token = "padded-key"', config_text)
            self.assertNotIn("padded-key  ", config_text)
            launcher = home / "bin/xingchi-codex"
            self.assertTrue(launcher.exists())
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o755)
            settings = tomllib.loads(config_text)
            catalog = json.loads(Path(settings["model_catalog_json"]).read_text())
            self.assertEqual([model["slug"] for model in catalog["models"]],
                             ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-6-terra"])
            self.assertEqual(settings["features"], {
                "api_key_model_discovery": True, "image_generation": True, "goals": True,
            })
            self.assertIn("--no-daemon", launcher.read_text())

    def test_installer_upgrades_old_cli_and_preserves_custom_home_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fakepath = home / "fakebin"
            fakepath.mkdir()
            codex = fakepath / "codex"
            codex.write_text("#!/bin/sh\necho 'codex-cli 0.169.0'\n")
            codex.chmod(0o755)
            npm = fakepath / "npm"
            npm.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" > "$XINGCHI_TEST_NPM_LOG"\n'
                'printf "#!/bin/sh\\necho codex-cli 0.170.0\\n" > "$XINGCHI_TEST_CODEX"\n'
            )
            npm.chmod(0o755)
            codex_home = home / "Custom Codex Home"
            codex_home.mkdir()
            config = codex_home / "config.toml"
            config.write_text('model = "gpt-6-luna"\nmodel_reasoning_effort = "max"\n')
            npm_log = home / "npm.log"
            result = subprocess.run(
                ["sh", str(ROOT / "install.sh"), "--yes"],
                env={"HOME": str(home), "PATH": str(fakepath) + os.pathsep + "/usr/bin:/bin",
                     "CODEX_HOME": str(codex_home), "XINGCHI_HOME": str(home / ".xingchi"),
                     "XINGCHI_BIN": str(home / "bin"), "XINGCHI_API_KEY": "test-key",
                     "XINGCHI_UPSTREAM": "http://127.0.0.1:9/v1", "SHELL": "/bin/sh",
                     "XINGCHI_TEST_NPM_LOG": str(npm_log), "XINGCHI_TEST_CODEX": str(codex)},
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(npm_log.read_text().strip(), "install -g @openai/codex")
            settings = tomllib.loads(config.read_text())
            self.assertEqual(settings["model"], "gpt-6-luna")
            self.assertEqual(settings["model_reasoning_effort"], "max")
            self.assertEqual(Path(settings["model_catalog_json"]).parent, codex_home)

    def test_installer_restores_echo_if_key_prompt_is_interrupted(self):
        unix = (ROOT / "install.sh").read_text()
        self.assertIn("trap 'stty echo", unix)
        self.assertIn("stty echo", unix)

    def test_no_credentials_in_repo(self):
        pattern = re.compile(r"sk-[0-9a-fA-F]{32,}")
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            if path.name.endswith((".pyc", ".png", ".jpg", ".zip")):
                continue
            text = path.read_text(errors="ignore")
            self.assertIsNone(pattern.search(text), f"secret-like token in {path}")


if __name__ == "__main__":
    unittest.main()
