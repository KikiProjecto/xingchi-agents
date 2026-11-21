"""Terminal-side commands that must work even when a model session is capped."""

from __future__ import annotations

import codecs
from datetime import datetime
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import signal
import subprocess
import sys
from threading import Thread
from time import monotonic
import unicodedata

from xingchi_history import label, list_threads, select_thread


CSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
INHERIT = b"/inherit"
VALUE_OPTIONS = {"-c", "--config", "--enable", "--disable", "--remote", "--remote-auth-token-env",
                 "-i", "--image", "-m", "--model", "--local-provider", "-p", "--profile",
                 "-s", "--sandbox", "-a", "--ask-for-approval", "-C", "--cd", "--add-dir"}
LOCAL_OPTIONS = {"--last", "--all"}
TERMINAL_REPORT = re.compile(rb"\x1b\[(?:[0-9;]*[Rc]|[?=>][0-9;]*c|\?[0-9;]*u|\??[0-9;]*\$y|[0-9;]*t|[IO])$")


def terminal_report(key):
    return key.startswith((b"\x1b]", b"\x1bP", b"\x1b_", b"\x1b^", b"\x1bX")) or bool(TERMINAL_REPORT.fullmatch(key))


def logical_key(key):
    """Recognize keys from terminals using Codex's enhanced keyboard mode."""
    match = re.fullmatch(rb"\x1b\[(\d+)(?::(\d+)(?::\d+)?)?(?:;(\d+)(?::(\d+))?)?u", key)
    if not match:
        match = re.fullmatch(rb"\x1b\[1;1(?::(\d+))?([ABCDHF])", key)
        return (None if match[1] == b"3" else b"\x1b[" + match[2]) if match else key
    code, shifted = int(match[1]), int(match[2] or 0)
    modifiers, event = int(match[3] or 1), int(match[4] or 1)
    if event == 3:
        return None  # Key release is not another character.
    if modifiers == 5 and 65 <= code <= 122:
        return bytes([code & 31])
    if modifiers not in {1, 2}:
        return key
    if modifiers == 2 and shifted:
        code = shifted
    functional = {57348: b"\x1b[2~", 57349: b"\x1b[3~", 57350: b"\x1b[D", 57351: b"\x1b[C",
                  57352: b"\x1b[A", 57353: b"\x1b[B", 57354: b"\x1b[5~", 57355: b"\x1b[6~",
                  57356: b"\x1b[H", 57357: b"\x1b[F"}
    if code in functional:
        return functional[code]
    if code in {9, 13, 27, 127}:
        return bytes([code]) if modifiers == 1 else key
    if 32 <= code <= 0x10FFFF and chr(code).isprintable():
        return chr(code).encode("utf-8")
    return key


def interactive_options(args: list[str]) -> list[str] | None:
    """Keep launch settings, but never replay a resume, fork, or old prompt."""
    result = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"--help", "-h", "--version", "-V"}:
            return None
        if arg == "--":
            break
        if arg in {"resume", "fork", "agents"}:
            index += 1
            continue
        if arg in LOCAL_OPTIONS:
            index += 1
            continue
        if arg in VALUE_OPTIONS and index + 1 < len(args):
            result.extend(args[index:index + 2])
            index += 2
            continue
        if arg.startswith("-"):
            result.append(arg)
        elif arg in {"exec", "e", "review", "login", "logout", "mcp", "plugin",
                                            "app-server", "debug", "features", "doctor", "help",
                                            "completion", "update", "sandbox", "queue", "archive",
                                            "unarchive", "delete", "apply", "a", "cloud", "exec-server",
                                            "migrate-rollouts", "migrate-nfs-db", "remote-control"}:
            return None
        index += 1
    return result


def launch_directory(args: list[str]) -> Path:
    cwd = Path.cwd()
    for index, arg in enumerate(args):
        if arg in {"--", "resume", "fork", "agents"}:
            break
        if arg in {"-C", "--cd"} and index + 1 < len(args):
            cwd = Path(args[index + 1]).expanduser()
        elif arg.startswith("--cd="):
            cwd = Path(arg[5:]).expanduser()
    return cwd.resolve()


