# vj

A modal JSON editor built with [Textual](https://github.com/Textualize/textual), featuring vim-style keybindings.

## Features

- **Vim-style modal editing** - Normal, Insert, Command, and Search modes
- **Syntax highlighting** - JSON-aware colorization
- **JSON validation** - Real-time validation with error reporting
- **JSONPath search** - Search using JSONPath expressions (`$.foo.bar`)
- **JSONL support** - Edit JSON Lines files with record-aware navigation
- **Embedded JSON editing** - Edit JSON strings within JSON (nested levels)
- **Bracket matching** - Jump to matching brackets with `%`
- **Undo/Redo** - Full undo history

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Open a file
vj data.json

# Open in read-only mode
vj -R data.json

# Create new file
vj newfile.json
```

## Keybindings

### Movement
| Key | Action |
|-----|--------|
| `h j k l` | Left/Down/Up/Right |
| `w b` | Word forward/backward |
| `0 $ ^` | Line start/end/first char |
| `gg G` | File start/end |
| `%` | Jump to matching bracket |
| `PgUp PgDn` | Page up/down |
| `Ctrl+d/u` | Half page down/up |

### Search
| Key | Action |
|-----|--------|
| `/` | Search forward |
| `?` | Search backward |
| `n N` | Next/previous match |
| `$.` `$[` | JSONPath search (auto-detect) |
| `\j` | JSONPath suffix for patterns |
| `\c \C` | Case insensitive/sensitive |

### Insert Mode
| Key | Action |
|-----|--------|
| `i I` | Insert at cursor/line start |
| `a A` | Append after cursor/line end |
| `o O` | Open line below/above |

### Editing
| Key | Action |
|-----|--------|
| `x` | Delete char |
| `dd` | Delete line |
| `dw d$` | Delete word/to end |
| `cw cc` | Change word/line |
| `r{c}` | Replace char |
| `J` | Join lines |
| `yy p P` | Yank/paste after/before |
| `u` | Undo |
| `Ctrl+r` | Redo |
| `.` | Repeat last edit |
| `ej` | Edit embedded JSON string |

### Commands
| Command | Action |
|---------|--------|
| `:w` | Save |
| `:w {file}` | Save as |
| `:e {file}` | Open file |
| `:fmt` | Format JSON |
| `:q` | Quit |
| `:q!` | Quit (discard changes) |
| `:wq` | Save and quit |
| `:help` | Toggle help panel |

## License

MIT
