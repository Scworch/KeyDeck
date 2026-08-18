import logging
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

# Configure detailed debug logger
log_file = plugin_dir / "wavelink_debug.log"
logger = logging.getLogger("WaveLinkPlugin")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

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
        logger.info("=========================================")
        logger.info("Starting Wave Link Control Plugin...")
        logger.info(f"Log file location: {log_file}")

        channel_name = "Music"
        step = 5
        logger.info("Configuration: F13 -> %s +%d%%, F14 -> %s -%d%%", channel_name, step, channel_name, step)

        self.client = WaveLinkClient()

        try:
            self.client.connect()
            logger.info("Connected to Wave Link!")
        except Exception as e:
            logger.warning(f"Wave Link WebSocket connection info: {e}")

        try:
            # add_hotkey gives exactly one callback per F13/F14 press and avoids
            # matching unrelated keys by scan code.
            self._hotkeys = [
                keyboard.add_hotkey("f13", lambda: self._handle_volume_change(channel_name, step, True)),
                keyboard.add_hotkey("f14", lambda: self._handle_volume_change(channel_name, step, False)),
            ]
            logger.info("F13/F14 hotkeys registered.")
        except Exception as e:
            logger.error(f"Failed to install low-level keyboard hook: {e}")

    def _handle_volume_change(self, channel_name: str, step: int, increase: bool) -> None:
        if self.client is None:
            self.client = WaveLinkClient()

        try:
            with self._volume_lock:
                if not self.client.is_connected():
                    self.client.connect()
                if increase:
                    new_vol = self.client.increase_volume(channel_name, step)
                else:
                    new_vol = self.client.decrease_volume(channel_name, step)
                logger.info("Music local volume changed to %d%%", new_vol)
        except WaveLinkError as exc:
            logger.error("Wave Link volume adjustment failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected Wave Link volume adjustment error: %s", exc)

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

        logger.info("Wave Link Plugin stopped.")
        logger.info("=========================================")

    def actions(self) -> list:
        return []