class InputKeys:
    """Keep terminal reports, escape sequences and pasted text intact."""

    def __init__(self):
        self.pending = b""
        self.escape_since = 0.0

    def feed(self, data: bytes) -> list[bytes]:
        self.pending += data
        keys = []
        while self.pending:
            text = self.pending
            if text.startswith(b"\x1b[200~"):
                end = text.find(b"\x1b[201~")
                if end == -1:
                    break
                length = end + 6
            elif text.startswith((b"\x1b]", b"\x1bP", b"\x1b_", b"\x1b^", b"\x1bX")):
                ends = [(text.find(b"\x1b\\"), 2)]
                if text.startswith(b"\x1b]"):
                    ends.append((text.find(b"\x07"), 1))
                ends = [(end, length) for end, length in ends if end >= 0]
                if not ends:
                    break
                end, terminator_length = min(ends)
                length = end + terminator_length
            elif text.startswith(b"\x1b["):
                match = CSI.match(text)
                if not match:
                    break
                length = match.end()
            elif text.startswith(b"\x1bO"):
                if len(text) < 3:
                    break
                length = 3
            elif text.startswith(b"\x1b"):
                if len(text) < 2:
                    self.escape_since = monotonic()
                    break
                length = 2
            elif text[0] >= 0xC0:
                length = 2 if text[0] < 0xE0 else 3 if text[0] < 0xF0 else 4
                if len(text) < length:
                    break
            else:
                length = 1
            keys.append(text[:length])
            self.pending = text[length:]
        return keys

    def escape(self) -> list[bytes]:
        if self.pending == b"\x1b" and monotonic() - self.escape_since > 0.04:
            self.pending = b""
            return [b"\x1b"]
        return []


class SlashInput:
    """Add one selectable command while leaving Codex's other commands intact."""

    def __init__(self):
        self.candidate = b""
        self.empty = True
        self.length = 0
        self.inherit_selected = True

    def feed(self, key: bytes, *, native_available=False, native_first=False) -> tuple[bytes, str | None]:
        # The terminal can reply to a cursor/device query while a command is
        # being typed. These replies are for Codex, not the extension composer.
        if terminal_report(key):
            return key, None
        logical = logical_key(key)
        if logical != key:
            if logical is None:
                return key, None
            forwarded, selector = self.feed(logical, native_available=native_available, native_first=native_first)
            return (key if forwarded == logical else forwarded), selector
        if self.empty and not self.candidate and key.startswith(b"\x1b[200~"):
            pasted = key[6:-6]
            if (pasted and (INHERIT.startswith(pasted) or pasted.startswith(INHERIT + b" "))
                    and b"\n" not in pasted and b"\r" not in pasted):
                self.candidate = pasted
                self.inherit_selected = True
                return key, None
        if self.candidate:
            if key in {b"\x1b[A", b"\x1bOA", b"\x1b[B", b"\x1bOB"}:
                up = key in {b"\x1b[A", b"\x1bOA"}
                if self.inherit_selected:
                    if native_available:
                        self.inherit_selected = False
                        return key if up else b"", None
                    return b"", None
                if up and native_first:
                    self.inherit_selected = True
                    return b"", None
                return key, None
            if key in {b"\r", b"\n", b"\t"}:
                selector = None
                if self.inherit_selected:
                    selector = self.candidate[len(INHERIT):].decode("utf-8", errors="replace").strip()
                self.candidate = b""
                self.empty = key in {b"\r", b"\n"}
                self.length = 0 if self.empty else None
                # Clear the real composer before opening the local picker. No
                # Enter, prompt expansion, or model request reaches Codex.
                return (b"\x15", selector) if selector is not None else (key, None)
            if key in {b"\x7f", b"\b"}:
                self.candidate = self.candidate.decode("utf-8", errors="replace")[:-1].encode("utf-8")
                self.inherit_selected = True
                if not self.candidate:
                    self.empty = True
                    self.length = 0
                return key, None
            if key in {b"\x1b", b"\x03", b"\x15"}:
                self.candidate, self.empty = b"", True
                self.length = 0
                return b"\x15", None
            proposed = self.candidate + key
            if (not key.startswith(b"\x1b") and key.decode("utf-8", errors="replace").isprintable()
                    and (INHERIT.startswith(proposed) or proposed.startswith(INHERIT + b" "))):
                self.candidate = proposed
                self.inherit_selected = True
                return key, None
            self.candidate = b""
            self.empty = False
            self.length = len(proposed) if len(key) == 1 else None
            return key, None
        if self.empty and key == b"/":
            self.candidate = key
            self.inherit_selected = True
            return key, None
        if key in {b"\r", b"\n", b"\x03", b"\x15"}:
            self.empty = True
            self.length = 0
        elif key in {b"\x7f", b"\b"}:
            self.length = max(0, self.length - 1) if self.length is not None else None
            self.empty = self.length == 0
        elif key == b"\x1b":
            # Closing a native picker does not type a character into the
            # composer, and must not disable the next slash command.
            return key, None
        elif not key.startswith(b"\x1b[") or key[-1:] not in {b"R", b"c"}:
            self.empty = False
            if not key.startswith(b"\x1b") and key.decode("utf-8", errors="replace").isprintable():
                self.length = self.length + 1 if self.length is not None else None
            else:
                self.length = None
        return key, None


