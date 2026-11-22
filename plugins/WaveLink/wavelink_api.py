import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
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


class WaveLink35Client:
    """Client for Wave Link 3.x's local JSON-RPC WebSocket API."""

    _fallback_ports = range(1884, 1894)
    _request_timeout = 3.0
    _connect_timeout = 0.25

    def __init__(self) -> None:
        self._ws = None
        self._lock = threading.RLock()
        self._request_id = 0

    def connect(self) -> None:
        with self._lock:
            if self.is_connected():
                return

            last_error: Exception | None = None
            for port in self._candidate_ports():
                try:
                    with socket.create_connection(
                        ("127.0.0.1", port),
                        timeout=self._connect_timeout,
                    ):
                        pass
                except OSError as exc:
                    last_error = exc
                    continue
                try:
                    import websocket

                    self._ws = websocket.create_connection(
                        f"ws://127.0.0.1:{port}",
                        timeout=self._request_timeout,
                        origin="streamdeck://",
                    )
                    application = self._request_unlocked("getApplicationInfo")
                    if (
                        not isinstance(application, dict)
                        or application.get("appID") != "EWL"
                        or int(application.get("interfaceRevision", 0)) < 1
                    ):
                        raise WaveLinkConnectionError(
                            "The connected WebSocket is not a supported Wave Link 3 API"
                        )
                    return
                except Exception as exc:
                    last_error = exc
                    self.disconnect()

            details = f": {last_error}" if last_error else ""
            raise WaveLinkConnectionError(
                f"Could not connect to Wave Link 3.x{details}"
            ) from last_error

    def _candidate_ports(self) -> list[int]:
        ports: list[int] = []
        info_file = self._ws_info_path()
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
            port = int(info.get("port"))
            if 1 <= port <= 65535:
                ports.append(port)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            pass
        ports.extend(port for port in self._fallback_ports if port not in ports)
        return ports

    @staticmethod
    def _ws_info_path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        return (
            Path(local_app_data)
            / "Packages"
            / "Elgato.WaveLink_g54w8ztgkx496"
            / "LocalState"
            / "ws-info.json"
        )

    def disconnect(self) -> None:
        with self._lock:
            ws = self._ws
            self._ws = None
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def is_connected(self) -> bool:
        return bool(self._ws is not None and getattr(self._ws, "connected", False))

    def _request_unlocked(self, method: str, params: dict | None = None) -> Any:
        if self._ws is None:
            raise WaveLinkConnectionError("Wave Link 3.x is not connected")
        self._request_id += 1
        request_id = self._request_id
        self._ws.settimeout(self._request_timeout)
        self._ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
        )
        deadline = time.monotonic() + self._request_timeout
        while time.monotonic() < deadline:
            response = json.loads(self._ws.recv())
            if not isinstance(response, dict) or response.get("id") != request_id:
                continue
            error = response.get("error")
            if isinstance(error, dict):
                raise WaveLinkError(
                    str(error.get("message") or f"Wave Link request failed: {method}")
                )
            return response.get("result")
        raise WaveLinkConnectionError(
            f"Wave Link did not answer the {method} request"
        )

    def _request(self, method: str, params: dict | None = None) -> Any:
        with self._lock:
            if not self.is_connected():
                self.connect()
            try:
                return self._request_unlocked(method, params)
            except WaveLinkError:
                raise
            except Exception as exc:
                self.disconnect()
                raise WaveLinkConnectionError(
                    f"Wave Link 3.x request failed ({method}): {exc}"
                ) from exc

    @staticmethod
    def _normalize_channel_name(name: str) -> str:
        normalized = name.strip()
        if normalized.casefold().startswith("wave link "):
            normalized = normalized[len("Wave Link "):]
        return normalized.casefold()

    def _channels(self) -> list[dict]:
        result = self._request("getChannels")
        channels = result if isinstance(result, list) else (
            result.get("channels") if isinstance(result, dict) else None
        )
        if not isinstance(channels, list):
            raise WaveLinkError("Wave Link 3.x returned an invalid channel list")
        return [channel for channel in channels if isinstance(channel, dict)]

    def get_channels(self) -> list[str]:
        return sorted(
            {
                str(channel.get("name", "")).strip()
                for channel in self._channels()
                if str(channel.get("name", "")).strip()
            },
            key=str.casefold,
        )

    def _find_channel(self, channel_name: str) -> dict:
        target = self._normalize_channel_name(channel_name)
        channel = next(
            (
                item
                for item in self._channels()
                if self._normalize_channel_name(str(item.get("name", ""))) == target
            ),
            None,
        )
        if channel is None:
            raise WaveLinkError(f"Wave Link channel was not found: {channel_name}")
        return channel

    def _find_mix(self, mix: str) -> dict:
        result = self._request("getMixes")
        mixes = result if isinstance(result, list) else (
            result.get("mixes") if isinstance(result, dict) else None
        )
        if not isinstance(mixes, list):
            raise WaveLinkError("Wave Link 3.x returned an invalid mix list")

        mix_key = mix.strip().casefold()
        if mix_key in ("local", "monitor", "personal"):
            mix_names = ("personal mix", "monitor mix", "local mix")
        elif mix_key == "stream":
            mix_names = ("stream mix",)
        else:
            raise WaveLinkError(f"Unsupported Wave Link mix: {mix}")
        for expected_name in mix_names:
            found = next(
                (
                    item
                    for item in mixes
                    if isinstance(item, dict)
                    and str(item.get("name", "")).strip().casefold() == expected_name
                ),
                None,
            )
            if found is not None and found.get("id"):
                return found

        if mix_key in ("local", "monitor", "personal") and mixes:
            first = mixes[0]
            if isinstance(first, dict) and first.get("id"):
                return first
        raise WaveLinkError(f"Wave Link 3.x does not provide the requested {mix} mix")

    def get_volume(self, channel_name: str = "Music", mix: str = "local") -> int:
        channel = self._find_channel(channel_name)
        target_mix = self._find_mix(mix)
        channel_mixes = channel.get("mixes")
        if not isinstance(channel_mixes, list):
            raise WaveLinkError(
                f"Wave Link channel has no volume data for {target_mix.get('name')}"
            )
        state = next(
            (
                item
                for item in channel_mixes
                if isinstance(item, dict) and item.get("id") == target_mix.get("id")
            ),
            None,
        )
        if state is None or not isinstance(state.get("level"), (int, float)):
            raise WaveLinkError(
                f"Wave Link channel {channel_name} is not routed to {target_mix.get('name')}"
            )
        return max(0, min(100, round(float(state["level"]) * 100)))

    def set_volume(
        self,
        channel_name: str = "Music",
        value: int = 50,
        mix: str = "local",
    ) -> int:
        channel = self._find_channel(channel_name)
        target_mix = self._find_mix(mix)
        channel_mixes = channel.get("mixes")
        if not isinstance(channel_mixes, list) or not any(
            isinstance(item, dict) and item.get("id") == target_mix.get("id")
            for item in channel_mixes
        ):
            raise WaveLinkError(
                f"Wave Link channel {channel_name} is not routed to {target_mix.get('name')}"
            )

        target_volume = max(0, min(100, int(value)))
        self._request(
            "setChannel",
            {
                "id": channel.get("id"),
                "mixes": [
                    {
                        "id": target_mix["id"],
                        "level": target_volume / 100,
                    }
                ],
            },
        )
        return target_volume

    def increase_volume(
        self,
        channel_name: str = "Music",
        step: int = 5,
        mix: str = "local",
    ) -> int:
        return self.set_volume(
            channel_name,
            min(100, self.get_volume(channel_name, mix) + step),
            mix,
        )

    def decrease_volume(
        self,
        channel_name: str = "Music",
        step: int = 5,
        mix: str = "local",
    ) -> int:
        return self.set_volume(
            channel_name,
            max(0, self.get_volume(channel_name, mix) - step),
            mix,
        )


def create_client(api_version: str = "3.5") -> WaveLinkClient | WaveLink35Client:
    if api_version == "2.0.6":
        return WaveLinkClient()
    if api_version == "3.5":
        return WaveLink35Client()
    raise ValueError(f"Unsupported Wave Link API version: {api_version}")


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
