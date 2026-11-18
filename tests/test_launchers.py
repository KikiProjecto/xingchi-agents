import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


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
            self.assertEqual(output["args"], ["--model", "two words", "*"])
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

    def test_installer_keeps_key_out_of_process_arguments(self):
        unix = (ROOT / "install.sh").read_text()
        self.assertNotIn('-H "Authorization: Bearer', unix)
        self.assertIn("-K -", unix)
        # A Ctrl-C at the hidden prompt must restore terminal echo.
        self.assertIn("trap '", unix)
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
