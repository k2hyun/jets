"""Static resources for vj."""

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

HELP_JSON = """\
{
    "Movement": {
        "h j k l": "left/down/up/right",
        "w b": "word forward/backward",
        "0 $ ^": "line start/end/first char",
        "gg G": "file start/end",
        "%": "jump to matching bracket",
        "PgUp PgDn": "page up/down",
        "Ctrl+d/u": "half page down/up"
    },
    "Insert Mode": {
        "i I": "insert at cursor/line start",
        "a A": "append after cursor/line end",
        "o O": "open line below/above"
    },
    "Editing": {
        "x": "delete char",
        "dd": "delete line",
        "dw d$": "delete word/to end",
        "cw cc": "change word/line",
        "r{c}": "replace char",
        "J": "join lines",
        "yy p P": "yank/paste after/before",
        "u": "undo",
        "Ctrl+r": "redo",
        ".": "repeat last edit",
        "ej": "edit embedded JSON string"
    },
    "Commands": {
        ":w": "save",
        ":w {file}": "save as",
        ":e {file}": "open file",
        ":fmt": "format JSON",
        ":q": "quit",
        ":wq": "save and quit",
        ":help": "toggle this help"
    }
}"""

APP_CSS = """
Screen {
    layout: vertical;
}
#editor {
    width: 1fr;
    height: 1fr;
    border: solid $accent;
}
#help-panel {
    height: 20%;
    display: none;
}
#help-panel.visible {
    display: block;
}
#help-header {
    height: auto;
    padding: 0 1;
    background: $accent;
}
#help-title {
    width: 1fr;
    padding: 0;
}
#help-close {
    min-width: 3;
    width: 3;
    height: 1;
    padding: 0;
    margin: 0;
    border: none;
    background: transparent;
    color: $text;
}
#help-close:hover {
    background: $error;
    color: $text;
}
#help-editor {
    height: 1fr;
    border: solid $accent;
}
#ej-panel {
    height: 50%;
    display: none;
}
#ej-panel.visible {
    display: block;
}
#ej-header {
    height: auto;
    padding: 0 1;
    background: $warning;
}
#ej-title {
    width: 1fr;
    padding: 0;
}
#ej-close {
    min-width: 3;
    width: 3;
    height: 1;
    padding: 0;
    margin: 0;
    border: none;
    background: transparent;
    color: $text;
}
#ej-close:hover {
    background: $error;
    color: $text;
}
#ej-editor {
    height: 1fr;
    border: solid $warning;
}
"""
