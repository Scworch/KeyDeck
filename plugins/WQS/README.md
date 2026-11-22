# WQS — Windows Quick Start

WQS is a configurable KeyDeck plugin. On first load an empty `presets` array is
filled with four editable examples by the versioned settings store.

The **Advanced** editor stores arbitrary JSON, while **New**, **Duplicate**,
**Delete**, and **Save current layout** provide the preset workflow. Presets
contain arbitrary applications and ordered actions (`url`, `command`, `script`,
`wait`, and explicitly guarded `click` actions).

Zapret uses the configured BAT path and optional UAC elevation. NekoBox is only
reported as connected when a configured TUN command and optional status command
return success; opening an executable alone is never reported as a successful
VPN connection. Device battery values come only from configured PowerShell commands or local
Logitech G HUB data, so unavailable values are shown honestly. G HUB devices
are PRO X 2 LIGHTSPEED and G502 X LIGHTSPEED; their normal/off SVG icons are
selected from `icons/`.

Windows desktop UI cannot run before interactive logon. Configure KeyDeck's
existing startup task for earliest user-session startup. WQS does not terminate
Explorer and restores the taskbar on normal close, emergency hotkey, plugin
stop, and process exit.
