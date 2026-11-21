"""The terminal extension must never send /inherit to a capped model."""

from pathlib import Path
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from xingchi_tui import InputKeys, SessionMenu, SlashInput, TerminalRenderer, TerminalScreen, interactive_options


class InheritTerminalTests(unittest.TestCase):
    def test_inherit_is_intercepted_before_enter_reaches_codex(self):
        composer = SlashInput()
        sent = b""
        for key in b"/inherit":
            data, selected = composer.feed(bytes([key]))
            sent += data
            self.assertIsNone(selected)
        data, selected = composer.feed(b"\r")
        self.assertEqual(selected, "")
        self.assertEqual(sent + data, b"/inherit\x15")
        self.assertNotIn(b"\r", sent + data)

    def test_other_slash_commands_and_terminal_replies_are_preserved(self):
        composer = SlashInput()
        sent = b""
        for key in (b"/", b"i", b"\x1b[1;2R", b"m", b"p", b"o", b"r", b"t", b"\r"):
            data, selected = composer.feed(key)
            sent += data
            self.assertIsNone(selected)
        self.assertEqual(sent, b"/i\x1b[1;2Rmport\r")

    def test_backspace_cancellation_and_inline_session_filter(self):
        composer = SlashInput()
        for key in b"/inhe":
            composer.feed(bytes([key]))
        composer.feed(b"\x7f")
        self.assertEqual(composer.candidate, b"/inh")
        self.assertEqual(composer.feed(b"\x1b"), (b"\x15", None))
        for key in b"/inherit renderer":
            composer.feed(bytes([key]))
        self.assertEqual(composer.feed(b"\r"), (b"\x15", "renderer"))

    def test_slash_popup_selects_inherit_without_typing_its_name(self):
        composer = SlashInput()
        self.assertEqual(composer.feed(b"/"), (b"/", None))
        self.assertEqual(composer.feed(b"\r"), (b"\x15", ""))

    def test_arrows_select_native_commands_and_return_to_inherit(self):
        composer = SlashInput()
        composer.feed(b"/")
        self.assertEqual(composer.feed(b"\x1b[B", native_available=True), (b"", None))
        self.assertFalse(composer.inherit_selected)
        self.assertEqual(composer.feed(b"\r"), (b"\r", None))
        composer.feed(b"/")
        composer.feed(b"\x1b[B", native_available=True)
        self.assertEqual(composer.feed(b"\x1b[A", native_available=True, native_first=True), (b"", None))
        self.assertTrue(composer.inherit_selected)
        self.assertEqual(composer.feed(b"\r"), (b"\x15", ""))

    def test_typed_prefix_is_forwarded_for_native_filtering(self):
        composer = SlashInput()
        sent = b"".join(composer.feed(bytes([key]))[0] for key in b"/inh")
        self.assertEqual(sent, b"/inh")
        self.assertEqual(composer.feed(b"\r"), (b"\x15", ""))

    def test_terminal_startup_reports_do_not_disable_the_command(self):
        composer = SlashInput()
        for report in (b"\x1b[?0u", b"\x1b[?1007;2$y", b"\x1b[?1;2c",
                       b"\x1b]11;rgb:0000/0000/0000\x1b\\", b"\x1bP>|terminal\x1b\\"):
            self.assertEqual(composer.feed(report), (report, None))
        composer.feed(b"/")
        self.assertEqual(composer.feed(b"\r"), (b"\x15", ""))

    def test_closing_a_native_picker_does_not_disable_the_next_command(self):
        composer = SlashInput()
        for key in b"/model\r":
            composer.feed(bytes([key]))
        composer.feed(b"\x1b")
        for key in b"/inherit":
            composer.feed(bytes([key]))
        self.assertEqual(composer.feed(b"\r"), (b"\x15", ""))

    def test_enhanced_keyboard_keys_and_releases_select_inherit(self):
        composer = SlashInput()
        self.assertEqual(composer.feed(b"\x1b[47u"), (b"\x1b[47u", None))
        self.assertEqual(composer.feed(b"\x1b[47;1:3u"), (b"\x1b[47;1:3u", None))
        self.assertEqual(composer.feed(b"\x1b[13u"), (b"\x15", ""))
        menu = SessionMenu()
        menu.sessions = [{"id": "one"}, {"id": "two"}]
        menu.key(b"\x1b[1;1B", 10)
        self.assertEqual(menu.key(b"\x1b[13u", 10), "two")
        self.assertEqual(menu.key(b"\x1b[27u", 10), "cancel")

    def test_escape_sequences_and_utf8_survive_split_reads(self):
        keys = InputKeys()
        self.assertEqual(keys.feed(b"\x1b["), [])
        self.assertEqual(keys.feed(b"A\xc3"), [b"\x1b[A"])
        self.assertEqual(keys.feed(b"\xa9"), ["é".encode()])
        self.assertEqual(keys.feed(b"\x1b[200~/inherit"), [])
        self.assertEqual(keys.feed(b"\x1b[201~"), [b"\x1b[200~/inherit\x1b[201~"])
        self.assertEqual(keys.feed(b"\x1b]11;rgb:0000/0000/0000\x1b"), [])
        self.assertEqual(keys.feed(b"\\"), [b"\x1b]11;rgb:0000/0000/0000\x1b\\"])
        self.assertEqual(keys.feed(b"\x1bP>|ter"), [])
        self.assertEqual(keys.feed(b"minal\x1b\\"), [b"\x1bP>|terminal\x1b\\"])

    def test_pasted_command_and_cleared_draft_work(self):
        composer = SlashInput()
        composer.feed(b"x")
        composer.feed(b"\x7f")
        data, selected = composer.feed(b"\x1b[200~/inherit\x1b[201~")
        self.assertEqual(data, b"\x1b[200~/inherit\x1b[201~")
        self.assertEqual(composer.feed(b"\r"), (b"\x15", ""))

    def test_picker_filters_navigates_selects_and_cancels(self):
        menu = SessionMenu()
        menu.sessions = [{"id": "first-id", "name": "Bevy house", "archived": False},
                         {"id": "second-id", "name": "Bevy renderer", "archived": False}]
        menu.key(b"\x1b[B", 10)
        self.assertEqual(menu.key(b"\r", 10), "second-id")
        menu.key(b"h", 10)
        menu.key(b"o", 10)
        self.assertEqual(menu.key(b"\r", 10), "first-id")
        self.assertEqual(menu.key(b"\x1b", 10), "cancel")

    def test_restart_keeps_settings_but_drops_old_resume_and_prompt(self):
        self.assertEqual(interactive_options(["-m", "chosen-model", "resume", "--last", "old prompt",
                                              "-c", "model_reasoning_effort=high"]),
                         ["-m", "chosen-model", "-c", "model_reasoning_effort=high"])
        self.assertIsNone(interactive_options(["-m", "chosen-model", "exec", "do something"]))
        self.assertIsNone(interactive_options(["--help"]))


