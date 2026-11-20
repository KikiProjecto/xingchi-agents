"""Windows regression test for install.ps1.

The original Windows installer used ``$Upstream`` for the base URL and
``$upstream`` for the API key. PowerShell variable names are case-insensitive,
so the two were the same variable: storing the key overwrote the URL. The
result was ``base_url = "<api key>"`` in config.toml, ``OPENAI_BASE_URL`` set to
the key in the generated launcher, and a "verification" step that tried to
DNS-resolve the key as a hostname (printed as "could not reach upstream
/models").

These tests pin that down from both ends: statically, that the colliding name
cannot come back, and functionally, that a real installer run puts the key in
the bearer token and nowhere near a URL.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import tomllib
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parents[1]
KEY = "win-test-key-abc123"
ASTRA_KEY = "win-test-astra-key-xyz789"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

try:
    import winreg
except ImportError:  # not on Windows
    winreg = None


def _user_path():
    """The user PATH the installer would rewrite, straight from the registry."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, "Path")[0]
    except FileNotFoundError:
        return None


def _installer_code():
    """install.ps1 with its comment lines dropped.

    The header comment deliberately names the old $Upstream/$upstream pair, so
    the guard has to look at code only.
    """
    kept = [
        line
        for line in (ROOT / "install.ps1").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    return os.linesep.join(kept)


class _ModelsHandler(BaseHTTPRequestHandler):
    """Answers GET /models like the upstream and records what was sent."""

    protocol_version = "HTTP/1.1"

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            # PowerShell may reset a keep-alive connection it has finished with.
            pass

    def do_GET(self):
        self.server.requests.append(
            {"path": self.path, "authorization": self.headers.get("Authorization")}
        )
        if self.headers.get("Authorization") == "Bearer " + KEY:
            models = ["gpt-6.1-sol"]
        else:
            models = json.loads((ROOT / "lib/model-groups.json").read_text(encoding="utf-8"))["astra"]
        body = json.dumps({"object": "list", "data": [{"id": model} for model in models]}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, BrokenPipeError):
            # PowerShell can reset a reused connection after reading the body.
            pass

    def log_message(self, *args):
        pass


class InstallerSourceTests(unittest.TestCase):
    """Static guards: these run on every platform, no PowerShell needed."""

    def test_no_case_colliding_url_and_key_variables(self):
        # To PowerShell, $Upstream and $upstream are one variable. Any spelling
        # of that name is the landmine that broke the installer.
        self.assertIsNone(
            re.search(r"\$upstream\b", _installer_code(), re.IGNORECASE),
            "install.ps1 reintroduced $Upstream/$upstream. PowerShell variable "
            "names are case-insensitive, so the base URL and the API key collide "
            "and the key ends up in base_url",
        )

    def test_launchers_are_generated_from_placeholders(self):
        # Values are filled in with a literal .Replace() into single-quoted
        # here-strings, so nothing can expand into the wrong slot.
        text = (ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("__BASE_URL__", text)
        self.assertIn("__KEY_FILE__", text)

    def test_both_saved_keys_get_user_restricted_windows_acls(self):
        text = (ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("function Protect-UserFile($Path)", text)
        self.assertIn("$acl.SetAccessRuleProtection($true, $false)", text)
        self.assertIn("Protect-UserFile $KeyFile", text)
        self.assertIn("Protect-UserFile $AstraKeyFile", text)

    def test_launcher_loads_catalog_without_shared_daemon(self):
        self.assertIn("xingchi-codex-runner.py", _installer_code())
        self.assertIn("%XINGCHI_RUNNER%", _installer_code())


@unittest.skipUnless(os.name == "nt", "the Windows installer only runs on Windows")
@unittest.skipUnless(POWERSHELL, "PowerShell is not installed")
class WindowsInstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)

        self.server = HTTPServer(("127.0.0.1", 0), _ModelsHandler)
        self.server.requests = []
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = "http://127.0.0.1:%d/v1" % self.server.server_address[1]

        # A stub keeps this test offline: without it the installer would run
        # "npm install -g @openai/codex" against the real npm prefix.
        fake_bin = self.home / "fakebin"
        fake_bin.mkdir()
        (fake_bin / "codex.cmd").write_text(
            '@echo off\nif "%~1"=="--version" (\n'
            '  echo codex-cli 0.170.0\n  exit /b 0\n)\n'
            'echo %*>"%XINGCHI_TEST_ARGS%"\n'
            'echo %XINGCHI_API_KEY%>"%XINGCHI_TEST_KEY%"\nexit /b 3\n'
        )

        self.env = dict(os.environ)
        self.env.update(
            {
                "USERPROFILE": str(self.home),
                "HOME": str(self.home),
                "CODEX_HOME": str(self.home / ".codex"),
                "XINGCHI_HOME": str(self.home / ".xingchi"),
                "XINGCHI_BIN": str(self.home / "bin"),
                # Padded on purpose: the installer trims pasted keys.
                "XINGCHI_API_KEY": "  " + KEY + "  ",
                "XINGCHI_ASTRA_API_KEY": "  " + ASTRA_KEY + "  ",
                "XINGCHI_UPSTREAM": self.base_url,
                # Never touch the developer's real PATH from a test.
                "XINGCHI_NO_PATH": "1",
                "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "XINGCHI_TEST_ARGS": str(self.home / "args.txt"),
                "XINGCHI_TEST_KEY": str(self.home / "selected-key.txt"),
            }
        )
        self._result = None

    def install(self):
        if self._result is None:
            self._result = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "install.ps1"),
                    "-Yes",
                ],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=180,
            )
        self.assertEqual(
            self._result.returncode,
            0,
            "installer failed\nstdout:\n%s\nstderr:\n%s"
            % (self._result.stdout, self._result.stderr),
        )
        return self._result

    def test_key_never_lands_in_base_url(self):
        path_before = _user_path()
        self.install()
        self.assertEqual(
            path_before, _user_path(), "-NoPath must not rewrite the user PATH"
        )

        config = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('base_url = "%s"' % self.base_url, config)
        self.assertIn('env_key = "XINGCHI_API_KEY"', config)
        self.assertNotIn(KEY, config)

        # The specific failure that shipped: the key used as the base URL.
        for line in config.splitlines():
            if line.strip().startswith(("base_url", "model_catalog_url")):
                self.assertNotIn(KEY, line, "API key reached a URL: %s" % line)

        # The key belongs on the wire as a bearer header, not in the request
        # target (a key-as-URL produces a request for "<key>/models").
        self.assertEqual(
            [request["authorization"] for request in self.server.requests],
            ["Bearer " + KEY, "Bearer " + ASTRA_KEY],
        )
        self.assertTrue(all(request["path"] == "/v1/models" for request in self.server.requests))

        # The padded key was trimmed before it reached disk.
        key_file = (self.home / ".xingchi" / "upstream.key").read_text(encoding="utf-8")
        self.assertEqual(key_file, KEY + "\n")
        astra_file = (self.home / ".xingchi" / "astra.key").read_text(encoding="utf-8")
        self.assertEqual(astra_file, ASTRA_KEY + "\n")

    def test_installs_reasoning_catalog_with_all_levels(self):
        self.install()
        codex_home = self.home / ".codex"
        config = (codex_home / "config.toml").read_text(encoding="utf-8")
        catalog_path = codex_home / "xingchi-models.json"
        self.assertIn("model_catalog_json = " + json.dumps(str(catalog_path), ensure_ascii=False), config)
        self.assertNotIn("model_reasoning_effort", config)
        settings = tomllib.loads(config)
        self.assertNotIn("XingchiAstra", settings["model_providers"])
        self.assertEqual(settings["model_providers"]["OpenAI"]["capabilities"]["remote_compaction"], "unsupported")
        self.assertEqual(settings["features"], {
            "api_key_model_discovery": True, "image_generation": True, "goals": True,
        })
        models = json.loads(catalog_path.read_text(encoding="utf-8"))["models"]
        self.assertEqual([model["slug"] for model in models], ["gpt-6.1-sol"])
        astra_catalog = json.loads((codex_home / "xingchi-models-astra.json").read_text(encoding="utf-8"))["models"]
        self.assertEqual([model["slug"] for model in astra_catalog], [
            *json.loads((ROOT / "lib/model-groups.json").read_text(encoding="utf-8"))["astra"],
        ])
        astra_reasoning = next(model for model in astra_catalog if model["slug"] == "gpt-6-astra")
        self.assertEqual(
            [level["effort"] for level in astra_reasoning["supported_reasoning_levels"]],
            ["low", "medium", "high", "xhigh", "max", "ultra"],
        )
        self.assertEqual(
            [level["effort"] for level in models[0]["supported_reasoning_levels"]],
            ["low", "medium", "high", "xhigh", "max", "ultra"],
        )

    def test_launchers_do_not_contain_the_key(self):
        self.install()

        launcher = (self.home / "bin" / "xingchi-codex.cmd").read_text(encoding="utf-8")
        status = (self.home / "bin" / "xingchi.cmd").read_text(encoding="utf-8")

        self.assertIn('set "XINGCHI_UPSTREAM=%s"' % self.base_url, launcher)
        self.assertIn("upstream.key", launcher)
        self.assertIn("XINGCHI_RUNNER", launcher)
        self.assertIn("xingchi-codex-runner.py", launcher)
        self.assertIn(self.base_url, status)

        for name, text in (("xingchi-codex.cmd", launcher), ("xingchi.cmd", status)):
            self.assertNotIn(KEY, text, "the API key leaked into %s" % name)
            self.assertNotIn(ASTRA_KEY, text, "the Astra key leaked into %s" % name)

    def test_launcher_forwards_model_effort_and_exit_code(self):
        self.install()
        launcher = self.home / "bin/xingchi-codex.cmd"
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(launcher), "-m", "gpt-6-luna",
             "-c", "model_reasoning_effort=max", "-a", "on-request", "-s",
             "read-only", "--approve-for-me", "--search"],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        forwarded = (self.home / "args.txt").read_text().strip()
        self.assertEqual(
            forwarded,
            "--no-daemon -m gpt-6-luna -c model_reasoning_effort=max "
            "-a on-request -s read-only --approve-for-me --search",
        )
        self.assertEqual((self.home / "selected-key.txt").read_text().strip(), KEY)

    def test_launcher_astra_flag_selects_astra_key_and_default_model(self):
        self.install()
        launcher = self.home / "bin" / "xingchi-codex.cmd"
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(launcher), "--astra", "--search"],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        forwarded = (self.home / "args.txt").read_text().strip()
        self.assertIn("model_catalog_json", forwarded)
        self.assertIn("xingchi-models-astra.json", forwarded)
        self.assertIn("-m gpt-6-astra", forwarded)
        self.assertIn("--search", forwarded)
        self.assertEqual((self.home / "selected-key.txt").read_text().strip(), ASTRA_KEY)

    def test_reinstall_preserves_model_and_effort(self):
        self.install()
        path = self.home / ".codex/config.toml"
        (self.home / ".xingchi/models.txt").write_text("sol:gpt-6.1-terra\n", encoding="utf-8")
        text = path.read_text(encoding="utf-8").replace('model = "gpt-6.1-sol"', 'model = "gpt-6.1-terra"')
        path.write_text('model_reasoning_effort = "ultra"\n' + text, encoding="utf-8")
        self._result = None
        self.install()
        settings = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(settings["model"], "gpt-6.1-terra")
        self.assertEqual(settings["model_reasoning_effort"], "ultra")
        self.assertEqual(settings["model_providers"]["OpenAI"]["capabilities"]["remote_compaction"], "unsupported")


if __name__ == "__main__":
    unittest.main()