class TerminalScreen:
    """Track Codex's visible cells so the extra row belongs to its popup.

    Only the native output updates this buffer. Extension rows are restored
    before the next native update, and are never drawn inside a split escape
    sequence or an unfinished synchronized frame.
    """

    command_row = re.compile(r"^\s*(?:›\s+)?/[\w:-]+\s{2,}\S")
    selected_row = re.compile(r"^\s*›\s+/[\w:-]+\s{2,}\S")
    sequence = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")

    def __init__(self, size):
        self.columns, self.rows = size.columns, size.lines
        self.cells = [[" "] * self.columns for _ in range(self.rows)]
        self.x = self.y = 0
        self.saved = (0, 0)
        self.top, self.bottom = 0, self.rows - 1
        self.pending = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.synchronized = False
        self.alternate = None
        self.viewport_clears = 0

    @property
    def ready(self):
        return not (self.pending or self.decoder.getstate()[0] or self.synchronized)

    def line(self, row):
        return "".join(self.cells[row]).rstrip()

    def resize(self, size):
        self.cells = [(row[:size.columns] + [" "] * max(0, size.columns - len(row)))
                      for row in self.cells[:size.lines]]
        self.cells.extend([[" "] * size.columns for _ in range(size.lines - len(self.cells))])
        self.columns, self.rows = size.columns, size.lines
        self.x, self.y = min(self.x, self.columns - 1), min(self.y, self.rows - 1)
        self.top, self.bottom = 0, self.rows - 1

    def scroll(self, count):
        count = max(-self.rows, min(self.rows, count))
        for _ in range(abs(count)):
            if count > 0:
                del self.cells[self.top]
                self.cells.insert(self.bottom, [" "] * self.columns)
            else:
                del self.cells[self.bottom]
                self.cells.insert(self.top, [" "] * self.columns)

    def index(self, reverse=False):
        if self.y == (self.top if reverse else self.bottom):
            self.scroll(-1 if reverse else 1)
        else:
            self.y = max(0, min(self.rows - 1, self.y + (-1 if reverse else 1)))

    def control(self, params, final):
        private = params.startswith("?")
        values = [int(p) if p.isdigit() else 0 for p in params.lstrip("?><=").split(";")]
        n = values[0] or 1
        if private and final in {"h", "l"}:
            if 2026 in values:
                self.synchronized = final == "h"
            if 1049 in values:
                if final == "h" and self.alternate is None:
                    self.alternate = (self.cells, self.x, self.y, self.top, self.bottom)
                    self.cells = [[" "] * self.columns for _ in range(self.rows)]
                    self.x = self.y = 0
                    self.top, self.bottom = 0, self.rows - 1
                elif final == "l" and self.alternate is not None:
                    self.cells, self.x, self.y, self.top, self.bottom = self.alternate
                    self.alternate = None
                    self.resize(os.terminal_size((self.columns, self.rows)))
        elif final in {"H", "f"}:
            self.y = min(self.rows - 1, n - 1)
            self.x = min(self.columns - 1, (values[1] or 1) - 1 if len(values) > 1 else 0)
        elif final in {"A", "B", "e"}:
            self.y = max(0, min(self.rows - 1, self.y + (-n if final == "A" else n)))
        elif final in {"C", "D", "a"}:
            self.x = max(0, min(self.columns - 1, self.x + (-n if final == "D" else n)))
        elif final in {"E", "F"}:
            self.x = 0
            self.y = max(0, min(self.rows - 1, self.y + (-n if final == "F" else n)))
        elif final in {"G", "`"}:
            self.x = min(self.columns - 1, n - 1)
        elif final == "d":
            self.y = min(self.rows - 1, n - 1)
        elif final in {"J", "K"}:
            mode = values[0]
            if final == "J":
                if mode == 2 or mode == 0 and self.x == 0:
                    self.viewport_clears += 1
                for row in range(self.rows):
                    if mode == 2 or mode == 0 and row > self.y or mode == 1 and row < self.y:
                        self.cells[row] = [" "] * self.columns
            if mode in {0, 1, 2}:
                start, end = (self.x, self.columns) if mode == 0 else (0, self.x + 1) if mode == 1 else (0, self.columns)
                self.cells[self.y][start:end] = [" "] * (end - start)
        elif final == "r":
            self.top = min(self.rows - 1, n - 1)
            self.bottom = min(self.rows - 1, (values[1] or self.rows) - 1 if len(values) > 1 else self.rows - 1)
            self.x = self.y = 0
        elif final in {"S", "T"}:
            self.scroll(n if final == "S" else -n)
        elif final in {"L", "M"} and self.top <= self.y <= self.bottom:
            top, self.top = self.top, self.y
            self.scroll(-n if final == "L" else n)
            self.top = top
        elif final in {"P", "@", "X"}:
            row, start = self.cells[self.y], min(self.x, self.columns - 1)
            n = min(n, self.columns - start)
            if final == "P":
                row[start:] = row[start + n:] + [" "] * n
            elif final == "@":
                row[start:] = [" "] * n + row[start:self.columns - n]
            else:
                row[start:start + n] = [" "] * n
        elif final == "s":
            self.saved = (self.x, self.y)
        elif final == "u" and not params:
            self.x, self.y = self.saved

    def feed(self, data):
        text = self.pending + self.decoder.decode(data)
        self.pending = ""
        i = 0
        while i < len(text):
            char = text[i]
            if char == "\x1b":
                if i + 1 == len(text):
                    break
                kind = text[i + 1]
                if kind == "[":
                    match = self.sequence.match(text, i)
                    if not match:
                        break
                    self.control(match[1], match[3])
                    i = match.end()
                    continue
                if kind in {"]", "P", "_", "^", "X"}:
                    ends = [(text.find("\x1b\\", i + 2), 2)]
                    if kind == "]":
                        ends.append((text.find("\x07", i + 2), 1))
                    ends = [(end, length) for end, length in ends if end >= 0]
                    if not ends:
                        break
                    end, length = min(ends)
                    i = end + length
                    continue
                if kind in {"(", ")", "*", "+", "#", "%"}:
                    if i + 2 == len(text):
                        break
                    i += 3
                    continue
                if kind == "7":
                    self.saved = (self.x, self.y)
                elif kind == "8":
                    self.x, self.y = self.saved
                elif kind in {"D", "M", "E"}:
                    self.index(kind == "M")
                    if kind == "E":
                        self.x = 0
                i += 2
                continue
            if char == "\r":
                self.x = 0
            elif char in {"\n", "\v", "\f"}:
                self.index()
            elif char == "\b":
                self.x = max(0, self.x - 1)
            elif char == "\t":
                self.x = min(self.columns - 1, (self.x // 8 + 1) * 8)
            elif char.isprintable():
                if self.x >= self.columns:
                    self.x = 0
                    self.index()
                width = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
                if width:
                    self.cells[self.y][self.x] = char
                    if width == 2 and self.x + 1 < self.columns:
                        self.cells[self.y][self.x + 1] = ""
                    self.x += width
                elif self.x:
                    self.cells[self.y][self.x - 1] += char
            i += 1
        self.pending = text[i:]

    def popup(self):
        """Return the native popup rows nearest the composer, if present."""
        selected = [row for row in range(self.y) if self.selected_row.match(self.line(row))]
        if not selected:
            return None
        chosen = selected[-1]
        start = chosen
        while start and self.line(start - 1).strip():
            start -= 1
        rows = [row for row in range(start, self.y) if self.command_row.match(self.line(row))]
        return (rows, chosen) if rows else None

    def empty_composer(self):
        text = self.line(self.y)
        prefix = re.match(r"^\s*› ", text)
        return bool(prefix and self.x == prefix.end()
                    and text[prefix.end():].strip() in {"", "Ask Codex to do anything"})

    def extension_rows(self, selected):
        popup = self.popup()
        first = popup[0][0] if popup else self.y - 1
        row = max(0, first - 1)
        # The native popup reserves a blank row above its entries. If a very
        # short terminal has none, use the separator above the composer.
        if self.line(row).strip():
            row = max(0, self.y - 1)
        text = ("› " if selected else "  ") + "/inherit       choose a saved session and start a fresh chat"
        changes = [(row, text, selected)]
        if popup and selected:
            chosen = popup[1]
            changes.append((chosen, self.line(chosen).replace("›", " ", 1), False))
        return changes

    def paint(self, changes, *, synchronize=True):
        result = "\x1b[?2026h" if synchronize else ""
        for row, text, selected in changes:
            result += f"\x1b[{row + 1};1H\x1b[0m\x1b[2K"
            result += ("\x1b[7m" if selected else "") + text[:self.columns - 1] + "\x1b[0m"
        result += f"\x1b[{self.y + 1};{min(self.x, self.columns - 1) + 1}H"
        return result + ("\x1b[?2026l" if synchronize else "")


class TerminalRenderer:
    """Commit the native frame and the extension row as one visible update."""

    sync_mode = re.compile(rb"\x1b\[\?2026[hl]")

    def __init__(self, size):
        self.screen = TerminalScreen(size)
        self.pending = bytearray()
        self.restore = b""
        self.signature = None
        self.resize_clear = None

    @classmethod
    def frame(cls, *parts):
        payload = b"".join(parts)
        if not payload:
            return b""
        # Synchronized output is a mode, not a nesting counter. Native frame
        # endings must not expose the restored popup before /inherit is added.
        return b"\x1b[?2026h" + cls.sync_mode.sub(b"", payload) + b"\x1b[?2026l"

    def resize(self, size):
        if (size.columns, size.lines) == (self.screen.columns, self.screen.rows):
            return
        self.screen.resize(size)
        self.cover()
        # Terminal reflow can move the visible overlay and cursor differently
        # from this cell buffer. Keep them untouched until Codex clears and
        # repaints at the new size; even its preceding cursor query must pass
        # through without restoring or adding a row at stale coordinates.
        self.resize_clear = self.screen.viewport_clears

    def extension(self, composer):
        changes = self.screen.extension_rows(composer.inherit_selected) if composer.candidate else []
        self.signature = (changes, self.screen.x, self.screen.y)
        original = [(row, self.screen.line(row), bool(self.screen.selected_row.match(self.screen.line(row))))
                    for row, _, _ in changes]
        # Capture the old native cursor as well as the old cells. The next
        # native frame may begin with a relative cursor movement.
        self.restore = self.screen.paint(original, synchronize=False).encode() if changes else b""
        return self.screen.paint(changes, synchronize=False).encode() if changes else b""

    def redraw(self, composer):
        if self.pending or not self.screen.ready or self.resize_clear is not None:
            return b""
        changes = self.screen.extension_rows(composer.inherit_selected) if composer.candidate else []
        if self.signature == (changes, self.screen.x, self.screen.y):
            return b""
        restore = self.restore
        return self.frame(restore, self.extension(composer))

    def feed(self, data, composer, *, visible=True):
        self.pending.extend(data)
        self.screen.feed(data)
        if not self.screen.ready:
            return b""
        native = bytes(self.pending)
        self.pending.clear()
        if not visible:
            self.cover()
            return b""
        if self.resize_clear is not None:
            if self.screen.viewport_clears == self.resize_clear:
                return self.frame(native)
            self.resize_clear = None
        restore = self.restore
        return self.frame(restore, native, self.extension(composer))

    def cover(self):
        self.restore = b""
        self.signature = None


class PosixChild:
    def __init__(self, command, env, cwd, size):
        import fcntl
        import pty
        import struct
        import termios

        self.master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", size.lines, size.columns, 0, 0))

            def terminal_session():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            self.process = subprocess.Popen(command, env=env, cwd=cwd, stdin=slave, stdout=slave,
                                            stderr=slave, preexec_fn=terminal_session)
        except BaseException:
            os.close(self.master)
            raise
        finally:
            os.close(slave)

    def read(self):
        return os.read(self.master, 65536)

    def write(self, data):
        while data:
            data = data[os.write(self.master, data):]

    def resize(self, size):
        import fcntl
        import struct
        import termios
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", size.lines, size.columns, 0, 0))

    def poll(self):
        return self.process.poll()

    def close(self):
        try:
            if self.poll() is None:
                try:
                    self.write(b"\x03/quit\r")
                except OSError:
                    pass  # The native child may have just closed its terminal.
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
        finally:
            os.close(self.master)
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)


class SessionMenu:
    def __init__(self, selector=""):
        self.sessions = None
        self.error = ""
        self.query = selector
        self.selected = 0

    def matches(self):
        query = self.query.casefold().strip().removeprefix("@")
        return [t for t in self.sessions or [] if query in " ".join(
            (t["id"], t.get("name") or "", t.get("preview") or "")).casefold()]

    def key(self, key, height):
        key = logical_key(key)
        if key is None:
            return None
        if key in {b"\x1b", b"\x03"}:
            return "cancel"
        matches = self.matches()
        step = {b"\x1b[A": -1, b"\x1bOA": -1, b"\x1b[B": 1, b"\x1bOB": 1,
                b"\x1b[5~": -height, b"\x1b[6~": height}.get(key)
        if step is not None:
            self.selected = max(0, min(len(matches) - 1, self.selected + step))
        elif key in {b"\r", b"\n"} and matches:
            return matches[self.selected]["id"]
        elif key in {b"\x7f", b"\b"}:
            self.query, self.selected = self.query[:-1], 0
        elif key == b"\x15":
            self.query, self.selected = "", 0
        elif key.startswith(b"\x1b[200~"):
            self.query += key[6:-6].decode("utf-8", errors="replace").replace("\n", " ")
            self.selected = 0
        elif not key.startswith(b"\x1b") and key.decode("utf-8", errors="replace").isprintable():
            self.query += key.decode("utf-8", errors="replace")
            self.selected = 0
        return None

    def render(self, size, cwd):
        width, height = max(20, size.columns - 4), max(1, size.lines - 9)
        lines = ["\x1b[1mInherit a saved session\x1b[0m", str(cwd),
                 "↑/↓ choose  ·  Enter inherit  ·  Esc cancel  ·  type to filter", "", f"Filter: {self.query}", ""]
        matches = self.matches()
        if self.sessions is None:
            lines.append("Loading sessions in this directory…")
        elif not matches:
            lines.append("No saved sessions match this directory and filter.")
        else:
            start = (self.selected // height) * height
            for index in range(start, min(start + height, len(matches))):
                thread = matches[index]
                updated = thread.get("updatedAt")
                date = datetime.fromtimestamp(updated).strftime("%m-%d %H:%M") if updated else ""
                title = label(thread)[38:]
                row = f'{date}  {thread["id"][:13]}  {title[:max(0, width - 29)]}'[:width]
                lines.append(("\x1b[7m› " + row + "\x1b[0m") if index == self.selected else "  " + row)
            lines.append(f"\x1b[2m{self.selected + 1}/{len(matches)} sessions\x1b[0m")
        if self.error:
            lines.append(self.error)
        return "\x1b[?25l\x1b[H\x1b[2J" + "\r\n".join(line[:width + 30] for line in lines)


def run_tui(command, env, cwd, history_request, fresh_command):
    """Relay the native terminal; handle /inherit without a model request."""
    from contextlib import ExitStack

    events = Queue()
    generation = 0
    child = None
    menu = None
    restore_size_at = None
    keys, composer = InputKeys(), SlashInput()
    size = shutil.get_terminal_size()
    renderer = TerminalRenderer(size)
    screen = renderer.screen
    process_cwd = Path.cwd()

    def write(data):
        if not data:
            return
        sys.stdout.buffer.write(data.encode("utf-8") if isinstance(data, str) else data)
        sys.stdout.buffer.flush()

    def input_reader():
        try:
            while data := os.read(sys.stdin.fileno(), 4096):
                events.put(("input", None, data))
        finally:
            events.put(("eof", None, None))

    def start(command_):
        nonlocal generation
        if os.name == "nt":
            from xingchi_conpty import WindowsChild
            backend = WindowsChild
        else:
            backend = PosixChild
        current = backend(command_, env, process_cwd, size)
        generation += 1
        tag = generation

        def output_reader():
            try:
                while data := current.read():
                    events.put(("output", tag, data))
            except OSError:
                pass
            finally:
                events.put(("exit", tag, None))

        Thread(target=output_reader, daemon=True).start()
        return current

    def repaint():
        nonlocal restore_size_at
        child.resize(os.terminal_size((max(20, size.columns - 1), size.lines)))
        restore_size_at = monotonic() + 0.08

    def draw():
        if menu:
            renderer.cover()
            write(renderer.frame(menu.render(size, cwd).encode()))
        else:
            write(renderer.redraw(composer))

    def load_sessions(target):
        try:
            with history_request() as request:
                sessions = list_threads(request, cwd)
            events.put(("sessions", target, sessions))
        except (OSError, RuntimeError, ValueError) as exc:
            events.put(("sessions_error", target, str(exc)))

    def handle(key):
        nonlocal child, menu, composer, screen, renderer
        if menu:
            if terminal_report(key):
                child.write(key)
                return
            result = menu.key(key, max(1, size.lines - 9))
            if result == "cancel":
                menu = None
                write("\x1b[?25h")
                repaint()
            elif result:
                try:
                    next_command = fresh_command(result, cwd)
                except (OSError, RuntimeError, ValueError) as exc:
                    menu.error = str(exc)
                else:
                    child.close()
                    menu, composer = None, SlashInput()
                    renderer = TerminalRenderer(size)
                    screen = renderer.screen
                    write("\x1b[?25h\x1b[H\x1b[2J")
                    child = start(next_command)
            draw()
            return
        previous_candidate = composer.candidate
        popup = screen.popup()
        forwarded, selector = composer.feed(key, native_available=bool(popup),
                                            native_first=bool(popup and popup[0][0] == popup[1]))
        if forwarded:
            child.write(forwarded)
        if selector is not None:
            menu = SessionMenu(selector)
            Thread(target=load_sessions, args=(menu,), daemon=True).start()
            draw()
        elif not forwarded or previous_candidate and not composer.candidate:
            # Text and native navigation render when Codex acknowledges them.
            # A speculative overlay here uses the previous popup's geometry.
            draw()

    with ExitStack() as cleanup:
        if os.name == "nt":
            from xingchi_conpty import raw_console
            cleanup.enter_context(raw_console())
        else:
            import termios
            import tty
            saved = termios.tcgetattr(sys.stdin.fileno())
            cleanup.callback(termios.tcsetattr, sys.stdin.fileno(), termios.TCSADRAIN, saved)
            tty.setraw(sys.stdin.fileno())
            previous = signal.signal(signal.SIGWINCH, lambda *_: events.put(("resize", None, None)))
            cleanup.callback(signal.signal, signal.SIGWINCH, previous)
        try:
            child = start(command)
            Thread(target=input_reader, daemon=True).start()
            while True:
                try:
                    kind, tag, data = events.get(timeout=0.04)
                except Empty:
                    kind, tag, data = "idle", None, None
                if kind == "input":
                    for key in keys.feed(data):
                        handle(key)
                elif kind == "eof":
                    return 0
                elif kind == "output" and tag == generation:
                    write(renderer.feed(data, composer, visible=not menu))
                    if screen.ready and not composer.candidate and screen.empty_composer():
                        composer.empty, composer.length = True, 0
                elif kind == "exit" and tag == generation:
                    return child.poll() or 0
                elif kind == "sessions" and tag is menu:
                    menu.sessions = data
                    if menu.query:
                        try:
                            selected = select_thread(data, menu.query.removeprefix("@"))
                            menu.query = selected["id"]
                        except RuntimeError:
                            pass
                    draw()
                elif kind == "sessions_error" and tag is menu:
                    menu.sessions, menu.error = [], data
                    draw()
                elif kind == "resize" or (os.name == "nt" and shutil.get_terminal_size() != size):
                    size = shutil.get_terminal_size()
                    renderer.resize(size)
                    child.resize(size)
                    if menu:
                        draw()
                for key in keys.escape():
                    handle(key)
                if restore_size_at and monotonic() >= restore_size_at:
                    child.resize(size)
                    restore_size_at = None
        finally:
            if child:
                child.close()
            write("\x1b[0m\x1b[?25h")
