# KeyDeck

KeyDeck is a Python desktop app inspired by Stream Deck:
- tray application with a compact deck window
- configurable grid and per-slot action mapping in `CFG`
- squircle buttons with labels and plugin-provided icons
- plugin system (folder-per-plugin) with per-plugin settings

## Requirements

- Windows
- Python 3.11+

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m keydeck
```

## Project Structure

```text
keydeck/                      Core application package
plugins/                      Plugins (one folder per plugin)
  example_hello/
  Steam_Switcher/
  SteamLauncher/
  ResolutionSwitcher/
config/                       App runtime config
icons/                        Optional tray icon assets
```

## Plugin Basics

Each plugin lives in `plugins/<plugin_name>/` and typically includes:
- `manifest.json`
- `plugin.py`
- optional local `settings.json` (ignored in git)

Action binding is configured in `CFG`:
- choose action per slot
- open plugin settings from the slot editor

## Privacy / Local Data

The repository ignores local plugin state by default:
- `plugins/*/settings.json`
- `plugins/*/cache/`

This prevents personal data (for example Steam accounts and local caches) from being committed.
