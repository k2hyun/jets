"""Demo application for the JSON editor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from .editor import JsonEditor

SAMPLE_JSON = """\
{
    "name": "json-editor",
    "version": "1.0.0",
    "description": "A modal JSON editor built with Textual",
    "features": [
        "normal mode",
        "insert mode",
        "command mode",
        "syntax highlighting",
        "json validation",
        "bracket matching"
    ],
    "config": {
        "theme": "dark",
        "indent_size": 4,
        "auto_format": true,
        "max_undo": 200,
        "nested": {
            "deep": {
                "value": null
            }
        }
    },
    "scores": [100, 200, 300]
}"""


class JsonEditorApp(App):
    """TUI app that wraps the JsonEditor widget."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #editor {
        height: 1fr;
        border: solid $accent;
    }
    #help-bar {
        height: auto;
        max-height: 5;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
        border-top: solid $accent 50%;
    }
    """

    TITLE = "JSON Editor"
    BINDINGS = []

    def __init__(
        self,
        file_path: str = "",
        initial_content: str = "",
        read_only: bool = False,
        jsonl: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.file_path = file_path
        self.initial_content = initial_content
        self.read_only = read_only
        self.jsonl = jsonl

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield JsonEditor(
            self.initial_content,
            read_only=self.read_only,
            jsonl=self.jsonl,
            id="editor",
        )
        yield Static(
            "[b]Move:[/b] h j k l  w b  0 $ ^  gg G  %  PgUp/PgDn\n"
            "[b]Edit:[/b] i I a A o O  x  dd dw d$ cw cc  r[dim]{c}[/]"
            "  J  yy p P  u\n"
            "[b]Cmd :[/b] :w [dim]save[/]  :w [dim italic]file[/]  :e [dim italic]file[/]"
            "  :fmt [dim]format[/]  :q [dim]quit[/]  :wq [dim]save+quit[/]",
            id="help-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._update_title()
        self.query_one("#editor").focus()

    def _update_title(self) -> None:
        ro = " [RO]" if self.read_only else ""
        if self.file_path:
            self.sub_title = self.file_path + ro
        else:
            self.sub_title = "[new]" + ro

    # -- Event handlers ----------------------------------------------------

    def on_json_editor_quit(self) -> None:
        self.exit()

    def on_json_editor_json_validated(
        self, event: JsonEditor.JsonValidated
    ) -> None:
        if event.valid:
            self.notify("JSON is valid", severity="information")
        else:
            self.notify(f"Invalid JSON: {event.error}", severity="error", timeout=6)

    def on_json_editor_file_save_requested(
        self, event: JsonEditor.FileSaveRequested
    ) -> None:
        target = event.file_path or self.file_path
        if not target:
            self.notify("No file name — use :w <file>", severity="warning")
            return

        try:
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(event.content, encoding="utf-8")
            self.file_path = str(path)
            self._update_title()
            self.notify(f"Saved: {self.file_path}", severity="information")
            if event.quit_after:
                self.exit()
        except OSError as exc:
            self.notify(f"Save failed: {exc}", severity="error", timeout=6)

    def on_json_editor_file_open_requested(
        self, event: JsonEditor.FileOpenRequested
    ) -> None:
        target = event.file_path
        try:
            content = Path(target).read_text(encoding="utf-8")
        except FileNotFoundError:
            self.notify(f"File not found: {target}", severity="error", timeout=6)
            return
        except OSError as exc:
            self.notify(f"Cannot open: {exc}", severity="error", timeout=6)
            return

        editor = self.query_one("#editor", JsonEditor)
        editor.set_content(content)
        self.jsonl = target.lower().endswith(".jsonl")
        editor.jsonl = self.jsonl
        self.file_path = target
        self._update_title()
        self.notify(f"Opened: {target}", severity="information")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jet",
        description="JSON Editor in Textual",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="",
        help="JSON file to open",
    )
    parser.add_argument(
        "-R", "--read-only",
        action="store_true",
        default=False,
        help="open in read-only mode",
    )
    args = parser.parse_args()

    file_path: str = args.file
    initial_content: str = SAMPLE_JSON
    jsonl: bool = file_path.lower().endswith(".jsonl") if file_path else False

    if file_path:
        path = Path(file_path)
        try:
            if path.exists():
                initial_content = path.read_text(encoding="utf-8")
            else:
                # New file — start with empty object / empty line
                initial_content = "" if jsonl else "{}"
        except PermissionError as exc:
            print(f"jet: {exc}", file=sys.stderr)
            sys.exit(1)

    app = JsonEditorApp(
        file_path=file_path,
        initial_content=initial_content,
        read_only=args.read_only,
        jsonl=jsonl,
    )
    app.run()


if __name__ == "__main__":
    main()
