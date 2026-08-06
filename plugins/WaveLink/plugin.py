import logging
import sys
import json
from pathlib import Path

# Add plugin dir to sys.path
plugin_dir = Path(__file__).resolve().parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

import keyboard
from keydeck.plugin_api import PluginBase, PluginContext, Action
from wavelink_api import WaveLinkClient, WaveLinkConnectionError, WaveLinkError

# Configure detailed debug logger
log_file = plugin_dir / "wavelink_debug.log"
logger = logging.getLogger("WaveLinkPlugin")
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(str(log_file), encoding="utf-8")
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
fh.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(fh)

class Plugin(PluginBase):
    plugin_id = "wavelink_control"
    plugin_name = "Wave Link Control"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context)
        self.client: WaveLinkClient | None = None
        self._unhook_fn = None

    def start(self) -> None:
        """Starts low-level keyboard hook listener and connects to Wave Link."""
        logger.info("=========================================")
        logger.info("Starting Wave Link Control Plugin...")
        logger.info(f"Log file location: {log_file}")

        default_settings = {
            "channel_name": "Music",
            "step": 5,
            "hotkey_increase": "f13",
            "hotkey_decrease": "f14",
            "vk_increase": 124,
            "vk_decrease": 125,
            "debug_all_keys": True
        }
        
        # Load or populate settings.json
        if self.context:
            settings = self.context.load_settings(default_settings)
            if not settings:
                settings = default_settings
                self.context.save_settings(settings)
        else:
            settings = default_settings
        
        channel_name = settings.get("channel_name", "Music")
        step = int(settings.get("step", 5))
        hk_inc = str(settings.get("hotkey_increase", "f13")).lower()
        hk_dec = str(settings.get("hotkey_decrease", "f14")).lower()
        vk_inc = settings.get("vk_increase", 124)
        vk_dec = settings.get("vk_decrease", 125)
        debug_all = settings.get("debug_all_keys", True)

        logger.info(f"Configuration loaded: channel='{channel_name}', step={step}%")
        logger.info(f"Increase triggers: name='{hk_inc}', vk={vk_inc}")
        logger.info(f"Decrease triggers: name='{hk_dec}', vk={vk_dec}")

        self.client = WaveLinkClient()

        try:
            self.client.connect()
            logger.info("Connected to Wave Link!")
        except Exception as e:
            logger.warning(f"Wave Link WebSocket connection info: {e}")

        def on_key_event(event: keyboard.KeyboardEvent):
            if event.event_type != keyboard.KEY_DOWN:
                return

            event_name = (event.name or "").lower()
            event_vk = getattr(event, "vk", None)
            event_scan = getattr(event, "scan_code", None)

            if debug_all:
                logger.debug(f"[KEY PRESS] name='{event_name}', vk={event_vk}, scan_code={event_scan}")

            is_inc = (event_name == hk_inc) or (event_vk is not None and event_vk == vk_inc) or (event_scan == 100)
            is_dec = (event_name == hk_dec) or (event_vk is not None and event_vk == vk_dec) or (event_scan == 101)

            if is_inc:
                logger.info(f"MATCH: Increase Hotkey Pressed (name='{event_name}', scan_code={event_scan})")
                self._handle_volume_change(channel_name, step, increase=True)

            elif is_dec:
                logger.info(f"MATCH: Decrease Hotkey Pressed (name='{event_name}', scan_code={event_scan})")
                self._handle_volume_change(channel_name, step, increase=False)

        try:
            self._unhook_fn = keyboard.hook(on_key_event)
            logger.info("Low-level keyboard hook active and listening for key events.")
        except Exception as e:
            logger.error(f"Failed to install low-level keyboard hook: {e}")

    def _handle_volume_change(self, channel_name: str, step: int, increase: bool) -> None:
        if self.client is None:
            self.client = WaveLinkClient()

        try:
            if increase:
                new_vol = self.client.increase_volume(channel_name, step)
                logger.info(f"-> Increased '{channel_name}' volume by +{step}% -> New Level: {new_vol}%")
            else:
                new_vol = self.client.decrease_volume(channel_name, step)
                logger.info(f"-> Decreased '{channel_name}' volume by -{step}% -> New Level: {new_vol}%")
        except Exception as e:
            logger.error(f"Volume adjustment error: {e}")

    def stop(self) -> None:
        """Stops keyboard hooks and closes Wave Link connection."""
        if self._unhook_fn:
            try:
                keyboard.unhook(self._unhook_fn)
            except Exception:
                pass
            self._unhook_fn = None

        if self.client:
            self.client.disconnect()
            self.client = None

        logger.info("Wave Link Plugin stopped.")
        logger.info("=========================================")

    def actions(self) -> list[Action]:
        return []
