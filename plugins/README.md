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

WQS is an unfinished experimental plugin and is not included in public release builds.

Wave Link Control:
- Choose the Wave Link API in plugin settings: Wave Link 3.5 is selected by default; choose 2.0.6 for the legacy API. The 3.5 adapter talks directly to Wave Link's local WebSocket API; the legacy adapter continues using the bundled Streamer.bot libraries, so downloading Streamer.bot is not required.
- Configure the Wave Link channel, volume step, and the two increase/decrease hotkeys in the plugin settings.
- Wheel calibration captures keyboard/media-key events only. The PRO X 2 volume wheel emits HID Consumer Control reports, which require a device filter driver to suppress before Windows changes its volume.
- Configured hotkeys are intercepted globally while KeyDeck is running. Debug mode writes recognized volume-key events and Wave Link errors to `%LOCALAPPDATA%\KeyDeck\plugins\WaveLink\wavelink-debug.log` in release builds (or `plugins/WaveLink/wavelink-debug.log` from source); unrelated keystrokes are not recorded.
