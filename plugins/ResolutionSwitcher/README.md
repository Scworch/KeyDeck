# ResolutionSwitcher

Two-button plugin:
- switch to saved original mode
- switch to target mode (default: `1920x1440`)

Safety:
- target switch keeps refresh rate from dropping: it selects only display modes
  with `Hz >= current Hz`; otherwise it fails with an error.

Open plugin settings from CFG -> `Plugin settings` on the slot.
