import sys
import threading
from pathlib import Path

# Add plugin dir to sys.path
plugin_dir = Path(__file__).resolve().parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

import keyboard
from keydeck.plugin_api import PluginBase, PluginContext
from wavelink_api import WaveLinkClient, WaveLinkError

class Plugin(PluginBase):
    plugin_id = "wavelink_control"
    plugin_name = "Wave Link Control"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context)
        self.client: WaveLinkClient | None = None
        self._hotkeys: list[object] = []
        self._volume_lock = threading.Lock()

    def start(self) -> None:
        """Starts low-level keyboard hook listener and connects to Wave Link."""
        channel_name = "Music"
        step = 5

        self.client = WaveLinkClient()

        try:
            self.client.connect()
        except Exception:
            pass

        try:
            # add_hotkey gives exactly one callback per F13/F14 press and avoids
            # matching unrelated keys by scan code.
            self._hotkeys = [
                keyboard.add_hotkey("f13", lambda: self._handle_volume_change(channel_name, step, True)),
                keyboard.add_hotkey("f14", lambda: self._handle_volume_change(channel_name, step, False)),
            ]
        except Exception:
            pass

    def _handle_volume_change(self, channel_name: str, step: int, increase: bool) -> None:
        if self.client is None:
            self.client = WaveLinkClient()

        try:
            with self._volume_lock:
                if not self.client.is_connected():
                    self.client.connect()
                if increase:
                    self.client.increase_volume(channel_name, step)
                else:
                    self.client.decrease_volume(channel_name, step)
        except WaveLinkError:
            pass
        except Exception:
            pass

    def stop(self) -> None:
        """Stops keyboard hooks and closes Wave Link connection."""
        for hotkey in self._hotkeys:
            try:
                keyboard.remove_hotkey(hotkey)
            except Exception:
                pass
        self._hotkeys = []

        if self.client:
            self.client.disconnect()
            self.client = None

    def actions(self) -> list:
        return []
