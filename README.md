# KeyDeck

Python skeleton for a StreamDeck-like desktop app with:
- tray icon launcher
- mini deck window in screen corner
- configurable button grid
- squircle-like buttons with labels
- top-right settings button
- plugin folders as standalone components

## Project Layout

```text
KeyDeck/
  keydeck/                  # app package
    ui/                     # Qt UI widgets
  plugins/                  # plugin components (folder-per-plugin)
    example_hello/
  icons/                    # tray/app icons
  config/                   # runtime config
  run_keydeck.cmd           # launch through .venv
  create_shortcut.ps1       # recreate KeyDeck.lnk shortcut
```

## Quick Start

1. Create and activate venv:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
$env:PYTHONUTF8='1'  # helpful on Windows when project path has Cyrillic chars
python -m pip install -r requirements.txt
```

3. Run:

```powershell
python -m keydeck
```

Or use:

```powershell
.\run_keydeck.cmd
```

## Plugins

Each plugin is a separate folder in `plugins/` and should contain `plugin.py`.
The loader expects a `Plugin` class with an `actions()` method.
Script-based plugins are also supported through `manifest.json` (`entry` file is executed on click).
Each plugin can define its own settings JSON via manifest field `settings`.
