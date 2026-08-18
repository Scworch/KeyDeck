import os
import sys
import time
import logging
import warnings

warnings.filterwarnings("ignore")
logger = logging.getLogger("WaveLinkAPI")

plugin_lib_dir = os.path.join(os.path.dirname(__file__), "lib")
if str(plugin_lib_dir) not in sys.path:
    sys.path.insert(0, str(plugin_lib_dir))

HAS_DLL = False
try:
    import clr
    from System.Reflection import Assembly
    import System
    from System import Activator

    def _load_asm(filename):
        path = os.path.join(plugin_lib_dir, filename)
        if not os.path.exists(path):
            sb_fallback = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../Streamer.bot-x64-1.0.4", filename))
            if os.path.exists(sb_fallback):
                path = sb_fallback
        bytes_data = System.IO.File.ReadAllBytes(path)
        return Assembly.Load(bytes_data)

    _load_asm("Common.dll")
    _load_asm("System.Threading.Tasks.Extensions.dll")
    _load_asm("System.Threading.Channels.dll")
    _load_asm("System.Runtime.CompilerServices.Unsafe.dll")
    _load_asm("System.Text.Json.dll")
    _load_asm("Serilog.dll")
    _load_asm("websocket-sharp.dll")
    _load_asm("Newtonsoft.Json.dll")
    _load_asm("Streamer.bot.Common.dll")
    elgato_asm = _load_asm("Streamer.bot.Elgato.dll")

    mixer_enum = elgato_asm.GetType("Streamer.bot.Elgato.WaveLink.Enums.MixerType")
    local_mixer_val = System.Enum.Parse(mixer_enum, "Local")
    stream_mixer_val = System.Enum.Parse(mixer_enum, "Stream")

    client_type = elgato_asm.GetType("_9J8nHIpasSlsUaPNBCNB19VDI1i")
    HAS_DLL = True
    logger.info("Successfully loaded Streamer.bot Elgato DLL engine!")
except Exception as e:
    logger.warning(f"Could not load Streamer.bot Elgato DLL: {e}")


class WaveLinkError(Exception):
    pass

class WaveLinkConnectionError(WaveLinkError):
    pass


class WaveLinkClient:
    """
    Wave Link Client powered directly by Streamer.bot's official Elgato DLL engine.
    Targeting specifically Local Mix (Monitor Mix) or Stream Mix as requested.
    """
    def __init__(self):
        self.sb_client = None
        self._volumes: dict[tuple[str, str], int] = {}
        self._init_engine()

    @staticmethod
    def _await(task):
        if task is not None and hasattr(task, "GetAwaiter"):
            return task.GetAwaiter().GetResult()
        return task

    def _init_engine(self):
        if not HAS_DLL:
            return
        try:
            self.sb_client = Activator.CreateInstance(client_type)
            connect_method = next(
                (client_type.GetMethod(name) for name in (
                    "_F7kiwaGcXGmByNEKQrZXcZvoIOc",
                    "_7nSAE3J7hkKq4QMRFGk8pipU3TN",
                ) if client_type.GetMethod(name) is not None),
                None,
            )
            if connect_method is None:
                raise WaveLinkConnectionError("Wave Link connect method was not found")
            self._await(connect_method.Invoke(self.sb_client, None))
            # The DLL completes its Task before its IsConnected property is
            # updated. Give the websocket state a short, bounded settling time.
            deadline = time.monotonic() + 3.0
            while not self.sb_client.IsConnected and time.monotonic() < deadline:
                time.sleep(0.05)
            if self.sb_client.IsConnected:
                logger.info("Streamer.bot WaveLinkClient connected to Elgato Wave Link!")
            else:
                raise WaveLinkConnectionError("Wave Link connection timed out")
        except Exception as e:
            logger.error(f"Error initializing Streamer.bot DLL engine: {e}")

    def connect(self) -> None:
        """Connect to Wave Link, safely reusing an existing connection."""
        if not self.is_connected():
            self._init_engine()
        if not self.is_connected():
            raise WaveLinkConnectionError("Could not connect to Wave Link")

    def disconnect(self) -> None:
        """Release the underlying .NET client when it supports disposal."""
        client = self.sb_client
        self.sb_client = None
        if client is None:
            return
        for method_name in ("Disconnect", "Close", "Dispose"):
            try:
                method = client.GetType().GetMethod(method_name)
                if method is not None:
                    method.Invoke(client, None)
                    break
            except Exception as exc:  # noqa: BLE001
                logger.debug("Wave Link cleanup method %s failed: %s", method_name, exc)

    def is_connected(self) -> bool:
        if self.sb_client:
            return bool(self.sb_client.IsConnected)
        return False

    def get_volume(self, channel_name: str = "Music", mix: str = "local") -> int:
        return self._volumes.get((channel_name.casefold(), mix.casefold()), 50)

    def set_volume(self, channel_name: str = "Music", value: int = 50, mix: str = "local") -> int:
        target_vol = max(0, min(100, int(value)))
        full_name = channel_name if "wave link" in channel_name.lower() else f"Wave Link {channel_name.capitalize()}"

        if not self.is_connected():
            self.connect()

        if not self.sb_client or not self.sb_client.IsConnected:
            raise WaveLinkConnectionError("Wave Link is not connected")
        try:
            target_mixer = local_mixer_val if mix.lower() in ["local", "monitor"] else stream_mixer_val
            set_vol_method = client_type.GetMethod("_weACe7NGG4CKekW52V5lzi35LEB")
            if set_vol_method is None:
                raise WaveLinkError("Wave Link volume method was not found")
            self._await(set_vol_method.Invoke(self.sb_client, [full_name, target_mixer, System.Int32(target_vol), System.Boolean(False)]))
            self._volumes[(channel_name.casefold(), mix.casefold())] = target_vol
            logger.info("Wave Link: set '%s' (%s mix) to %d%%", full_name, mix, target_vol)
        except WaveLinkError:
            raise
        except Exception as exc:
            raise WaveLinkError(f"Could not set Wave Link volume: {exc}") from exc

        return target_vol

    def increase_volume(self, channel_name: str = "Music", step: int = 5, mix: str = "local") -> int:
        current = self.get_volume(channel_name, mix)
        new_vol = min(100, current + step)
        return self.set_volume(channel_name, new_vol, mix)

    def decrease_volume(self, channel_name: str = "Music", step: int = 5, mix: str = "local") -> int:
        current = self.get_volume(channel_name, mix)
        new_vol = max(0, current - step)
        return self.set_volume(channel_name, new_vol, mix)


_global_client = None

def get_client() -> WaveLinkClient:
    global _global_client
    if _global_client is None:
        _global_client = WaveLinkClient()
    return _global_client

def get_volume(channel_name: str = "Music") -> int:
    return get_client().get_volume(channel_name, mix="local")

def set_volume(channel_name: str, value: int) -> int:
    return get_client().set_volume(channel_name, value, mix="local")

def increase_volume(channel_name: str = "Music", step: int = 5) -> int:
    return get_client().increase_volume(channel_name, step, mix="local")

def decrease_volume(channel_name: str = "Music", step: int = 5) -> int:
    return get_client().decrease_volume(channel_name, step, mix="local")
