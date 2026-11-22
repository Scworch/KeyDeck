import os
import sys
import time
from typing import Any
import warnings

warnings.filterwarnings("ignore")

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
except Exception:
    pass


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
        self._connection_error: Exception | None = None
        self._init_engine()

    @staticmethod
    def _await(task):
        if task is not None and hasattr(task, "GetAwaiter"):
            return task.GetAwaiter().GetResult()
        return task

    def _init_engine(self):
        if not HAS_DLL:
            self._connection_error = WaveLinkConnectionError("Wave Link support libraries are unavailable")
            return
        try:
            self._connection_error = None
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
            if not self.sb_client.IsConnected:
                raise WaveLinkConnectionError("Wave Link connection timed out")
        except Exception as exc:
            self._connection_error = exc
            self.sb_client = None

    def connect(self) -> None:
        """Connect to Wave Link, safely reusing an existing connection."""
        if not self.is_connected():
            self._init_engine()
        if not self.is_connected():
            details = f": {self._connection_error}" if self._connection_error else ""
            raise WaveLinkConnectionError(f"Could not connect to Wave Link{details}") from self._connection_error

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
            except Exception:
                pass

    def is_connected(self) -> bool:
        if self.sb_client:
            return bool(self.sb_client.IsConnected)
        return False

    def get_volume(self, channel_name: str = "Music", mix: str = "local") -> int:
        channel = self._get_channel_state(channel_name)
        if channel is None:
            raise WaveLinkError(f"Wave Link channel was not found: {channel_name}")

        get_volume_method_name = (
            "_3XB3tF1WiHsaYoklgYkvUrRAcqX"
            if mix.lower() in ["local", "monitor"]
            else "_WqwUwaZuBHMERxfKjmqzlkUjF5b"
        )
        try:
            get_volume_method = channel.GetType().GetMethod(get_volume_method_name)
            if get_volume_method is None:
                raise WaveLinkError("Wave Link channel volume method was not found")
            volume = get_volume_method.Invoke(channel, None).Volume
            return max(0, min(100, int(volume)))
        except WaveLinkError:
            raise
        except Exception as exc:
            raise WaveLinkError(f"Could not read Wave Link channel volume: {exc}") from exc

    def _get_channel_state(self, channel_name: str) -> Any | None:
        if not HAS_DLL:
            raise WaveLinkConnectionError("Wave Link support libraries are unavailable")
        if not self.is_connected():
            self.connect()

        full_name = channel_name if "wave link" in channel_name.lower() else f"Wave Link {channel_name}"
        get_channel_method = client_type.GetMethod("_tNJD4usSlBgn8qDaF5lWUzdH5Gh")
        if get_channel_method is None:
            raise WaveLinkError("Wave Link channel lookup method was not found")

        try:
            return self._await(get_channel_method.Invoke(self.sb_client, [full_name]))
        except Exception as exc:
            raise WaveLinkError(f"Could not retrieve Wave Link channel: {exc}") from exc

    def set_volume(self, channel_name: str = "Music", value: int = 50, mix: str = "local") -> int:
        target_vol = max(0, min(100, int(value)))
        full_name = channel_name if "wave link" in channel_name.lower() else f"Wave Link {channel_name}"

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
        except WaveLinkError:
            raise
        except Exception as exc:
            raise WaveLinkError(f"Could not set Wave Link volume: {exc}") from exc

        return target_vol

    def get_channels(self) -> list[str]:
        """Return the available Wave Link mixer channel names."""
        if not HAS_DLL:
            raise WaveLinkConnectionError("Wave Link support libraries are unavailable")
        if not self.is_connected():
            self.connect()

        get_channels_method = client_type.GetMethod("_bABIuvuZl1O55sO9WP4iBwsmRp")
        if get_channels_method is None:
            raise WaveLinkError("Wave Link channel-list method was not found")

        try:
            channels = self._await(
                get_channels_method.Invoke(
                    self.sb_client,
                    [System.Boolean(False)],
                )
            )
            names = {
                str(channel.Name).strip()
                for channel in channels
                if channel.Name and str(channel.Name).strip()
            }
            names = {
                name
                for name in names
                if self._get_channel_state(name) is not None
            }
        except Exception as exc:
            raise WaveLinkError(f"Could not list Wave Link channels: {exc}") from exc

        return sorted(names, key=str.casefold)

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
