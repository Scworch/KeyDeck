from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import struct
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import uuid

from PySide6.QtCore import QThread, Signal

try:
    from .discordconnect_secure_store import SecureCredentialStore
except ImportError:
    from discordconnect_secure_store import SecureCredentialStore


RPC_SCOPES = ("rpc", "rpc.voice.read", "rpc.voice.write", "identify")
REQUIRED_RPC_SCOPES = frozenset({"rpc", "rpc.voice.read", "rpc.voice.write"})
OAUTH_REDIRECT_URI = "http://127.0.0.1"
MAX_RPC_PAYLOAD = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class DiscordRpcError(RuntimeError):
    pass


def make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def filter_guilds(value: object) -> list[dict]:
    rows = value.get("guilds", []) if isinstance(value, dict) else value
    if not isinstance(rows, list):
        return []
    guilds = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        guild_id = str(row.get("id", ""))
        name = row.get("name")
        if not guild_id.isdigit() or not isinstance(name, str) or not name.strip():
            continue
        guilds.append(
            {
                "id": guild_id,
                "name": name,
                "icon_url": row.get("icon_url")
                if isinstance(row.get("icon_url"), str)
                else None,
            }
        )
    return guilds


def filter_voice_channels(value: object) -> list[dict]:
    rows = value.get("channels", []) if isinstance(value, dict) else value
    if not isinstance(rows, list):
        return []
    channels = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != 2:
            continue
        channel_id = str(row.get("id", ""))
        name = row.get("name")
        if not channel_id.isdigit() or not isinstance(name, str) or not name.strip():
            continue
        channels.append({"id": channel_id, "name": name, "type": 2})
    return channels


def encode_rpc_frame(opcode: int, payload: dict) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return struct.pack("<II", opcode, len(encoded)) + encoded


def consume_rpc_frames(buffer: bytearray) -> list[tuple[int, dict]]:
    frames: list[tuple[int, dict]] = []
    while len(buffer) >= 8:
        opcode, payload_length = struct.unpack_from("<II", buffer)
        if payload_length > MAX_RPC_PAYLOAD:
            raise DiscordRpcError("Discord sent an oversized RPC message.")
        frame_length = 8 + payload_length
        if len(buffer) < frame_length:
            break
        payload_bytes = bytes(buffer[8:frame_length])
        del buffer[:frame_length]
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiscordRpcError("Discord sent an invalid RPC message.") from exc
        if not isinstance(payload, dict):
            raise DiscordRpcError("Discord sent an invalid RPC message.")
        frames.append((opcode, payload))
    return frames


class DiscordIpcConnection:
    def __init__(self, handle) -> None:
        self._handle = handle
        self._buffer = bytearray()
        self._closed = False
        self._close_lock = threading.Lock()

    @classmethod
    def open(cls) -> DiscordIpcConnection:
        if os.name != "nt":
            raise DiscordRpcError("Discord RPC through named pipes is available on Windows only.")

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        invalid_handle = ctypes.c_void_p(-1).value
        for index in range(10):
            handle = kernel32.CreateFileW(
                rf"\\?\pipe\discord-ipc-{index}",
                0xC0000000,
                0x3,
                None,
                0x3,
                0x80,
                None,
            )
            if handle not in (None, invalid_handle):
                return cls(handle)
        raise DiscordRpcError(
            "Discord Desktop is not running or its local RPC interface is unavailable."
        )

    def send(self, opcode: int, payload: dict) -> None:
        self._ensure_open()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WriteFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        kernel32.WriteFile.restype = ctypes.c_int
        data = encode_rpc_frame(opcode, payload)
        offset = 0
        while offset < len(data):
            buffer = ctypes.create_string_buffer(data[offset:])
            written = ctypes.c_uint32()
            if not kernel32.WriteFile(
                self._handle,
                buffer,
                len(data) - offset,
                ctypes.byref(written),
                None,
            ):
                raise DiscordRpcError("The Discord RPC connection was interrupted.")
            if written.value <= 0:
                raise DiscordRpcError("The Discord RPC connection was interrupted.")
            offset += written.value

    def read_available(self) -> list[tuple[int, dict]]:
        self._ensure_open()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.PeekNamedPipe.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        kernel32.PeekNamedPipe.restype = ctypes.c_int
        available = ctypes.c_uint32()
        if not kernel32.PeekNamedPipe(
            self._handle,
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        ):
            raise DiscordRpcError("Discord Desktop disconnected from local RPC.")
        if available.value:
            kernel32.ReadFile.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_void_p,
            ]
            kernel32.ReadFile.restype = ctypes.c_int
            chunk_size = min(available.value, 65536)
            buffer = ctypes.create_string_buffer(chunk_size)
            received = ctypes.c_uint32()
            if not kernel32.ReadFile(
                self._handle,
                buffer,
                chunk_size,
                ctypes.byref(received),
                None,
            ):
                raise DiscordRpcError("Discord Desktop disconnected from local RPC.")
            if received.value == 0:
                raise DiscordRpcError("Discord Desktop disconnected from local RPC.")
            self._buffer.extend(buffer.raw[: received.value])
        return consume_rpc_frames(self._buffer)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle(self._handle)

    def _ensure_open(self) -> None:
        if self._closed:
            raise DiscordRpcError("The Discord RPC connection is closed.")