class CommandPopupScreenTests(unittest.TestCase):
    def test_inherit_is_a_selected_row_above_the_native_commands(self):
        native = TerminalScreen(os.terminal_size((80, 24)))
        native.feed(b"\x1b[H\x1b[J\x1b[8;1H\x1b[7m\xe2\x80\xba /model         choose a model\x1b[0m"
                    b"\x1b[9;1H  /presets       run a preset\x1b[18;1H\xe2\x80\xba /\x1b[18;4H")
        rendered = TerminalScreen(os.terminal_size((80, 24)))
        rendered.feed(b"\x1b[8;1H\xe2\x80\xba /model         choose a model"
                      b"\x1b[9;1H  /presets       run a preset\x1b[18;1H\xe2\x80\xba /")
        rendered.feed(native.paint(native.extension_rows(True)).encode())
        self.assertTrue(rendered.line(6).startswith("› /inherit "))
        self.assertTrue(rendered.line(7).startswith("  /model "))
        self.assertEqual(rendered.line(17), "› /")
        self.assertNotIn("/inherit", rendered.line(23), "A footer hint is not a command entry")
        self.assertEqual((rendered.x, rendered.y), (native.x, native.y))

    def test_filtered_inherit_row_stays_next_to_the_composer(self):
        screen = TerminalScreen(os.terminal_size((80, 24)))
        screen.feed("\x1b[6;1H› /inherit\x1b[6;11H".encode())
        changes = screen.extension_rows(True)
        screen.feed(screen.paint(changes).encode())
        self.assertTrue(screen.line(3).startswith("› /inherit "))
        self.assertEqual(screen.line(5), "› /inherit")

    def test_split_escape_sequences_and_synchronized_frames_delay_overlay(self):
        screen = TerminalScreen(os.terminal_size((80, 24)))
        screen.feed(b"\x1b[?2026h\x1b[8;")
        self.assertFalse(screen.ready)
        screen.feed(b"1H\xe2\x80")
        self.assertFalse(screen.ready)
        screen.feed(b"\xba /model         choose\x1b[?2026l\x1b]0;title")
        self.assertFalse(screen.ready)
        screen.feed(b"\x07\x1b[18;4H")
        self.assertTrue(screen.ready)
        self.assertEqual(screen.popup(), ([7], 7))

    def test_scrollback_and_terminal_resize_keep_popup_position(self):
        screen = TerminalScreen(os.terminal_size((80, 24)))
        screen.feed("\x1b[8;1H› /model         choose\x1b[18;1H› /\x1b[1;6r\x1b[1;1H\x1bM\x1b[r\x1b[18;4H".encode())
        self.assertEqual(screen.popup(), ([7], 7))
        screen.resize(os.terminal_size((120, 40)))
        self.assertEqual(screen.popup(), ([7], 7))


