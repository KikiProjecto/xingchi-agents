"""Exercise the Windows terminal transport on the native Windows CI runner."""

import os
from pathlib import Path
from queue import Queue
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))


@unittest.skipUnless(os.name == "nt", "ConPTY is provided by Windows")
class ConPtyTests(unittest.TestCase):
    def test_child_receives_input_and_transports_output(self):
        from xingchi_conpty import WindowsChild

        child = WindowsChild([sys.executable, "-u", "-c",
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

        threading.Thread(target=read, daemon=True).start()
        content = b""
        while b"CONPTY_READY" not in content:
            content += output.get(timeout=10)
        child.resize(os.terminal_size((120, 40)))
        child.write(b"hello\r\n")
        while b"REPLY_hello" not in content:
            content += output.get(timeout=10)
        self.assertIn(b"REPLY_hello", content)
