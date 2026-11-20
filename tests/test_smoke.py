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
ASTRA_KEY = "smoke-astra-key-456"
UPSTREAM_MODELS = ["gpt-6.1-sol"]
ASTRA_MODELS = [
    "gpt-5.6-sol", "gpt-6", "gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna",
    "gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-6-astra", "gpt-5.5",
    "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark", "codex-auto-review",
    "gpt-5.2", "gpt-image-1", "gpt-image-1.5", "gpt-image-2",
    "gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2.6-flare",
    "gpt-image-2.6-sunburst",
]
KNOWN_REASONING_MODELS = {"gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-6-terra", "gpt-6.1-terra"}


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
            authorization = self.server.requests[-1]["headers"].get("authorization")
            models = self.server.astra_model_ids if authorization == f"Bearer {ASTRA_KEY}" else self.server.model_ids
            payload = json.dumps({"data": [{"id": model} for model in models]}).encode()
            self.send_response(200)
        elif (self.command == "POST" and self.path == "/v1/responses"
              and getattr(self.server, "complete_responses", False)
              and not any(item.get("type") == "compaction_trigger"
                          for item in json.loads(self.server.requests[-1]["body"])["input"])):
            body = json.loads(self.server.requests[-1]["body"])
            compacting = not body.get("tools")
            message = {
                "id": "msg_smoke", "type": "message", "role": "assistant", "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Smoke summary." if compacting else "Smoke reply."}],
            }
            # A large reported usage makes the next turn need automatic compaction.
            input_tokens = 100 if compacting else 60000
            events = [
                {"type": "response.created", "response": {"id": "resp_smoke", "status": "in_progress", "output": []}},
                {"type": "response.output_item.done", "output_index": 0, "item": message},
                {"type": "response.completed", "response": {
                    "id": "resp_smoke", "status": "completed", "output": [message],
                    "usage": {"input_tokens": input_tokens, "output_tokens": 10, "total_tokens": input_tokens + 10},
                }},
            ]
            payload = "".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
                              for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
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
        self.server.astra_model_ids = list(ASTRA_MODELS)
        self.server.daemon_threads = True
        port = self.server.server_address[1]
        self.upstream = f"http://127.0.0.1:{port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        key_file = self.home / ".xingchi" / "upstream.key"
        key_file.write_text(KEY + "\n")
        key_file.chmod(0o600)
        astra_key_file = self.home / ".xingchi" / "astra.key"
        astra_key_file.write_text(ASTRA_KEY + "\n")
        astra_key_file.chmod(0o600)

        # The launcher, not the environment, must supply the key.
        self.env = {
            "HOME": str(self.home),
            "PATH": os.environ["PATH"],
            "TERM": "dumb",
            "CODEX_HOME": str(self.home / ".codex"),
            "XINGCHI_HOME": str(self.home / ".xingchi"),
            "XINGCHI_UPSTREAM": self.upstream,
            "XINGCHI_API_KEY": KEY,
            "XINGCHI_ASTRA_API_KEY": ASTRA_KEY,
        }
    def configure(self):
        configured = subprocess.run(
            [sys.executable, str(ROOT / "lib/config.py"), "codex"],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(configured.returncode, 0, configured.stderr)

    def test_codex_debug_catalog_is_scoped_to_selected_key_group(self):
        (self.home / ".xingchi" / "models.txt").write_text("# extra models\ngpt-6.2-astra\ngpt-6.1-sol\n")
        self.configure()
        sol_result = subprocess.run(
            ["codex", "debug", "models"], env=self.env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(sol_result.returncode, 0, sol_result.stderr)
        sol_models = json.loads(sol_result.stdout)["models"]
        self.assertEqual({model["slug"] for model in sol_models}, set(UPSTREAM_MODELS))

        astra_result = subprocess.run(
            ["sh", str(ROOT / "bin/xingchi-codex"), "--astra", "debug", "models"],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(astra_result.returncode, 0, astra_result.stderr)
        models = json.loads(astra_result.stdout)["models"]
        self.assertEqual({model["slug"] for model in models}, set(ASTRA_MODELS))
        self.assertIn("codex-auto-review", {model["slug"] for model in models})
        self.assertIn("gpt-image-2.6-sunburst", {model["slug"] for model in models})
        self.assertNotIn("gpt-6.2-astra", {model["slug"] for model in models})
        self.assertEqual(self.server.requests[0]["path"], "/v1/models")
        self.assertEqual(self.server.requests[0]["headers"].get("authorization"), f"Bearer {KEY}")
        self.assertEqual(self.server.requests[1]["headers"].get("authorization"), f"Bearer {ASTRA_KEY}")
        self.assertFalse((self.home / ".xingchi/model-routes.json").exists())
        for model in models:
            with self.subTest(model=model["slug"]):
                self.assertEqual(model["visibility"], "list")
                self.assertTrue(model["supported_in_api"])
                if model["slug"] in KNOWN_REASONING_MODELS:
                    expected = ["low", "medium", "high", "xhigh", "max"]
                    if model["slug"] != "gpt-6-luna":
                        expected.append("ultra")
                    self.assertEqual([level["effort"] for level in model["supported_reasoning_levels"]], expected)
                else:
                    self.assertEqual(model["supported_reasoning_levels"], [])

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

    def test_astra_flag_selects_astra_key_and_defaults_to_astra_model(self):
        self.configure()
        cases = (
            # With no model option, --astra must not start on the Sol default.
            (["--astra", "exec", "--ephemeral", "--skip-git-repo-check", "say hi"],
             ASTRA_KEY, "gpt-6-astra"),
            # The chosen key remains Astra even if a caller explicitly selects
            # a model also advertised by Sol; there is no model-based routing.
            (["--astra", "exec", "--ephemeral", "--skip-git-repo-check", "-m",
              "gpt-6.1-sol", "say hi"], ASTRA_KEY, "gpt-6.1-sol"),
            (["exec", "--ephemeral", "--skip-git-repo-check", "say hi"],
             KEY, "gpt-6.1-sol"),
        )
        for args, expected_key, expected_model in cases:
            with self.subTest(model=expected_model):
                self.server.requests.clear()
                result = subprocess.run(
                    ["sh", str(ROOT / "bin/xingchi-codex"), *args],
                    env=self.env, capture_output=True, text=True, timeout=30,
                )
                posts = [request for request in self.server.requests
                         if request["method"] == "POST" and request["path"] == "/v1/responses"]
                self.assertTrue(posts, result.stderr + result.stdout)
                self.assertEqual(posts[0]["headers"].get("authorization"), f"Bearer {expected_key}")
                self.assertEqual(json.loads(posts[0]["body"])["model"], expected_model)

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

    def test_resumed_session_compacts_with_regular_responses(self):
        self.configure()
        self.server.complete_responses = True
        path = self.home / ".codex/config.toml"
        path.write_text('model_auto_compact_token_limit = 50000\n' + path.read_text(encoding="utf-8"), encoding="utf-8")
        launcher = ["sh", str(ROOT / "bin/xingchi-codex"), "exec"]
        first = subprocess.run(
            [*launcher, "--skip-git-repo-check", "--json", "Say hello."],
            env=self.env, cwd=self.home, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        events = [json.loads(line) for line in first.stdout.splitlines() if line.startswith("{")]
        thread_id = next(event["thread_id"] for event in events if event.get("type") == "thread.started")
        self.server.requests.clear()

        resumed = subprocess.run(
            [*launcher, "resume", "--skip-git-repo-check", "--json", thread_id, "Continue the conversation."],
            env=self.env, cwd=self.home, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        posts = [r for r in self.server.requests if r["method"] == "POST"]
        bodies = [json.loads(r["body"]) for r in posts]
        self.assertGreaterEqual(len(bodies), 2, "Expected a compaction request followed by a normal reply")
        self.assertTrue(all(r["path"] == "/v1/responses" for r in posts))
        self.assertFalse(bodies[0].get("tools"), "The first request should summarize history")
        self.assertTrue(bodies[-1].get("tools"), "The resumed conversation should continue after compaction")
        self.assertFalse(any(item.get("type") == "compaction_trigger" for body in bodies for item in body["input"]))
        self.assertTrue(any("Smoke summary." in json.dumps(item) for item in bodies[-1]["input"]))

    def test_codex_sends_selected_model_and_reasoning_effort(self):
        self.configure()
        catalogs = [
            ("sol", self.home / ".codex/xingchi-models.json", []),
            ("astra", self.home / ".codex/xingchi-models-astra.json", ["--astra"]),
        ]
        for group, catalog_path, group_args in catalogs:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))["models"]
            for entry in catalog:
                model = entry["slug"]
                for level in entry["supported_reasoning_levels"]:
                    effort = level["effort"]
                    with self.subTest(group=group, model=model, effort=effort):
                        self.server.requests.clear()
                        result = subprocess.run(
                            ["sh", str(ROOT / "bin/xingchi-codex"), *group_args, "exec", "--ephemeral",
                             "--skip-git-repo-check", "-m", model,
                             "-c", f'model_reasoning_effort="{effort}"', "say hi"],
                            env=self.env, capture_output=True, text=True, timeout=30,
                        )
                        posts = [r for r in self.server.requests if r["path"] == "/v1/responses"]
                        self.assertTrue(posts, result.stderr)
                        body = json.loads(posts[0]["body"])
                        self.assertEqual(body["model"], model)
                        expected_key = ASTRA_KEY if group == "astra" else KEY
                        self.assertEqual(posts[0]["headers"].get("authorization"), f"Bearer {expected_key}")
                        expected_effort = "max" if effort == "ultra" else effort
                        self.assertEqual(body["reasoning"]["effort"], expected_effort)

    def test_fresh_installed_picker_is_sol_scoped_and_saves_effort(self):
        import fcntl
        import pty
        import termios

        self.server.model_ids = ["gpt-6.1-sol"]
        self.server.astra_model_ids = []
        installed = subprocess.run(
            ["sh", str(ROOT / "install.sh"), "--yes"],
            # This test exercises the real model picker. MCP startup has its
            # own integration coverage and optional uvx/npx cache writers can
            # otherwise race TemporaryDirectory cleanup on Python 3.14.
            env={**self.env, "XINGCHI_SKIP_INTEGRATIONS": "1"},
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
        pump(10, until="GPT-6.1 Sol on Xingchi")
        self.assertNotIn("GPT-6 Astra on Xingchi", clean_output())
        self.assertNotIn("GPT-6 Luna on Xingchi", clean_output())
        os.write(master, b"\r")
        pump(10, until="More reasoning")
        pump(0.2)
        down(4)
        os.write(master, b"\r")
        pump(10, until="2. Ultra")
        os.write(master, b"\r")

        def selection_saved():
            saved = tomllib.loads(config_path.read_text(encoding="utf-8"))
            return saved.get("model") == "gpt-6.1-sol" and saved.get("model_reasoning_effort") == "max"

        pump(10, condition=selection_saved)
        saved = tomllib.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["model"], "gpt-6.1-sol")
        self.assertEqual(saved["model_reasoning_effort"], "max")
        self.assertFalse(any(r["method"] == "POST" for r in self.server.requests))


if __name__ == "__main__":
    unittest.main()
