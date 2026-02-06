"""Modal JSON editor widget."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from enum import Enum, auto

from rich.text import Text
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget


class EditorMode(Enum):
    NORMAL = auto()
    INSERT = auto()
    COMMAND = auto()


class JsonEditor(Widget, can_focus=True):
    """A modal JSON editor Textual widget.

    Supported commands:
      NORMAL: h j k l  w b  0 $ ^  gg G  %  i I a A o O
              x  dd dw d$  cw cc  r{c}  J  yy p P  u
      INSERT: typing / Backspace / Enter / Tab / Escape
      COMMAND: :w :q :wq :fmt
    """

    DEFAULT_CSS = """
    JsonEditor {
        height: 1fr;
        background: $surface;
        padding: 0 1;
    }
    """

    mode: reactive[EditorMode] = reactive(EditorMode.NORMAL)

    # -- Messages ----------------------------------------------------------

    @dataclass
    class JsonValidated(Message):
        content: str
        valid: bool
        error: str = ""

    @dataclass
    class FileSaveRequested(Message):
        content: str
        file_path: str       # empty string means save to current file
        quit_after: bool = False

    @dataclass
    class FileOpenRequested(Message):
        file_path: str

    @dataclass
    class Quit(Message):
        pass

    @dataclass
    class ForceQuit(Message):
        pass

    @dataclass
    class HelpToggleRequested(Message):
        pass

    @dataclass
    class EmbeddedEditRequested(Message):
        content: str  # Parsed JSON content to edit
        source_row: int  # Row of the string value
        source_col_start: int  # Column where string starts (including quote)
        source_col_end: int  # Column where string ends (including quote)

    @dataclass
    class EmbeddedEditSave(Message):
        content: str  # Updated JSON content

    # -- Init --------------------------------------------------------------

    def __init__(
        self,
        initial_content: str = "",
        *,
        read_only: bool = False,
        jsonl: bool = False,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.read_only: bool = read_only
        self.jsonl: bool = jsonl
        if self.jsonl and initial_content:
            initial_content = self._jsonl_to_pretty(initial_content)
        self.lines: list[str] = (
            initial_content.split("\n") if initial_content else [""]
        )
        self.cursor_row: int = 0
        self.cursor_col: int = 0
        self._mode: EditorMode = EditorMode.NORMAL
        self.command_buffer: str = ""
        self.pending: str = ""
        self.status_msg: str = ""
        self.undo_stack: list[tuple[list[str], int, int]] = []
        self.redo_stack: list[tuple[list[str], int, int]] = []
        self.yank_buffer: list[str] = []
        self._scroll_top: int = 0
        self._dot_buffer: list[tuple[str, str | None]] = []
        self._dot_recording: bool = False
        self._dot_replaying: bool = False

    # -- Helpers -----------------------------------------------------------

    def _dot_start(self, event) -> None:
        """Begin recording a new edit sequence for dot-repeat."""
        if self._dot_replaying:
            return
        self._dot_buffer = [(event.key, event.character)]
        self._dot_recording = True

    def _dot_stop(self) -> None:
        self._dot_recording = False

    def _dot_replay(self) -> None:
        """Replay the last recorded edit sequence."""
        if not self._dot_buffer:
            return
        from types import SimpleNamespace

        self._dot_replaying = True
        for rkey, rchar in self._dot_buffer:
            mock = SimpleNamespace(key=rkey, character=rchar)
            if self._mode == EditorMode.NORMAL:
                self._handle_normal(mock)
            elif self._mode == EditorMode.INSERT:
                self._handle_insert(mock)
            self._clamp_cursor()
        self._dot_replaying = False

    def _save_undo(self) -> None:
        self.undo_stack.append((self.lines[:], self.cursor_row, self.cursor_col))
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)
        # Clear redo stack on new edit
        if self.redo_stack:
            self.redo_stack.clear()

    def _clamp_cursor(self) -> None:
        self.cursor_row = max(0, min(self.cursor_row, len(self.lines) - 1))
        line_len = len(self.lines[self.cursor_row])
        if self._mode == EditorMode.NORMAL:
            max_col = max(0, line_len - 1) if line_len else 0
        else:
            max_col = line_len
        self.cursor_col = max(0, min(self.cursor_col, max_col))

    @staticmethod
    def _char_width(ch: str) -> int:
        """Return display width of a character (2 for fullwidth/wide)."""
        if ch < "\u0100":
            return 1
        return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1

    def _make_segments(self, line: str, avail: int) -> list[tuple[int, int]]:
        """Break *line* into segments fitting within *avail* display columns."""
        if not line:
            return [(0, 0)]
        if line.isascii():
            return [
                (s, min(s + avail, len(line)))
                for s in range(0, len(line), avail)
            ]
        segs: list[tuple[int, int]] = []
        seg_start = 0
        w = 0
        for i, ch in enumerate(line):
            cw = self._char_width(ch)
            if w + cw > avail and i > seg_start:
                segs.append((seg_start, i))
                seg_start = i
                w = cw
            else:
                w += cw
        segs.append((seg_start, len(line)))
        return segs

    def _wrap_rows(self, line: str, avail: int) -> int:
        """Return the number of display rows a line occupies when wrapped."""
        if not line:
            return 1
        if line.isascii():
            return -(-len(line) // avail)
        rows = 1
        w = 0
        for ch in line:
            cw = self._char_width(ch)
            if w + cw > avail:
                rows += 1
                w = cw
            else:
                w += cw
        return rows

    def _cursor_wrap_dy(self, line: str, cursor_col: int, avail: int) -> int:
        """Return the wrapped row index (0-based) of *cursor_col* within *line*."""
        segs = self._make_segments(line, avail)
        for si, (s_start, s_end) in enumerate(segs):
            if cursor_col < s_end:
                return si
        # cursor at end of line — check if cursor block fits on last row
        if line:
            ls, le = segs[-1]
            last_w = sum(self._char_width(line[c]) for c in range(ls, le))
            if last_w + 1 > avail:
                return len(segs)
        return max(0, len(segs) - 1)

    def _gutter_widths(self) -> tuple[int, int, int]:
        """Return ``(ln_width, rec_width, prefix_width)``.

        *rec_width* is 0 when not in JSONL mode.
        """
        ln_width = max(3, len(str(len(self.lines))))
        if not self.jsonl:
            return ln_width, 0, ln_width + 1
        rec_count = 0
        in_block = False
        for line in self.lines:
            if line.strip():
                if not in_block:
                    rec_count += 1
                    in_block = True
            else:
                in_block = False
        rec_width = max(2, len(str(max(1, rec_count))))
        return ln_width, rec_width, rec_width + 1 + ln_width + 1

    def _jsonl_line_records(self) -> list[int]:
        """Map each editor line to its JSONL record number.

        The first line of each block gets the 1-based record number;
        all other lines (continuation / blank separator) get 0.
        """
        result = [0] * len(self.lines)
        record = 0
        in_block = False
        for i, line in enumerate(self.lines):
            if line.strip():
                if not in_block:
                    record += 1
                    result[i] = record
                    in_block = True
            else:
                in_block = False
        return result

    def _visible_height(self) -> int:
        return max(1, self.content_region.height - 2)

    def _ensure_cursor_visible(self, avail: int) -> None:
        vh = self._visible_height()

        if self.cursor_row < self._scroll_top:
            self._scroll_top = self.cursor_row

        rows_before = sum(
            self._wrap_rows(self.lines[i], avail)
            for i in range(self._scroll_top, self.cursor_row)
        )
        cursor_dy = self._cursor_wrap_dy(
            self.lines[self.cursor_row], self.cursor_col, avail
        )
        while rows_before + cursor_dy >= vh and self._scroll_top <= self.cursor_row:
            rows_before -= self._wrap_rows(self.lines[self._scroll_top], avail)
            self._scroll_top += 1

    # -- Public API --------------------------------------------------------

    def get_content(self) -> str:
        return "\n".join(self.lines)

    def set_content(self, content: str) -> None:
        if self.jsonl and content:
            content = self._jsonl_to_pretty(content)
        self.lines = content.split("\n") if content else [""]
        self.cursor_row = 0
        self.cursor_col = 0
        self.refresh()

    # =====================================================================
    # Rendering
    # =====================================================================

    def render(self) -> Text:
        width = self.content_region.width
        height = self.content_region.height
        if height < 3 or width < 10:
            return Text("(too small)")

        content_height = height - 2
        ln_width, rec_width, prefix_w = self._gutter_widths()
        avail = max(1, width - prefix_w)
        jsonl_records = self._jsonl_line_records() if self.jsonl else None

        self._ensure_cursor_visible(avail)

        # Local references for hot path
        lines = self.lines
        cursor_row = self.cursor_row
        cursor_col = self.cursor_col
        make_segments = self._make_segments
        char_width = self._char_width
        compute_styles = self._compute_line_styles
        result_append = Text.append

        result = Text()
        rows_used = 0
        line_idx = self._scroll_top
        num_lines = len(lines)

        while rows_used < content_height and line_idx < num_lines:
            line = lines[line_idx]
            is_cursor_line = line_idx == cursor_row
            line_len = len(line)

            # Break line into width-aware wrapped segments
            segs = make_segments(line, avail)
            # Cursor at end of line may need an extra wrap row
            if is_cursor_line and cursor_col >= line_len and line:
                ls, le = segs[-1]
                last_w = sum(char_width(line[c]) for c in range(ls, le))
                if last_w + 1 > avail:
                    segs.append((line_len, line_len))

            # Pre-compute styles once per line
            line_styles = compute_styles(line)

            for si, (s_start, s_end) in enumerate(segs):
                if rows_used >= content_height:
                    break
                # Line number on first row, indent on continuation
                if si == 0:
                    result_append(result, f"{line_idx + 1:>{ln_width}} ", style="dim cyan")
                    if rec_width:
                        rec_num = jsonl_records[line_idx]
                        if rec_num:
                            result_append(result, f"{rec_num:>{rec_width}} ", style="dim yellow")
                        else:
                            result_append(result, " " * (rec_width + 1))
                else:
                    result_append(result, " " * prefix_w)
                # Render segment — batch consecutive chars with same style
                col = s_start
                while col < s_end:
                    if is_cursor_line and col == cursor_col:
                        result_append(result, line[col], style=f"reverse {line_styles[col]}")
                        col += 1
                        continue
                    sty = line_styles[col]
                    end = col + 1
                    while end < s_end and line_styles[end] == sty and not (is_cursor_line and end == cursor_col):
                        end += 1
                    result_append(result, line[col:end], style=sty)
                    col = end
                # Cursor block at end of line (insert mode)
                if is_cursor_line and cursor_col >= line_len and si == len(segs) - 1:
                    result_append(result, " ", style="reverse")
                result_append(result, "\n")
                rows_used += 1

            line_idx += 1

        # Fill remaining rows with ~
        if rows_used < content_height:
            tilde_line = f"{'~':>{prefix_w - 1}} \n"
            while rows_used < content_height:
                result_append(result, tilde_line, style="dim blue")
                rows_used += 1

        # status bar
        mode = self._mode
        mode_label = f" {mode.name} "
        result_append(result, mode_label, style=self._MODE_STYLE[mode])

        read_only = self.read_only
        if read_only:
            result_append(result, " RO ", style="bold white on grey37")

        pending = self.pending
        if pending:
            result_append(result, f"  {pending}", style="bold yellow")

        status_msg = self.status_msg
        pos = f" Ln {cursor_row + 1}/{num_lines}, Col {cursor_col + 1} "
        ro_len = 4 if read_only else 0
        spacer_len = max(0, width - len(mode_label) - ro_len - len(pos) - len(status_msg) - 4)
        result_append(result, f"  {status_msg}")
        if spacer_len:
            result_append(result, " " * spacer_len)
        result_append(result, pos, style="bold")

        if mode == EditorMode.COMMAND:
            result_append(result, f"\n:{self.command_buffer}", style="bold yellow")
        else:
            result_append(result, "\n")

        return result

    # -- Syntax colouring helpers ------------------------------------------

    _BRACKET = frozenset("{}[]")
    _PUNCT = frozenset(":,")
    _DIGIT = frozenset("0123456789.-+eE")
    _KEYWORDS = ("true", "false", "null")
    _MODE_STYLE = {
        EditorMode.NORMAL: "bold white on dark_green",
        EditorMode.INSERT: "bold white on dark_blue",
        EditorMode.COMMAND: "bold white on dark_red",
    }

    def _compute_line_styles(self, line: str) -> list[str]:
        """Compute syntax highlight styles for every character in *line*."""
        n = len(line)
        if n == 0:
            return []

        # Local references for hot path
        BRACKET = self._BRACKET
        PUNCT = self._PUNCT
        DIGIT = self._DIGIT

        styles = ["white"] * n
        is_in_str = [False] * n

        # Single pass: track string regions and first unquoted colon
        in_str = False
        first_colon = -1
        prev_ch = ""

        for i, ch in enumerate(line):
            if ch == '"' and prev_ch != "\\":
                in_str = not in_str
                is_in_str[i] = True
            elif in_str:
                is_in_str[i] = True
            elif ch == ":" and first_colon == -1:
                first_colon = i
            prev_ch = ch

        # Assign styles in single pass
        for i, ch in enumerate(line):
            if ch in BRACKET:
                styles[i] = "bold white"
            elif is_in_str[i]:
                styles[i] = "cyan" if first_colon == -1 or i < first_colon else "green"
            elif ch in DIGIT:
                styles[i] = "yellow"
            # PUNCT stays "white" (default)

        # Keywords outside strings
        lower = line.lower()
        for kw in self._KEYWORDS:
            kw_len = len(kw)
            start = 0
            while True:
                p = lower.find(kw, start)
                if p == -1:
                    break
                end = min(p + kw_len, n)
                for j in range(p, end):
                    if not is_in_str[j]:
                        styles[j] = "magenta"
                start = p + 1

        return styles

    # =====================================================================
    # Key handling
    # =====================================================================

    def on_key(self, event: events.Key) -> None:
        event.prevent_default()
        event.stop()

        if not self._dot_replaying and self._dot_recording:
            self._dot_buffer.append((event.key, event.character))

        if self._mode == EditorMode.NORMAL:
            self._handle_normal(event)
        elif self._mode == EditorMode.INSERT:
            self._handle_insert(event)
        elif self._mode == EditorMode.COMMAND:
            self._handle_command(event)

        self._clamp_cursor()
        self.refresh()

    # -- NORMAL ------------------------------------------------------------

    def _enter_insert(self) -> None:
        if self.read_only:
            self.status_msg = "[readonly]"
            return
        self._mode = EditorMode.INSERT
        self.status_msg = "-- INSERT --"

    def _handle_normal(self, event: events.Key) -> None:
        key = event.key
        char = event.character or ""

        if self.pending:
            self._handle_pending(char, key)
            return

        # movement
        if char == "h" or key == "left":
            self.cursor_col -= 1
        elif char == "j" or key == "down":
            self.cursor_row += 1
        elif char == "k" or key == "up":
            self.cursor_row -= 1
        elif char == "l" or key == "right":
            self.cursor_col += 1
        elif char == "w":
            self._move_word_forward()
        elif char == "b":
            self._move_word_backward()
        elif char == "0":
            self.cursor_col = 0
        elif char == "$" or key == "end":
            self.cursor_col = max(0, len(self.lines[self.cursor_row]) - 1)
        elif char == "^" or key == "home":
            line = self.lines[self.cursor_row]
            self.cursor_col = len(line) - len(line.lstrip())
        elif char == "G":
            self.cursor_row = len(self.lines) - 1
        elif char == "%":
            self._jump_matching_bracket()
        elif key == "pagedown" or key == "ctrl+f":
            self.cursor_row += self._visible_height()
        elif key == "pageup" or key == "ctrl+b":
            self.cursor_row -= self._visible_height()
        elif key == "ctrl+d":
            self.cursor_row += self._visible_height() // 2
        elif key == "ctrl+u":
            self.cursor_row -= self._visible_height() // 2
        elif key == "ctrl+e":
            self._scroll_top = min(
                self._scroll_top + 1, len(self.lines) - 1
            )
        elif key == "ctrl+y":
            self._scroll_top = max(self._scroll_top - 1, 0)
        elif key == "ctrl+g":
            total = len(self.lines)
            pct = (self.cursor_row + 1) * 100 // total if total else 0
            self.status_msg = (
                f'"{self._mode.name}" line {self.cursor_row + 1} of {total}'
                f" --{pct}%--"
            )

        # enter insert mode
        elif char == "i":
            if not self.read_only:
                self._dot_start(event)
            self._enter_insert()
        elif char == "I":
            if not self.read_only:
                self._dot_start(event)
            line = self.lines[self.cursor_row]
            self.cursor_col = len(line) - len(line.lstrip())
            self._enter_insert()
        elif char == "a":
            if not self.read_only:
                self._dot_start(event)
            self.cursor_col += 1
            self._enter_insert()
        elif char == "A":
            if not self.read_only:
                self._dot_start(event)
            self.cursor_col = len(self.lines[self.cursor_row])
            self._enter_insert()
        elif char == "o":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._dot_start(event)
                self._save_undo()
                indent = self._current_indent()
                before = self.lines[self.cursor_row].rstrip()
                extra = "    " if before.endswith(("{", "[")) else ""
                self.cursor_row += 1
                self.lines.insert(self.cursor_row, " " * indent + extra)
                self.cursor_col = indent + len(extra)
                self._enter_insert()
        elif char == "O":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._dot_start(event)
                self._save_undo()
                indent = self._current_indent()
                self.lines.insert(self.cursor_row, " " * indent)
                self.cursor_col = indent
                self._enter_insert()

        # single-key edits
        elif char == "x":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._dot_start(event)
                self._dot_stop()
                self._save_undo()
                line = self.lines[self.cursor_row]
                if line and self.cursor_col < len(line):
                    self.lines[self.cursor_row] = (
                        line[: self.cursor_col] + line[self.cursor_col + 1 :]
                    )
        elif char == "p":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._dot_start(event)
                self._dot_stop()
                self._paste_after()
        elif char == "P":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._dot_start(event)
                self._dot_stop()
                self._paste_before()
        elif char == "u":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._undo()
        elif key == "ctrl+r":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._redo()
        elif char == "J":
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._dot_start(event)
                self._dot_stop()
                self._join_lines()

        # dot repeat
        elif char == ".":
            if not self.read_only:
                self._dot_replay()

        # multi-key starters
        elif char in ("d", "c", "y", "r", "g", "e"):
            if self.read_only and char not in ("y", "g", "e"):
                self.status_msg = "[readonly]"
            else:
                if char not in ("y", "g", "e"):
                    self._dot_start(event)
                self.pending = char

        # command mode
        elif char == ":":
            self._mode = EditorMode.COMMAND
            self.command_buffer = ""
            self.status_msg = ""

    # -- Pending multi-char ------------------------------------------------

    def _handle_pending(self, char: str, key: str) -> None:
        if key == "escape" or not char:
            self.pending = ""
            self.status_msg = ""
            self._dot_stop()
            return

        combo = self.pending + char
        self.pending = ""

        if self.read_only and combo not in ("yy", "gg", "ej"):
            self.status_msg = "[readonly]"
            return

        if combo == "dd":
            self._save_undo()
            self.yank_buffer = [self.lines[self.cursor_row]]
            if len(self.lines) > 1:
                self.lines.pop(self.cursor_row)
                if self.cursor_row >= len(self.lines):
                    self.cursor_row = len(self.lines) - 1
            else:
                self.lines[0] = ""
            self.cursor_col = 0
            self.status_msg = "line deleted"
            self._dot_stop()

        elif combo == "dw":
            self._save_undo()
            self._delete_word()
            self._dot_stop()

        elif combo == "d$":
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = line[: self.cursor_col]
            self._dot_stop()

        elif combo == "d0":
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = line[self.cursor_col :]
            self.cursor_col = 0
            self._dot_stop()

        elif combo == "cw":
            self._save_undo()
            self._delete_word()
            self._enter_insert()
            # recording continues into insert mode

        elif combo == "cc":
            self._save_undo()
            indent = self._current_indent()
            self.yank_buffer = [self.lines[self.cursor_row]]
            self.lines[self.cursor_row] = " " * indent
            self.cursor_col = indent
            self._enter_insert()
            # recording continues into insert mode

        elif combo == "yy":
            self.yank_buffer = [self.lines[self.cursor_row]]
            self.status_msg = "line yanked"

        elif combo == "gg":
            self.cursor_row = 0
            self.cursor_col = 0

        elif len(combo) == 2 and combo[0] == "r":
            self._save_undo()
            line = self.lines[self.cursor_row]
            if self.cursor_col < len(line):
                self.lines[self.cursor_row] = (
                    line[: self.cursor_col] + combo[1] + line[self.cursor_col + 1 :]
                )
            self._dot_stop()

        elif combo == "ej":
            self._edit_embedded_json()

        else:
            self._dot_stop()
            self.status_msg = f"unknown: {combo}"

    # -- INSERT ------------------------------------------------------------

    def _handle_insert(self, event: events.Key) -> None:
        key = event.key
        char = event.character

        if key == "escape":
            self._dot_stop()
            self._mode = EditorMode.NORMAL
            self.cursor_col = max(0, self.cursor_col - 1)
            self.status_msg = ""
            return

        if key == "backspace":
            self._save_undo()
            if self.cursor_col > 0:
                line = self.lines[self.cursor_row]
                self.lines[self.cursor_row] = (
                    line[: self.cursor_col - 1] + line[self.cursor_col :]
                )
                self.cursor_col -= 1
            elif self.cursor_row > 0:
                prev = self.lines[self.cursor_row - 1]
                self.cursor_col = len(prev)
                self.lines[self.cursor_row - 1] = prev + self.lines[self.cursor_row]
                self.lines.pop(self.cursor_row)
                self.cursor_row -= 1
            return

        if key == "enter":
            self._save_undo()
            line = self.lines[self.cursor_row]
            indent = len(line) - len(line.lstrip()) if line.strip() else 0
            before = line[: self.cursor_col].rstrip()
            after = line[self.cursor_col :].lstrip()

            if before.endswith(("{", "[")) and after and after[0] in ("}", "]"):
                closing_indent = " " * indent
                new_indent = " " * indent + "    "
                self.lines[self.cursor_row] = line[: self.cursor_col]
                self.lines.insert(self.cursor_row + 1, new_indent)
                self.lines.insert(
                    self.cursor_row + 2,
                    closing_indent + line[self.cursor_col :].lstrip(),
                )
                self.cursor_row += 1
                self.cursor_col = len(new_indent)
                return

            extra = "    " if before.endswith(("{", "[")) else ""
            self.lines[self.cursor_row] = line[: self.cursor_col]
            new_line = " " * indent + extra + line[self.cursor_col :]
            self.cursor_row += 1
            self.lines.insert(self.cursor_row, new_line)
            self.cursor_col = indent + len(extra)
            return

        if key == "tab":
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = (
                line[: self.cursor_col] + "    " + line[self.cursor_col :]
            )
            self.cursor_col += 4
            return

        if key == "end":
            self.cursor_col = len(self.lines[self.cursor_row])
            return
        if key == "home":
            line = self.lines[self.cursor_row]
            self.cursor_col = len(line) - len(line.lstrip())
            return

        if key in ("left", "right", "up", "down"):
            delta = {"left": (0, -1), "right": (0, 1), "up": (-1, 0), "down": (1, 0)}
            dr, dc = delta[key]
            self.cursor_row += dr
            self.cursor_col += dc
            return

        # auto-dedent for closing brackets
        if char in ("}", "]"):
            self._save_undo()
            line = self.lines[self.cursor_row]
            before = line[: self.cursor_col]
            if before.strip() == "":
                new_indent = max(0, len(before) - 4)
                self.lines[self.cursor_row] = (
                    " " * new_indent + char + line[self.cursor_col :]
                )
                self.cursor_col = new_indent + 1
                return

        if char and char.isprintable():
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = (
                line[: self.cursor_col] + char + line[self.cursor_col :]
            )
            self.cursor_col += 1

    # -- COMMAND -----------------------------------------------------------

    def _handle_command(self, event: events.Key) -> None:
        key = event.key
        char = event.character

        if key == "escape":
            self._mode = EditorMode.NORMAL
            self.command_buffer = ""
            self.status_msg = ""
            return

        if key == "enter":
            self._exec_command(self.command_buffer.strip())
            if self._mode == EditorMode.COMMAND:
                self._mode = EditorMode.NORMAL
            self.command_buffer = ""
            return

        if key == "backspace":
            if self.command_buffer:
                self.command_buffer = self.command_buffer[:-1]
            else:
                self._mode = EditorMode.NORMAL
            return

        if char and char.isprintable():
            self.command_buffer += char

    def _exec_command(self, cmd: str) -> None:
        stripped = cmd.strip()

        # :$ → jump to last line
        if stripped == "$":
            self.cursor_row = len(self.lines) - 1
            self.cursor_col = 0
            return

        # Line jump: :l<num> → editor line; :<num> or :p<num> → file line (JSONL record)
        if len(stripped) > 1 and stripped[0] == "l" and stripped[1:].isdigit():
            num = int(stripped[1:])
            self.cursor_row = max(0, min(num - 1, len(self.lines) - 1))
            self.cursor_col = 0
            return
        if stripped.isdigit() or (len(stripped) > 1 and stripped[0] == "p" and stripped[1:].isdigit()):
            num = int(stripped if stripped.isdigit() else stripped[1:])
            if self.jsonl:
                records = self._jsonl_line_records()
                for i, rec in enumerate(records):
                    if rec == num:
                        self.cursor_row = i
                        self.cursor_col = 0
                        return
                self.status_msg = f"record {num} not found"
                return
            self.cursor_row = max(0, min(num - 1, len(self.lines) - 1))
            self.cursor_col = 0
            return

        parts = cmd.split(None, 1)
        verb = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else ""

        force = verb.endswith("!")
        if force:
            verb = verb[:-1]

        if verb == "w":
            if self.read_only:
                self.status_msg = "[readonly]"
                return
            content = self.get_content()
            if not force:
                valid, err = self._check_content(content)
                if not valid:
                    self.status_msg = err
                    return
            save = self._pretty_to_jsonl(content) if self.jsonl else content
            self.post_message(
                self.FileSaveRequested(content=save, file_path=arg)
            )
        elif verb == "q":
            if force:
                self.post_message(self.ForceQuit())
            else:
                self.post_message(self.Quit())
        elif verb in ("wq", "x"):
            if self.read_only:
                # read-only: just quit without saving
                self.post_message(self.Quit())
                return
            content = self.get_content()
            if not force:
                valid, err = self._check_content(content)
                if not valid:
                    self.status_msg = err
                    return
            save = self._pretty_to_jsonl(content) if self.jsonl else content
            self.post_message(
                self.FileSaveRequested(
                    content=save, file_path=arg, quit_after=True
                )
            )
        elif verb == "e":
            if not arg:
                self.status_msg = "Usage: :e <file>"
            else:
                self.post_message(self.FileOpenRequested(file_path=arg))
        elif verb in ("fmt", "format"):
            if self.read_only:
                self.status_msg = "[readonly]"
            else:
                self._format_json()
        elif verb == "help":
            self.post_message(self.HelpToggleRequested())
        else:
            self.status_msg = f"unknown command: :{cmd}"

    # -- JSON operations ---------------------------------------------------

    def _check_content(self, content: str) -> tuple[bool, str]:
        """Validate content as JSON or JSONL. Returns (valid, error_msg)."""
        if self.jsonl:
            blocks = self._split_jsonl_blocks(content)
            for i, block in enumerate(blocks, 1):
                try:
                    json.loads(block)
                except json.JSONDecodeError as e:
                    return False, f"JSONL error: record {i}: {e.msg}"
            return True, ""
        try:
            json.loads(content)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"JSON error: {e.msg} (line {e.lineno})"

    def _validate_json(self) -> bool:
        content = self.get_content()
        valid, err = self._check_content(content)
        if valid:
            label = "JSONL" if self.jsonl else "JSON"
            self.status_msg = f"{label} valid"
            self.post_message(self.JsonValidated(content=content, valid=True))
            return True
        self.status_msg = err
        self.post_message(
            self.JsonValidated(content=content, valid=False, error=err)
        )
        return False

    def _format_json(self) -> None:
        if self.jsonl:
            self._format_jsonl()
            return
        content = self.get_content()
        try:
            parsed = json.loads(content)
            formatted = json.dumps(parsed, indent=4, ensure_ascii=False)
            self._save_undo()
            self.lines = formatted.split("\n")
            self.cursor_row = 0
            self.cursor_col = 0
            self.status_msg = "formatted"
        except json.JSONDecodeError as e:
            self.status_msg = f"cannot format: {e.msg} (line {e.lineno})"

    def _format_jsonl(self) -> None:
        content = self.get_content()
        blocks = self._split_jsonl_blocks(content)
        formatted: list[str] = []
        for i, block in enumerate(blocks):
            try:
                parsed = json.loads(block)
                formatted.append(json.dumps(parsed, indent=4, ensure_ascii=False))
            except json.JSONDecodeError as e:
                self.status_msg = f"cannot format: record {i + 1}: {e.msg}"
                return
        self._save_undo()
        self.lines = "\n\n".join(formatted).split("\n")
        self.cursor_row = 0
        self.cursor_col = 0
        self.status_msg = "formatted"

    def _find_string_at_cursor(self) -> tuple[int, int, str] | None:
        """Find the string value at the current cursor position.

        Returns (col_start, col_end, string_content) or None if not on a string.
        col_start and col_end include the quotes.
        """
        line = self.lines[self.cursor_row]
        col = self.cursor_col

        # Find if we're inside a string
        in_string = False
        string_start = -1
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    string_start = i
                else:
                    # End of string
                    if string_start <= col <= i:
                        # Cursor is in this string
                        raw = line[string_start + 1 : i]
                        # Unescape the string
                        try:
                            content = json.loads(f'"{raw}"')
                            return (string_start, i + 1, content)
                        except json.JSONDecodeError:
                            return None
                    in_string = False
                    string_start = -1
            i += 1
        return None

    def _edit_embedded_json(self) -> None:
        """Handle :ej command to edit embedded JSON string."""
        result = self._find_string_at_cursor()
        if result is None:
            self.status_msg = "cursor not on a string value"
            return

        col_start, col_end, content = result

        # Try to parse as JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            self.status_msg = "string is not valid JSON"
            return

        # Check if it's a list or dict
        if not isinstance(parsed, (list, dict)):
            self.status_msg = "string is not a list or dict"
            return

        # Format and send for editing
        formatted = json.dumps(parsed, indent=4, ensure_ascii=False)
        self.post_message(
            self.EmbeddedEditRequested(
                content=formatted,
                source_row=self.cursor_row,
                source_col_start=col_start,
                source_col_end=col_end,
            )
        )

    def update_embedded_string(
        self, row: int, col_start: int, col_end: int, new_content: str
    ) -> None:
        """Update a string value with new JSON content."""
        self._save_undo()
        # Escape the new content as a JSON string
        escaped = json.dumps(new_content, ensure_ascii=False)
        line = self.lines[row]
        self.lines[row] = line[:col_start] + escaped + line[col_end:]
        self.refresh()

    # -- JSONL helpers -----------------------------------------------------

    @staticmethod
    def _jsonl_to_pretty(content: str) -> str:
        """Convert JSONL (one-json-per-line) to pretty-printed blocks."""
        blocks: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
                blocks.append(json.dumps(parsed, indent=4, ensure_ascii=False))
            except json.JSONDecodeError:
                blocks.append(stripped)
        return "\n\n".join(blocks)

    @staticmethod
    def _split_jsonl_blocks(content: str) -> list[str]:
        """Split pretty-printed content into blocks separated by blank lines."""
        blocks: list[str] = []
        current: list[str] = []
        for line in content.split("\n"):
            if line.strip():
                current.append(line)
            else:
                if current:
                    blocks.append("\n".join(current))
                    current = []
        if current:
            blocks.append("\n".join(current))
        return blocks

    @staticmethod
    def _pretty_to_jsonl(content: str) -> str:
        """Convert pretty-printed blocks back to JSONL (one-json-per-line)."""
        blocks = JsonEditor._split_jsonl_blocks(content)
        lines: list[str] = []
        for block in blocks:
            try:
                parsed = json.loads(block)
                lines.append(json.dumps(parsed, ensure_ascii=False))
            except json.JSONDecodeError:
                lines.append(" ".join(block.split()))
        return "\n".join(lines)

    # -- Movement helpers --------------------------------------------------

    def _current_indent(self) -> int:
        line = self.lines[self.cursor_row]
        return len(line) - len(line.lstrip()) if line.strip() else 0

    def _move_word_forward(self) -> None:
        line = self.lines[self.cursor_row]
        col = self.cursor_col
        while col < len(line) and (line[col].isalnum() or line[col] == "_"):
            col += 1
        while col < len(line) and not (line[col].isalnum() or line[col] == "_"):
            col += 1
        if col >= len(line) and self.cursor_row < len(self.lines) - 1:
            self.cursor_row += 1
            nline = self.lines[self.cursor_row]
            self.cursor_col = len(nline) - len(nline.lstrip())
        else:
            self.cursor_col = min(col, max(0, len(line) - 1))

    def _move_word_backward(self) -> None:
        line = self.lines[self.cursor_row]
        col = self.cursor_col
        if col == 0:
            if self.cursor_row > 0:
                self.cursor_row -= 1
                self.cursor_col = max(0, len(self.lines[self.cursor_row]) - 1)
            return
        col -= 1
        while col > 0 and not (line[col].isalnum() or line[col] == "_"):
            col -= 1
        while col > 0 and (line[col - 1].isalnum() or line[col - 1] == "_"):
            col -= 1
        self.cursor_col = col

    def _jump_matching_bracket(self) -> None:
        line = self.lines[self.cursor_row]
        if self.cursor_col >= len(line):
            return
        ch = line[self.cursor_col]
        pairs = {"{": "}", "[": "]", "(": ")"}
        rpairs = {v: k for k, v in pairs.items()}
        if ch in pairs:
            self._search_bracket_forward(ch, pairs[ch])
        elif ch in rpairs:
            self._search_bracket_backward(ch, rpairs[ch])

    def _search_bracket_forward(self, open_ch: str, close_ch: str) -> None:
        depth = 1
        row, col = self.cursor_row, self.cursor_col + 1
        while row < len(self.lines):
            line = self.lines[row]
            while col < len(line):
                if line[col] == open_ch:
                    depth += 1
                elif line[col] == close_ch:
                    depth -= 1
                    if depth == 0:
                        self.cursor_row, self.cursor_col = row, col
                        return
                col += 1
            row += 1
            col = 0

    def _search_bracket_backward(self, close_ch: str, open_ch: str) -> None:
        depth = 1
        row, col = self.cursor_row, self.cursor_col - 1
        while row >= 0:
            line = self.lines[row]
            while col >= 0:
                if line[col] == close_ch:
                    depth += 1
                elif line[col] == open_ch:
                    depth -= 1
                    if depth == 0:
                        self.cursor_row, self.cursor_col = row, col
                        return
                col -= 1
            row -= 1
            if row >= 0:
                col = len(self.lines[row]) - 1

    # -- Edit helpers ------------------------------------------------------

    def _delete_word(self) -> None:
        line = self.lines[self.cursor_row]
        col = self.cursor_col
        start = col
        while col < len(line) and (line[col].isalnum() or line[col] == "_"):
            col += 1
        while col < len(line) and line[col] == " ":
            col += 1
        if col == start and col < len(line):
            col += 1
        self.lines[self.cursor_row] = line[:start] + line[col:]

    def _paste_after(self) -> None:
        if not self.yank_buffer:
            return
        self._save_undo()
        for i, line in enumerate(self.yank_buffer):
            self.lines.insert(self.cursor_row + 1 + i, line)
        self.cursor_row += 1
        self.cursor_col = 0

    def _paste_before(self) -> None:
        if not self.yank_buffer:
            return
        self._save_undo()
        for i, line in enumerate(self.yank_buffer):
            self.lines.insert(self.cursor_row + i, line)
        self.cursor_col = 0

    def _join_lines(self) -> None:
        if self.cursor_row >= len(self.lines) - 1:
            return
        self._save_undo()
        cur = self.lines[self.cursor_row].rstrip()
        nxt = self.lines[self.cursor_row + 1].lstrip()
        self.cursor_col = len(cur)
        self.lines[self.cursor_row] = cur + " " + nxt
        self.lines.pop(self.cursor_row + 1)

    def _undo(self) -> None:
        if not self.undo_stack:
            self.status_msg = "nothing to undo"
            return
        # Save current state for redo
        self.redo_stack.append(
            ([line for line in self.lines], self.cursor_row, self.cursor_col)
        )
        lines, row, col = self.undo_stack.pop()
        self.lines = lines
        self.cursor_row = row
        self.cursor_col = col
        self.status_msg = "undone"

    def _redo(self) -> None:
        if not self.redo_stack:
            self.status_msg = "nothing to redo"
            return
        # Save current state for undo
        self.undo_stack.append(
            ([line for line in self.lines], self.cursor_row, self.cursor_col)
        )
        lines, row, col = self.redo_stack.pop()
        self.lines = lines
        self.cursor_row = row
        self.cursor_col = col
        self.status_msg = "redone"
