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
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer

ROOT = Path(__file__).resolve().parents[1]
KEY = "smoke-key-123"

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
        configured = subprocess.run(
            ["python3", str(ROOT / "lib/config.py"), "codex"],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(configured.returncode, 0, configured.stderr)

    def test_codex_sends_responses_request_with_key_and_model(self):
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


if __name__ == "__main__":
    unittest.main()
