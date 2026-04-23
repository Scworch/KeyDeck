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
