"""End-to-end smoke test: the real Codex CLI against a fake upstream.

The launcher reads ~/.xingchi/upstream.key, lib/config.py points Codex at the
given base URL, and Codex sends a Responses request. We capture that request and
check the two things that decide whether a user can actually talk to Xingchi:
the bearer key and the model name.

Everything runs against 127.0.0.1 with an isolated HOME/CODEX_HOME, so no real
credit is spent and the user's own Codex config is never read or written.
"""

import json
import os
from pathlib import Path
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer

ROOT = Path(__file__).resolve().parents[1]
KEY = "smoke-key-123"
PICKER_MODELS = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-6-terra"]
UPSTREAM_MODELS = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6.1-terra", "gpt-6-luna", "gpt-5-test", "text-embedding-3-large"]


def _stop_tui(process, master):
    """Exit through the TUI; limit fallback signals to the process we own."""
    terminal_closed = False
    try:
        try:
            os.write(master, b"/quit\r")
        except OSError:
            pass  # The TUI may already have exited after a failed assertion.
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass

        # Closing the PTY also disconnects a native CLI launched by the Node
        # wrapper. macOS may reject signals to its entire process group.
        os.close(master)
        terminal_closed = True
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    finally:
        if not terminal_closed:
            os.close(master)


class TuiCleanupTests(unittest.TestCase):
    def test_graceful_exit_closes_terminal_without_process_group_signals(self):
        process = Mock()
        with patch.object(os, "write") as write, patch.object(os, "close") as close, \
                patch.object(os, "killpg", create=True) as kill_group:
            _stop_tui(process, 42)
        write.assert_called_once_with(42, b"/quit\r")
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        kill_group.assert_not_called()
        close.assert_called_once_with(42)

    def test_timeout_terminates_only_owned_process_when_group_signals_are_denied(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired(["codex"], 3), 0]
        with patch.object(os, "write"), patch.object(os, "close") as close, \
                patch.object(os, "killpg", side_effect=[None, PermissionError(1, "Operation not permitted")], create=True) as kill_group:
            _stop_tui(process, 42)
        process.terminate.assert_called_once_with()
        process.kill.assert_not_called()
        kill_group.assert_not_called()
        close.assert_called_once_with(42)

    def test_unresponsive_process_uses_bounded_direct_kill(self):
        process = Mock()
        timeout = subprocess.TimeoutExpired(["codex"], 3)
        process.wait.side_effect = [timeout, timeout, 0]
        with patch.object(os, "write"), patch.object(os, "close") as close, \
                patch.object(os, "killpg", create=True) as kill_group:
            _stop_tui(process, 42)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        kill_group.assert_not_called()
        close.assert_called_once_with(42)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read_body(self):
        # Codex streams the request body with chunked transfer encoding.
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            parts = []
            while True:
                line = self.rfile.readline().strip()
                size = int(line.split(b";")[0], 16)
                if size == 0:
                    self.rfile.readline()
                    break
                parts.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(parts)
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _record(self):
        self.server.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": self._read_body(),
            }
        )
        if self.command == "GET" and self.path.split("?")[0] == "/v1/models":
            payload = json.dumps({"data": [{"id": model} for model in self.server.model_ids]}).encode()
            self.send_response(200)
        else:
            # Fail fast: we only care about what Codex sent.
            payload = b'{"error":{"message":"smoke","type":"invalid_request_error"}}'
            self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _record
    do_POST = _record

    def log_message(self, *args):
        pass


