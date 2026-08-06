# SteamLauncher

Single-action-type plugin that can be assigned many times via profiles.

Each profile defines:
- `title` (button label)
- `steam_id` (app/game id)
- `launch_args` (optional)
- `icon_zoom`, `icon_offset_x`, `icon_offset_y` (position tuning)

Game logo:
- For numeric Steam IDs, plugin tries to load **client icon** (`.ico`) that is
  used in Steam game list (left mini icon) via `clienticon` hash.
- If client icon is unavailable, plugin falls back to `logo.png` and then `header.jpg`.
- Images are cached in `plugins/SteamLauncher/cache/`.
- Cached image is used as button background/icon.

Usage:
1. Assign any `SteamLauncher.*` action in CFG.
2. Open `Plugin settings` and add/edit profiles.
3. Use live preview in settings to align icon exactly.
4. Reload plugins (or restart app) to refresh action list.