class TerminalRedrawTests(unittest.TestCase):
    native_popup = ("\x1b[?2026h\x1b[H\x1b[J\x1b[8;1H› /model         choose a model"
                    "\x1b[9;1H  /presets       run a preset\x1b[18;1H› /\x1b[18;4H\x1b[?2026l").encode()

    def setUp(self):
        self.composer = SlashInput()
        self.composer.feed(b"/")
        size = os.terminal_size((80, 24))
        self.renderer = TerminalRenderer(size)
        self.visible = TerminalScreen(size)
        self.visible.feed(self.renderer.feed(self.native_popup, self.composer))

    def assert_committed_with_inherit(self, output):
        self.assertEqual(output.count(b"\x1b[?2026h"), 1)
        self.assertEqual(output.count(b"\x1b[?2026l"), 1,
                         "Intermediate commits expose the native popup without /inherit")
        self.visible.feed(output)
        self.assertTrue(self.visible.line(6).startswith("› /inherit "))
        self.assertTrue(self.visible.line(7).startswith("  /model "))

    def test_native_repaint_and_extension_are_one_visible_frame(self):
        update = b"\x1b[?2026h\x1b[18;4H\x1b[?2026l\x1b[?2026h\x1b[18;4H\x1b[?2026l"
        self.assert_committed_with_inherit(self.renderer.feed(update, self.composer))

    def test_split_frames_do_not_flush_missing_or_partial_entries(self):
        self.assertEqual(self.renderer.feed(b"\x1b[?2026h\x1b[18;", self.composer), b"")
        self.assertEqual(self.renderer.redraw(self.composer), b"")
        self.assertEqual(self.renderer.feed(b"4H", self.composer), b"")
        self.assertTrue(self.visible.line(6).startswith("› /inherit "))
        self.assert_committed_with_inherit(self.renderer.feed(b"\x1b[?2026l", self.composer))

    def test_unchanged_input_does_not_redraw_the_previous_popup(self):
        self.assertEqual(self.renderer.redraw(self.composer), b"")
        self.composer.feed(b"i")
        self.assertEqual(self.renderer.redraw(self.composer), b"")

    def test_native_relative_cursor_moves_start_from_the_old_native_cursor(self):
        update = b"\x1b[?2026h\x1b[1CXYZ\x1b[?2026l"
        self.assert_committed_with_inherit(self.renderer.feed(update, self.composer))
        self.assertEqual(self.visible.line(17), "› / XYZ")
        self.assertEqual((self.visible.x, self.visible.y),
                         (self.renderer.screen.x, self.renderer.screen.y))

    def test_covering_the_chat_drops_old_overlay_restoration(self):
        self.assertEqual(self.renderer.feed(b"\x1b[?2026h\x1b[H\x1b[J\x1b[?2026l",
                                            self.composer, visible=False), b"")
        self.assertEqual(self.renderer.restore, b"")

    def test_terminal_queries_and_osc_replies_remain_intact(self):
        queries = b"\x1b[6n\x1b]11;?\x1b\\"
        output = self.renderer.feed(queries, self.composer)
        self.assertIn(queries, output)
        self.assert_committed_with_inherit(output)

    def test_shrinking_waits_for_native_repaint_before_touching_the_moved_overlay(self):
        # Terminals can keep the top, scroll to the cursor, or clip the top
        # when shrinking. A pre-repaint cursor query must not add a second row
        # at the old absolute coordinates in any of those layouts.
        for shifted_rows in (0, 7, 10):
            with self.subTest(shifted_rows=shifted_rows):
                composer = SlashInput()
                composer.feed(b"/")
                size = os.terminal_size((120, 40))
                renderer = TerminalRenderer(size)
                visible = TerminalScreen(size)
                native = ("\x1b[?2026h\x1b[H\x1b[J\x1b[28;1H› /model         choose a model"
                          "\x1b[37;1H› /\x1b[37;4H\x1b[?2026l").encode()
                visible.feed(renderer.feed(native, composer))
                self.assertTrue(visible.line(26).startswith("› /inherit "))

                size = os.terminal_size((100, 30))
                visible.cells = visible.cells[shifted_rows:]
                visible.resize(size)
                renderer.resize(size)
                for update in (b"\x1b[6n", b"\x1b]0;title\x07",
                               b"\x1b[?2026h\x1b[?25h\x1b[?2026l"):
                    output = renderer.feed(update, composer)
                    self.assertIn(TerminalRenderer.sync_mode.sub(b"", update), output)
                    visible.feed(output)
                    self.assertEqual([y for y in range(visible.rows)
                                      if visible.line(y).startswith("› /inherit ")],
                                     [26 - shifted_rows])
                composer.inherit_selected = False
                self.assertEqual(renderer.redraw(composer), b"")
                composer.inherit_selected = True

                self.assertEqual(renderer.feed(b"\x1b[?2026h\x1b[H\x1b[", composer), b"")
                self.assertEqual(renderer.feed(b"J\x1b[18;1H", composer), b"")
                self.assertEqual(renderer.redraw(composer), b"")
                output = renderer.feed(("› /model         choose a model"
                                        "\x1b[27;1H› /\x1b[27;4H\x1b[?2026l").encode(), composer)
                self.assertEqual(output.count(b"\x1b[?2026l"), 1)
                visible.feed(output)
                self.assertEqual([y for y in range(visible.rows)
                                  if visible.line(y).startswith("› /inherit ")], [16])
                self.assertTrue(visible.line(17).startswith("  /model "))
                self.assertEqual((visible.x, visible.y), (3, 26))

    def test_unchanged_terminal_size_does_not_suspend_the_extension(self):
        self.renderer.resize(os.terminal_size((80, 24)))
        self.assert_committed_with_inherit(self.renderer.feed(b"\x1b[6n", self.composer))
        self.composer.inherit_selected = False
        self.assertIn(b"  /inherit ", self.renderer.redraw(self.composer))

    def test_inline_resize_resumes_after_clearing_its_viewport_below_history(self):
        size = os.terminal_size((100, 30))
        self.visible.resize(size)
        self.renderer.resize(size)
        update = ("\x1b[?2026h\x1b[6;1H\x1b[J\x1b[8;1H› /model         choose a model"
                  "\x1b[9;1H  /presets       run a preset\x1b[18;1H› /\x1b[18;4H\x1b[?2026l").encode()
        self.assert_committed_with_inherit(self.renderer.feed(update, self.composer))
        self.composer.inherit_selected = False
        self.assertIn(b"  /inherit ", self.renderer.redraw(self.composer))