@unittest.skipIf(os.name == "nt", "the Windows installer has native Windows tests")
@unittest.skipUnless(shutil.which("codex"), "codex CLI is not installed")
class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        (self.home / ".xingchi").mkdir()
        (self.home / ".codex").mkdir()

        self.server = TCPServer(("127.0.0.1", 0), _Handler)
        self.server.requests = []
        self.server.model_ids = list(UPSTREAM_MODELS)
        self.server.daemon_threads = True
        port = self.server.server_address[1]
        self.upstream = f"http://127.0.0.1:{port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        key_file = self.home / ".xingchi" / "upstream.key"
        key_file.write_text(KEY + "\n")
        key_file.chmod(0o600)

        # The launcher, not the environment, must supply the key.
        self.env = {
            "HOME": str(self.home),
            "PATH": os.environ["PATH"],
            "TERM": "dumb",
            "CODEX_HOME": str(self.home / ".codex"),
            "XINGCHI_HOME": str(self.home / ".xingchi"),
            "XINGCHI_UPSTREAM": self.upstream,
            "XINGCHI_API_KEY": KEY,
        }
    def configure(self):
        configured = subprocess.run(
            [sys.executable, str(ROOT / "lib/config.py"), "codex"],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(configured.returncode, 0, configured.stderr)

    def test_codex_debug_catalog_lists_upstream_and_local_models_with_reasoning(self):
        (self.home / ".xingchi" / "models.txt").write_text("# extra models\ngpt-6.2-astra\ngpt-6.1-sol\n")
        self.configure()
        result = subprocess.run(
            ["codex", "debug", "models"], env=self.env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        models = json.loads(result.stdout)["models"]
        self.assertEqual([model["slug"] for model in models],
                         PICKER_MODELS + ["gpt-6.1-terra", "gpt-5-test", "gpt-6.2-astra"])
        self.assertEqual(self.server.requests[0]["path"], "/v1/models")
        self.assertEqual(self.server.requests[0]["headers"].get("authorization"), f"Bearer {KEY}")
        for model in models[:4]:
            with self.subTest(model=model["slug"]):
                self.assertEqual(model["visibility"], "list")
                self.assertTrue(model["supported_in_api"])
                expected = ["low", "medium", "high", "xhigh", "max"]
                if model["slug"] != "gpt-6-luna":
                    expected.append("ultra")
                self.assertEqual(
                    [level["effort"] for level in model["supported_reasoning_levels"]],
                    expected,
                )

    def test_codex_sends_responses_request_with_key_and_model(self):
        self.configure()
        result = subprocess.run(
            ["sh", str(ROOT / "bin/xingchi-codex"), "exec",
             "--skip-git-repo-check", "say hi"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        posts = [r for r in self.server.requests if r["method"] == "POST"]
        self.assertTrue(
            posts,
            "Codex never reached the fake upstream.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        request = posts[0]
        self.assertEqual(request["path"], "/v1/responses")
        self.assertEqual(
            request["headers"].get("authorization"),
            f"Bearer {KEY}",
            "the request did not carry the key from upstream.key",
        )

        body = json.loads(request["body"])
        self.assertEqual(body["model"], "gpt-6.1-sol")
        self.assertTrue(body["stream"], "Codex must ask for a streaming response")
        self.assertIn("input", body, "the request carried no prompt input")

    def test_launcher_fails_before_network_when_key_is_missing(self):
        (self.home / ".xingchi" / "upstream.key").unlink()
        result = subprocess.run(
            ["sh", str(ROOT / "bin/xingchi-codex"), "exec", "say hi"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("API key missing", result.stderr)
        self.assertEqual(self.server.requests, [])

    def test_codex_sends_selected_model_and_reasoning_effort(self):
        self.configure()
        catalog = json.loads((ROOT / "lib/models.json").read_text(encoding="utf-8"))["models"]
        for entry in catalog:
            model = entry["slug"]
            for level in entry["supported_reasoning_levels"]:
                effort = level["effort"]
                with self.subTest(model=model, effort=effort):
                    self.server.requests.clear()
                    result = subprocess.run(
                        ["sh", str(ROOT / "bin/xingchi-codex"), "exec", "--ephemeral",
                         "--skip-git-repo-check", "-m", model,
                         "-c", f'model_reasoning_effort="{effort}"', "say hi"],
                        env=self.env, capture_output=True, text=True, timeout=30,
                    )
                    posts = [r for r in self.server.requests if r["path"] == "/v1/responses"]
                    self.assertTrue(posts, result.stderr)
                    body = json.loads(posts[0]["body"])
                    self.assertEqual(body["model"], model)
                    # Ultra is a client preset; Codex 0.170.0 sends Max on
                    # the wire while retaining Ultra as the selected preset.
                    expected_effort = "max" if effort == "ultra" else effort
                    self.assertEqual(body["reasoning"]["effort"], expected_effort)

    def test_fresh_installed_picker_has_four_models_and_saves_luna_max(self):
        import fcntl
        import pty
        import termios

        self.server.model_ids = ["gpt-6.1-sol"]
        installed = subprocess.run(
            ["sh", str(ROOT / "install.sh"), "--yes"], env=self.env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(installed.returncode, 0, installed.stderr + installed.stdout)
        config_path = self.home / ".codex/config.toml"
        with config_path.open("a", encoding="utf-8") as config_file:
            config_file.write('\n[projects.' + json.dumps(str(self.home)) + ']\ntrust_level = "trusted"\n')
        launcher = self.home / ".local/bin/xingchi-codex"
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
        process = subprocess.Popen(
            [str(launcher), "--no-alt-screen"], cwd=self.home,
            env={**self.env, "TERM": "xterm-256color"},
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        )
        os.close(slave)

        self.addCleanup(_stop_tui, process, master)
        output = bytearray()

        def clean_output():
            text = output.decode("utf-8", errors="replace")
            text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
            return re.sub(r"\x1b\].*?(?:\x07|\x1b\\)", "", text, flags=re.DOTALL)

        def pump(seconds, until=None, condition=None):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                    if b"\x1b[6n" in chunk:
                        os.write(master, b"\x1b[1;1R")
                    if b"\x1b[c" in chunk:
                        os.write(master, b"\x1b[?1;2c")
                if until and until in clean_output():
                    return
                if condition and condition():
                    return
            if until:
                self.fail(f"TUI never showed {until!r}:\n{clean_output()[-8000:]}")
            if condition:
                self.fail(f"TUI never saved the expected selection:\n{clean_output()[-8000:]}")

        def down(count):
            for _ in range(count):
                os.write(master, b"\x1b[B")
                pump(0.1)

        pump(15, until="GPT-6.1 Sol")
        os.write(master, b"/model")
        pump(0.2)
        os.write(master, b"\r")
        pump(10, until="GPT-6 Terra on Xingchi")
        for label in ("GPT-6.1 Sol", "GPT-6 Astra", "GPT-6 Luna", "GPT-6 Terra"):
            self.assertIn(label, clean_output())
        down(2)
        os.write(master, b"\r")
        pump(10, until="More reasoning")
        pump(0.2)
        down(3)
        os.write(master, b"\r")
        pump(0.5)
        os.write(master, b"\r")

        def selection_saved():
            saved = tomllib.loads(config_path.read_text(encoding="utf-8"))
            return saved.get("model") == "gpt-6-luna" and saved.get("model_reasoning_effort") == "max"

        pump(10, condition=selection_saved)
        saved = tomllib.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["model"], "gpt-6-luna")
        self.assertEqual(saved["model_reasoning_effort"], "max")
        self.assertFalse(any(r["method"] == "POST" for r in self.server.requests))


if __name__ == "__main__":
    unittest.main()
