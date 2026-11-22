# Plugins

Each plugin must be a separate folder component:

```text
plugins/
  your_plugin/
    plugin.py or your_script.py
    manifest.json
    settings.json   # or custom name from manifest
```

Supported modes:
- Class plugin:
  - `entry` points to file with `Plugin` class (inherits `PluginBase`)
  - `actions()` returns list of `Action`
- Script plugin:
  - `entry` points to executable Python script
  - KeyDeck creates one action and runs this script on button click

Manifest fields:
- `id` plugin id (optional, defaults to folder name)
- `name` display name on button (optional)
- `entry` plugin entry file (optional for class mode, default `plugin.py`)
- `settings` plugin settings JSON file name (optional, default `settings.json`)
- `args` optional list of script args; placeholders:
  - `{settings_file}`
  - `{plugin_dir}`

CFG integration:
- In KeyDeck CFG window you can bind each slot to a specific action (`action_id`).
- `Plugin settings` button opens settings for plugin of the selected slot action.

WQS:
- `WQS/` provides a fullscreen Windows Quick Start launcher with configurable
  presets, commands, network toggles, device battery commands, and click zones.
- Open the WQS settings editor and bind `WQS.launcher` to a KeyDeck slot.

Wave Link Control:
- Configure the Wave Link channel, volume step, and the two increase/decrease hotkeys in the plugin settings.
- Wheel calibration captures keyboard/media-key events only. The PRO X 2 volume wheel emits HID Consumer Control reports, which require a device filter driver to suppress before Windows changes its volume.
- Configured hotkeys are intercepted globally while KeyDeck is running. Debug mode writes recognized volume-key events and Wave Link errors to `%LOCALAPPDATA%\KeyDeck\plugins\WaveLink\wavelink-debug.log` in release builds (or `plugins/WaveLink/wavelink-debug.log` from source); unrelated keystrokes are not recorded.
