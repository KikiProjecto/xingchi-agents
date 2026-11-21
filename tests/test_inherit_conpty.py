"""Exercise the Windows terminal transport on the native Windows CI runner."""

import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
import threading
from time import monotonic
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))


@unittest.skipUnless(os.name == "nt", "ConPTY is provided by Windows")
class ConPtyTests(unittest.TestCase):
    def test_child_receives_input_and_transports_output(self):
        from xingchi_conpty import WindowsChild

        child = WindowsChild([sys.executable, "-u", "-c",
                              "import sys;"
                              "print('TTY_'+str(all(s.isatty() for s in (sys.stdin,sys.stdout,sys.stderr))),flush=True);"
                              "print('CONPTY_STDERR',file=sys.stderr,flush=True);"
                              "print('CONPTY_READY',flush=True);print('REPLY_'+input(),flush=True)"],
                             dict(os.environ), Path.cwd(), os.terminal_size((100, 35)))
        self.addCleanup(child.close)
        output = Queue()

        def read():
            try:
                while data := child.read():
                    output.put(data)
            except OSError:
                pass
            finally:
                output.put(None)

        threading.Thread(target=read, daemon=True).start()
        content = b""

        def receive(marker):
            nonlocal content
            deadline = monotonic() + 10
            while marker not in content:
                try:
                    data = output.get(timeout=max(0, deadline - monotonic()))
                except Empty:
                    self.fail(f"Timed out waiting for {marker!r}; child exit={child.poll()}; output={content!r}")
                if data is None:
                    self.fail(f"ConPTY closed before {marker!r}; child exit={child.poll()}; output={content!r}")
                content += data

        receive(b"CONPTY_READY")
        self.assertIn(b"TTY_True", content, "The child must receive console streams")
        self.assertIn(b"CONPTY_STDERR", content, "Child stderr must also travel through ConPTY")
        child.resize(os.terminal_size((120, 40)))
        child.write(b"hello\r\n")
        receive(b"REPLY_hello")

    def test_redirected_parent_keeps_child_io_inside_pseudoconsole(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "ConPtyTests.test_child_receives_input_and_transports_output"],
            input=b"", capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode("utf-8", errors="replace"))
        for stream in (result.stdout, result.stderr):
            self.assertNotIn(b"CONPTY_READY", stream, "Child stdout leaked into its parent's redirected stream")
            self.assertNotIn(b"CONPTY_STDERR", stream, "Child stderr leaked into its parent's redirected stream")


if __name__ == "__main__":
    unittest.main()