def _friendly_rpc_error(code: object, message: object = "") -> str:
    try:
        error_code = int(code)
    except (TypeError, ValueError):
        error_code = 0
    if error_code == 5003:
        return (
            "You are already in a voice channel. Approve moving to another channel "
            "before trying again."
        )
    if error_code in {4006, 4007, 4009}:
        return "Discord rejected the authorization. Check the Application ID and reconnect."
    if error_code in {4008, 4012}:
        return (
            "Discord does not allow this application to use the requested RPC feature. "
            "Check tester access and Discord's approval requirements."
        )
    if error_code == 5001:
        return "The selected server or channel is no longer available."
    if error_code == 5002:
        return "Discord denied this action. Check your access to that voice channel."
    if error_code == 5004:
        return "Discord could not complete the voice-channel action."
    if error_code == 5005:
        return "Another application currently controls Discord voice settings."
    if error_code == 5006:
        return "Discord could not update voice settings. Reconnect and try again."
    return (
        "Discord rejected the RPC request. RPC and voice scopes may require Discord "
        "approval, and test applications may require tester access. KeyDeck does not "
        "bypass these restrictions."
    )


def _token_request(fields: dict, client_id: str, client_secret: str | None) -> dict:
    data = dict(fields)
    data["client_id"] = client_id
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        encoded = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    request = Request(
        "https://discord.com/api/oauth2/token",
        data=urlencode(data).encode("ascii"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = response.read(1024 * 1024)
    except HTTPError as exc:
        error_name = ""
        try:
            response_body = json.loads(exc.read(65536).decode("utf-8"))
            error_name = str(response_body.get("error", ""))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
        if error_name == "invalid_grant":
            raise DiscordRpcError(
                "Discord authorization expired or was revoked. Reconnect the application."
            ) from None
        if error_name in {"invalid_client", "unauthorized_client"}:
            raise DiscordRpcError(
                "Discord rejected the Application ID or Client Secret. "
                "For secret-free PKCE, enable Public Client in the Developer Portal."
            ) from None
        raise DiscordRpcError(
            "Discord could not complete OAuth authorization. Check the application "
            "settings and registered Redirect URI."
        ) from None
    except (OSError, URLError, TimeoutError):
        raise DiscordRpcError("Discord's authorization service is temporarily unavailable.") from None
    try:
        result = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscordRpcError("Discord returned an invalid OAuth response.") from exc
    if not isinstance(result, dict) or not isinstance(result.get("access_token"), str):
        raise DiscordRpcError("Discord returned an incomplete OAuth response.")
    return result


def _download_image(url: str, destination: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cdn.discordapp.com":
        raise DiscordRpcError("Discord returned an unsupported image address.")
    request = Request(url, headers={"User-Agent": "KeyDeck-DiscordConnect"})
    try:
        with urlopen(request, timeout=8) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname != "cdn.discordapp.com":
                raise DiscordRpcError(
                    "Discord redirected the image request to an unsupported address."
                )
            content_type = response.headers.get_content_type()
            if not content_type.startswith("image/"):
                raise DiscordRpcError("Discord returned an invalid image.")
            content = response.read(MAX_IMAGE_BYTES + 1)
    except (OSError, URLError, TimeoutError):
        raise DiscordRpcError("Discord's image service is temporarily unavailable.") from None
    if len(content) > MAX_IMAGE_BYTES:
        raise DiscordRpcError("Discord's image is too large to display.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary_path.write_bytes(content)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


class DiscordRpcWorker(QThread):
    status_changed = Signal(str, str, object)
    voice_settings_changed = Signal(object)
    selected_channel_changed = Signal(object)
    request_finished = Signal(str, bool, object)
    user_changed = Signal(object)

    def __init__(
        self,
        client_id: str,
        credential_store: SecureCredentialStore,
        cache_dir: Path,
    ) -> None:
        super().__init__()
        self.client_id = client_id
        self.credential_store = credential_store
        self.cache_dir = cache_dir
        self._requests: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._connection: DiscordIpcConnection | None = None
        self._credentials: dict = {}
        self._secret = ""
        self._voice_settings: dict | None = None
        self._ready = False
        self._explicit_disconnect = False
        self._next_reconnect_at = 0.0
        self._reconnect_delay = 2.0
        self._user: dict | None = None
        self._selected_channel: dict | None = None
        self._needs_voice_refresh = False

    def submit(self, kind: str, payload: dict | None = None) -> str:
        request_id = uuid.uuid4().hex
        self._requests.put((request_id, kind, payload or {}))
        return request_id

    def stop_worker(self) -> None:
        self._stop_event.set()
        self._requests.put(("", "stop", {}))
        if self._connection is not None:
            self._connection.close()
        if not self.wait(15000):
            raise RuntimeError("Discord Connect did not stop its background worker.")

    def run(self) -> None:
        try:
            self._credentials = self.credential_store.load()
            self._secret = str(self._credentials.get("client_secret", ""))
            if self._credentials.get("access_token") and self.client_id:
                try:
                    self._connect_and_authenticate()
                except DiscordRpcError as exc:
                    self._handle_connection_error(exc)
            elif self.client_id:
                self._set_status(
                    "authorization_required",
                    "Discord authorization is required.",
                    None,
                )
            else:
                self._set_status("disconnected", "Not connected to Discord.", None)

            while not self._stop_event.is_set():
                self._poll_events()
                if self._needs_voice_refresh and self._ready:
                    self._needs_voice_refresh = False
                    try:
                        self._refresh_voice_settings()
                    except DiscordRpcError as exc:
                        self._handle_connection_error(exc)
                if (
                    not self._ready
                    and self._credentials.get("access_token")
                    and not self._explicit_disconnect
                    and time.monotonic() >= self._next_reconnect_at
                ):
                    try:
                        self._connect_and_authenticate()
                    except DiscordRpcError as exc:
                        self._handle_connection_error(exc)
                try:
                    request_id, kind, payload = self._requests.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == "stop":
                    break
                self._handle_request(request_id, kind, payload)
        except Exception as exc:
            self._set_status(
                "error",
                f"Discord integration stopped: {self._safe_error_text(exc)}",
                None,
            )
        finally:
            self._disconnect_rpc()

    def _handle_request(self, request_id: str, kind: str, payload: dict) -> None:
        try:
            if kind == "authorize":
                self._set_status("authorizing", "Waiting for Discord authorization…", None)
                self._authorize(str(payload.get("client_id", "")), str(payload.get("client_secret", "")))
                self.request_finished.emit(request_id, True, {"kind": kind})
                return
            if kind == "disconnect":
                self._explicit_disconnect = True
                self._disconnect_rpc()
                self._set_status("disconnected", "Discord is disconnected.", self._user)
                self.request_finished.emit(request_id, True, {"kind": kind})
                return
            if kind == "clear_credentials":
                self.credential_store.clear()
                self._explicit_disconnect = True
                self._disconnect_rpc()
                self._credentials = {}
                self._secret = ""
                self.client_id = ""
                self._user = None
                self._voice_settings = None
                self._selected_channel = None
                self.user_changed.emit(None)
                self.voice_settings_changed.emit(None)
                self.selected_channel_changed.emit(None)
                self._set_status("disconnected", "Saved Discord credentials were removed.", None)
                self.request_finished.emit(request_id, True, {"kind": kind})
                return
            if kind == "reconnect":
                self._explicit_disconnect = False
                self._disconnect_rpc()
                self._connect_and_authenticate()
                self.request_finished.emit(request_id, True, {"kind": kind})
                return
            if not self._ready:
                raise DiscordRpcError("Connect Discord before using this action.")
            result = self._handle_rpc_request(kind, payload)
            self.request_finished.emit(request_id, True, result)
        except DiscordRpcError as exc:
            self.request_finished.emit(request_id, False, str(exc))
            if kind == "authorize":
                self._disconnect_rpc()
                self._explicit_disconnect = True
                self._set_status("authorization_required", str(exc), None)
            elif kind == "reconnect" or any(
                marker in str(exc).casefold()
                for marker in ("disconnected", "connection", "timed out", "closed")
            ):
                self._handle_connection_error(exc)
        except (OSError, ValueError):
            message = "Could not access encrypted Discord credentials or local plugin data."
            self.request_finished.emit(request_id, False, message)
            if kind == "authorize":
                self._disconnect_rpc()
                self._explicit_disconnect = True
                self._set_status("authorization_required", message, None)

    def _handle_rpc_request(self, kind: str, payload: dict) -> dict:
        if kind == "guilds":
            response = self._rpc_command("GET_GUILDS", {})
            if not isinstance(response, dict):
                raise DiscordRpcError("Discord returned an invalid server list.")
            return {"kind": kind, "guilds": filter_guilds(response.get("guilds", []))}
        if kind == "channels":
            guild_id = str(payload.get("guild_id", ""))
            if not guild_id.isdigit():
                raise DiscordRpcError("Select a valid Discord server.")
            response = self._rpc_command("GET_CHANNELS", {"guild_id": guild_id})
            if not isinstance(response, dict):
                raise DiscordRpcError("Discord returned an invalid voice-channel list.")
            return {
                "kind": kind,
                "guild_id": guild_id,
                "channels": filter_voice_channels(response.get("channels", [])),
            }
        if kind == "guild_icon":
            guild_id = str(payload.get("guild_id", ""))
            if not guild_id.isdigit():
                raise DiscordRpcError("Select a valid Discord server.")
            guild = self._rpc_command("GET_GUILD", {"guild_id": guild_id})
            icon_url = guild.get("icon_url") if isinstance(guild, dict) else None
            if not icon_url:
                return {"kind": kind, "guild_id": guild_id, "path": None}
            image_url = str(icon_url)
            extension = Path(urlparse(image_url).path).suffix.lower()
            if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                extension = ".png"
            destination = self.cache_dir / f"guild-{guild_id}{extension}"
            _download_image(image_url, destination)
            return {"kind": kind, "guild_id": guild_id, "path": str(destination)}
        if kind == "user_avatar":
            user_id = str(payload.get("user_id", ""))
            avatar_hash = str(payload.get("avatar", ""))
            if not user_id.isdigit() or not re.fullmatch(r"[A-Za-z0-9_]+", avatar_hash):
                raise DiscordRpcError("Discord returned an invalid user avatar.")
            extension = "gif" if avatar_hash.startswith("a_") else "png"
            image_url = (
                f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{extension}"
                "?size=128"
            )
            destination = self.cache_dir / f"user-{user_id}.{extension}"
            _download_image(image_url, destination)
            return {"kind": kind, "path": str(destination)}
        if kind == "join":
            channel_id = str(payload.get("channel_id", ""))
            if not channel_id.isdigit():
                raise DiscordRpcError("Choose a valid voice channel.")
            args = {"channel_id": channel_id}
            if payload.get("force") is True:
                args["force"] = True
            self._rpc_command("SELECT_VOICE_CHANNEL", args)
            response = self._rpc_command("GET_SELECTED_VOICE_CHANNEL", {})
            self._selected_channel = response if isinstance(response, dict) else None
            self.selected_channel_changed.emit(self._selected_channel)
            if (
                not isinstance(self._selected_channel, dict)
                or str(self._selected_channel.get("id", "")) != channel_id
            ):
                raise DiscordRpcError(
                    "Discord did not confirm joining the selected voice channel."
                )
            return {"kind": kind, "channel": self._selected_channel}
        if kind == "leave":
            self._rpc_command("SELECT_VOICE_CHANNEL", {"channel_id": None})
            response = self._rpc_command("GET_SELECTED_VOICE_CHANNEL", {})
            if isinstance(response, dict) and response.get("id"):
                self._selected_channel = response
                self.selected_channel_changed.emit(self._selected_channel)
                raise DiscordRpcError(
                    "Discord did not confirm leaving the current voice channel."
                )
            self._selected_channel = None
            self.selected_channel_changed.emit(None)
            return {"kind": kind}
        if kind in {"toggle_mute", "toggle_deafen"}:
            if self._voice_settings is None:
                self._refresh_voice_settings()
            if self._voice_settings is None:
                raise DiscordRpcError("Discord did not provide the current voice settings.")
            field_name = "mute" if kind == "toggle_mute" else "deaf"
            current_value = self._voice_settings.get(field_name)
            if not isinstance(current_value, bool):
                self._refresh_voice_settings()
                current_value = (
                    self._voice_settings.get(field_name)
                    if self._voice_settings is not None
                    else None
                )
            if not isinstance(current_value, bool):
                raise DiscordRpcError("Discord did not provide the current voice state.")
            response = self._rpc_command(
                "SET_VOICE_SETTINGS",
                {field_name: not current_value},
            )
            if isinstance(response, dict):
                self._set_voice_settings(response)
            self._refresh_voice_settings()
            return {"kind": kind}
        raise DiscordRpcError("This Discord action is not supported.")

    def _authorize(self, client_id: str, client_secret: str) -> None:
        if not client_id.isdigit() or not 16 <= len(client_id) <= 22:
            raise DiscordRpcError("Enter a valid Discord Application ID.")
        self.client_id = client_id
        self._secret = client_secret
        self._credentials = {"client_secret": client_secret} if client_secret else {}
        self._explicit_disconnect = False
        self._disconnect_rpc()
        self._connect_pipe()
        verifier, challenge = make_pkce_pair()
        response = self._rpc_command(
            "AUTHORIZE",
            {
                "client_id": self.client_id,
                "scopes": list(RPC_SCOPES),
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "prompt": "consent",
            },
            timeout=180,
        )
        code = response.get("code") if isinstance(response, dict) else None
        if not isinstance(code, str) or not code:
            raise DiscordRpcError("Discord did not return an authorization code.")
        token = _token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "code_verifier": verifier,
            },
            self.client_id,
            self._secret or None,
        )
        self._save_token_response(token)
        self._authenticate()
        self._initialize_authenticated_connection()

    def _connect_and_authenticate(self) -> None:
        if not self.client_id:
            self._set_status("disconnected", "Enter an Application ID to connect.", None)
            return
        self._set_status("connecting", "Connecting to Discord Desktop…", self._user)
        try:
            self._connect_pipe()
            self._refresh_access_token_if_needed()
            if not self._credentials.get("access_token"):
                self._set_status(
                    "authorization_required",
                    "Discord authorization is required.",
                    None,
                )
                self._disconnect_rpc()
                return
            self._authenticate()
            self._initialize_authenticated_connection()
        except DiscordRpcError:
            self._disconnect_rpc()
            raise

    def _connect_pipe(self) -> None:
        self._disconnect_rpc()
        self._connection = DiscordIpcConnection.open()
        self._connection.send(
            0,
            {"v": 1, "client_id": self.client_id},
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for _opcode, payload in self._connection.read_available():
                if payload.get("evt") == "ERROR":
                    data = payload.get("data") or {}
                    raise DiscordRpcError(
                        _friendly_rpc_error(data.get("code"), data.get("message"))
                    )
                if payload.get("evt") == "READY":
                    return
            time.sleep(0.05)
        raise DiscordRpcError("Discord Desktop did not respond to the RPC handshake.")

    def _authenticate(self) -> None:
        self._refresh_access_token_if_needed()
        access_token = self._credentials.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise DiscordRpcError("Discord authorization is required.")
        try:
            response = self._rpc_command("AUTHENTICATE", {"access_token": access_token})
        except DiscordRpcError as exc:
            if "rejected the authorization" not in str(exc).casefold():
                raise
            self._refresh_access_token_if_needed(force=True)
            access_token = self._credentials.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise DiscordRpcError(
                    "Discord authorization expired. Reconnect the application."
                ) from None
            response = self._rpc_command("AUTHENTICATE", {"access_token": access_token})
        scopes = response.get("scopes", []) if isinstance(response, dict) else []
        granted_scopes = set(scopes) if isinstance(scopes, list) else set()
        missing_scopes = REQUIRED_RPC_SCOPES - granted_scopes
        if missing_scopes:
            raise DiscordRpcError(
                "Discord did not grant the RPC voice scopes required by this plugin. "
                "These scopes may require Discord approval."
            )
        user = response.get("user") if isinstance(response, dict) else None
        self._user = user if isinstance(user, dict) else None
        self.user_changed.emit(self._user)

    def _initialize_authenticated_connection(self) -> None:
        self._voice_settings = None
        self._selected_channel = None
        self._ready = True
        self._explicit_disconnect = False
        self._reconnect_delay = 2.0
        self._set_status("connected", "Connected to Discord.", self._user)
        self._rpc_command("SUBSCRIBE", {}, evt="VOICE_SETTINGS_UPDATE")
        self._rpc_command("SUBSCRIBE", {}, evt="VOICE_CHANNEL_SELECT")
        self._rpc_command("SUBSCRIBE", {}, evt="CURRENT_USER_UPDATE")
        self._refresh_voice_settings()
        self._refresh_selected_channel()
        self._set_status("connected", "Connected to Discord.", self._user)

    def _refresh_access_token_if_needed(self, *, force: bool = False) -> None:
        expires_at = self._credentials.get("expires_at", 0)
        if not isinstance(expires_at, (int, float)):
            expires_at = 0
        if (
            not force
            and self._credentials.get("access_token")
            and expires_at > time.time() + 60
        ):
            return
        refresh_token = self._credentials.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            self._credentials = {}
            self.credential_store.clear()
            raise DiscordRpcError(
                "Discord authorization expired. Reconnect the application."
            )
        token = _token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
            self.client_id,
            self._secret or None,
        )
        self._save_token_response(token)

    def _save_token_response(self, token: dict) -> None:
        expires_in = token.get("expires_in", 0)
        try:
            expires_at = time.time() + max(0, int(expires_in))
        except (TypeError, ValueError):
            expires_at = 0
        self._credentials = {
            "access_token": token["access_token"],
            "refresh_token": token.get(
                "refresh_token",
                self._credentials.get("refresh_token", ""),
            ),
            "expires_at": expires_at,
            "client_secret": self._secret,
        }
        self.credential_store.save(self._credentials)

    def _rpc_command(
        self,
        command: str,
        args: dict,
        *,
        evt: str | None = None,
        timeout: float = 12,
    ) -> dict | None:
        if self._connection is None:
            raise DiscordRpcError("Discord Desktop is not connected through RPC.")
        nonce = uuid.uuid4().hex
        payload: dict = {"cmd": command, "args": args, "nonce": nonce}
        if evt:
            payload["evt"] = evt
        self._connection.send(1, payload)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for _opcode, response in self._connection.read_available():
                self._handle_dispatch(response)
                if response.get("nonce") != nonce:
                    continue
                if response.get("evt") == "ERROR":
                    data = response.get("data") or {}
                    raise DiscordRpcError(
                        _friendly_rpc_error(data.get("code"), data.get("message"))
                    )
                data = response.get("data")
                return data if isinstance(data, dict) else None
            if self._stop_event.is_set():
                raise DiscordRpcError("Discord RPC request was cancelled.")
            time.sleep(0.05)
        raise DiscordRpcError("Discord RPC request timed out. Check Discord Desktop and retry.")

    def _poll_events(self) -> None:
        if self._connection is None:
            return
        try:
            for _opcode, payload in self._connection.read_available():
                self._handle_dispatch(payload)
        except DiscordRpcError as exc:
            if self._ready:
                self._handle_connection_error(exc)

    def _handle_dispatch(self, payload: dict) -> None:
        event = payload.get("evt")
        data = payload.get("data")
        if event == "VOICE_SETTINGS_UPDATE":
            if isinstance(data, dict) and isinstance(data.get("mute"), bool) and isinstance(
                data.get("deaf"), bool
            ):
                self._set_voice_settings(data)
            else:
                self._needs_voice_refresh = True
        elif event == "VOICE_CHANNEL_SELECT" and isinstance(data, dict):
            channel_id = data.get("channel_id")
            guild_id = data.get("guild_id")
            self._selected_channel = (
                {
                    "id": str(channel_id),
                    "guild_id": str(guild_id) if guild_id else None,
                }
                if channel_id
                else None
            )
            self.selected_channel_changed.emit(self._selected_channel)
        elif event == "CURRENT_USER_UPDATE" and isinstance(data, dict):
            self._user = data
            self.user_changed.emit(data)

    def _refresh_voice_settings(self) -> None:
        response = self._rpc_command("GET_VOICE_SETTINGS", {})
        if isinstance(response, dict):
            self._set_voice_settings(response)

    def _set_voice_settings(self, data: dict | None) -> None:
        self._voice_settings = dict(data) if isinstance(data, dict) else None
        self.voice_settings_changed.emit(self._voice_settings)

    def _refresh_selected_channel(self) -> None:
        response = self._rpc_command("GET_SELECTED_VOICE_CHANNEL", {})
        self._selected_channel = response if isinstance(response, dict) else None
        self.selected_channel_changed.emit(self._selected_channel)

    def _handle_connection_error(self, error: DiscordRpcError) -> None:
        self._disconnect_rpc()
        if self._explicit_disconnect or self._stop_event.is_set():
            return
        message = str(error)
        if any(
            phrase in message.casefold()
            for phrase in (
                "authorization expired",
                "authorization was revoked",
                "rejected the authorization",
            )
        ):
            self._credentials = {}
            self._secret = ""
            self.credential_store.clear()
            self._set_status("authorization_required", message, None)
            return
        if "does not allow this application to use the requested rpc feature" in message.casefold():
            self._explicit_disconnect = True
            self._set_status("authorization_required", message, None)
            return
        if "did not grant the rpc voice scopes" in message.casefold():
            self._explicit_disconnect = True
            self._set_status("authorization_required", message, None)
            return
        if "rejected the application id or client secret" in message.casefold():
            self._explicit_disconnect = True
            self._set_status("authorization_required", message, None)
            return
        self._set_voice_settings(None)
        self._selected_channel = None
        self.selected_channel_changed.emit(None)
        self._set_status("reconnecting", message, None)
        self._next_reconnect_at = time.monotonic() + self._reconnect_delay
        self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    def _disconnect_rpc(self) -> None:
        self._ready = False
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()
        self._voice_settings = None
        self._selected_channel = None
        self.voice_settings_changed.emit(None)
        self.selected_channel_changed.emit(None)

    def _set_status(self, state: str, message: str, user: object) -> None:
        self.status_changed.emit(state, message, user)

    @staticmethod
    def _safe_error_text(error: Exception) -> str:
        if isinstance(error, DiscordRpcError):
            return str(error)
        return "An unexpected error occurred. Check the Discord connection and try again."
