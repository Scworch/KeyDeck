from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl

_PLUGIN_DIR = str(Path(__file__).resolve().parent)
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from keydeck.plugin_api import Action, PluginBase
from discordconnect_rpc import DiscordRpcWorker
from discordconnect_secure_store import SecureCredentialStore


DISCORD_PORTAL = "https://discord.com/developers/applications"
RPC_DOCUMENTATION = "https://discord.com/developers/docs/topics/rpc"
OAUTH_DOCUMENTATION = "https://discord.com/developers/docs/topics/oauth2"
DEFAULT_BUTTON_COLOR = "#5865F2"
OFFLINE_BUTTON_COLOR = "#555b68"
OFF_STATE_COLOR = "#ED4245"


class _PluginUiReceiver(QObject):
    def __init__(self, plugin: Plugin) -> None:
        super().__init__()
        self.plugin = plugin

    @Slot(str, str, object)
    def on_status_changed(self, state: str, message: str, user: object) -> None:
        self.plugin._on_status_changed(state, message, user)

    @Slot(object)
    def on_voice_settings_changed(self, settings: object) -> None:
        self.plugin._on_voice_settings_changed(settings)

    @Slot(object)
    def on_selected_channel_changed(self, channel: object) -> None:
        self.plugin._on_selected_channel_changed(channel)

    @Slot(str, bool, object)
    def on_request_finished(self, request_id: str, success: bool, result: object) -> None:
        self.plugin._on_request_finished(request_id, success, result)

    @Slot(object)
    def on_user_changed(self, user: object) -> None:
        self.plugin._on_user_changed(user)


class Plugin(PluginBase):
    plugin_id = "DiscordConnect"
    plugin_name = "Discord Connect"

    def __init__(self, context=None) -> None:
        super().__init__(context)
        if self.context is None:
            raise RuntimeError("Discord Connect requires a plugin context.")
        self._settings = self.context.load_settings(
            {"client_id": "", "button_color": DEFAULT_BUTTON_COLOR}
        )
        self._settings["button_color"] = self._valid_color(
            self._settings.get("button_color")
        )
        self._settings["client_id"] = str(self._settings.get("client_id", ""))
        self.context.save_settings(self._settings)
        self._data_dir = self.context.writable_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._credential_store = SecureCredentialStore(
            self._data_dir / "credentials.dpapi"
        )
        self._worker: DiscordRpcWorker | None = None
        self._receiver: _PluginUiReceiver | None = None
        self._connection_state = "disconnected"
        self._connection_message = "Not connected to Discord."
        self._saved_auth_available = self._credential_store.path.is_file()
        self._auth_request_id: str | None = None
        self._user: dict | None = None
        self._user_avatar_path: str | None = None
        self._voice_settings: dict | None = None
        self._selected_channel: dict | None = None
        self._guilds: list[dict] = []
        self._channels_by_guild: dict[str, list[dict]] = {}
        self._guild_icon_paths: dict[str, str | None] = {}
        self._pending_guild_icons: set[str] = set()
        self._background_requests: dict[str, tuple[str, str]] = {}
        self._pending_action_requests: dict[str, str] = {}
        self._settings_dialog: DiscordSettingsDialog | None = None
        self._join_dialog: JoinChannelDialog | None = None
        self._credential_removal_request_id: str | None = None
        self._generated_icons = self._data_dir / "generated-icons"
        self._generated_icons.mkdir(parents=True, exist_ok=True)

    @property
    def connected(self) -> bool:
        return self._connection_state == "connected"

    def start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = None
        self._receiver = _PluginUiReceiver(self)
        worker = DiscordRpcWorker(
            self._settings["client_id"],
            self._credential_store,
            self._data_dir / "image-cache",
        )
        worker.status_changed.connect(self._receiver.on_status_changed)
        worker.voice_settings_changed.connect(
            self._receiver.on_voice_settings_changed
        )
        worker.selected_channel_changed.connect(
            self._receiver.on_selected_channel_changed
        )
        worker.request_finished.connect(self._receiver.on_request_finished)
        worker.user_changed.connect(self._receiver.on_user_changed)
        self._worker = worker
        worker.start()

    def stop(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.stop_worker()
            self._worker = None
        self._receiver = None
        self._connection_state = "disconnected"
        self._voice_settings = None
        self._selected_channel = None

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id="DiscordConnect.control",
                title="Discord Connect",
                callback=self._run_control,
                plugin_id=self.plugin_id,
                settings_callback=self.open_settings,
                action_settings_callback=self._edit_control_settings,
                action_icon_callback=self._control_icon,
                action_title_callback=self._control_title,
                icon_mode="fill",
                aliases=[
                    "DiscordConnect.join",
                    "DiscordConnect.leave",
                    "DiscordConnect.mute",
                    "DiscordConnect.deafen",
                ],
                alias_settings_defaults={
                    "DiscordConnect.join": {"mode": "join"},
                    "DiscordConnect.leave": {"mode": "leave"},
                    "DiscordConnect.mute": {"mode": "mute"},
                    "DiscordConnect.deafen": {"mode": "deafen"},
                },
            ),
        ]

    def _run_control(self, settings: dict | None = None) -> None:
        values = settings if isinstance(settings, dict) else {}
        mode = values.get("mode")
        if mode == "join":
            self._join_channel(values)
        elif mode == "leave":
            self._leave_channel(values)
        elif mode == "mute":
            self._toggle_mute(values)
        elif mode == "deafen":
            self._toggle_deafen(values)
        else:
            self._show_action_error(
                "Choose a Discord action in this button's settings first."
            )

    def _control_title(self, slot: int, settings: dict) -> str:
        mode = settings.get("mode")
        if mode == "join":
            return self._join_title(slot, settings)
        if mode == "leave":
            return self._leave_title(slot, settings)
        if mode == "mute":
            return self._mute_title(slot, settings)
        if mode == "deafen":
            return self._deafen_title(slot, settings)
        return "Choose Discord action"

    def _control_icon(self, slot: int, settings: dict) -> str | None:
        mode = settings.get("mode")
        if mode == "join":
            return self._join_icon(slot, settings)
        if mode == "mute":
            return self._mute_icon(slot, settings)
        if mode == "deafen":
            return self._deafen_icon(slot, settings)
        return None

    def _edit_control_settings(self, slot: int, current: dict) -> dict | None:
        modes = [
            ("join", "Join voice channel"),
            ("leave", "Leave voice channel"),
            ("mute", "Toggle mute"),
            ("deafen", "Toggle deafen"),
        ]
        labels = [label for _mode, label in modes]
        current_mode = str(current.get("mode", "join"))
        current_index = next(
            (index for index, (mode, _label) in enumerate(modes) if mode == current_mode),
            0,
        )
        selected, accepted = QInputDialog.getItem(
            QApplication.activeWindow(),
            "Discord button action",
            "Choose what this button should do:",
            labels,
            current_index,
            False,
        )
        if not accepted:
            return None
        mode = modes[labels.index(selected)][0]
        if mode == "join":
            result = self._edit_join_settings(slot, current)
            if result is None:
                return None
            result["mode"] = mode
            return result
        if mode == "leave":
            result = self._edit_leave_settings(slot, current)
            if result is None:
                return None
            return {**result, "mode": mode}
        return {"mode": mode}

    def open_settings(self) -> None:
        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        dialog = DiscordSettingsDialog(self, parent)
        self._settings_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._settings_dialog = None

    def _join_channel(self, settings: dict | None = None) -> None:
        values = settings if isinstance(settings, dict) else {}
        channel_id = str(values.get("channel_id", ""))
        if not channel_id.isdigit():
            self._show_action_error("Configure a Discord server and voice channel first.")
            return
        if not self._require_connection():
            return
        selected_id = (
            str(self._selected_channel.get("id", ""))
            if isinstance(self._selected_channel, dict)
            else ""
        )
        force = False
        if selected_id == channel_id:
            return
        if selected_id:
            result = QMessageBox.question(
                QApplication.activeWindow(),
                "Move Discord to another channel?",
                "You are already in a voice channel. Move to the selected channel?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                return
            force = True
        self._submit_action("join", {"channel_id": channel_id, "force": force})

    def _leave_channel(self, _settings: dict | None = None) -> None:
        if not self._require_connection():
            return
        if self._selected_channel is None:
            return
        self._submit_action("leave")

    def _toggle_mute(self, _settings: dict | None = None) -> None:
        self._toggle_voice_setting("toggle_mute", "Mute")

    def _toggle_deafen(self, _settings: dict | None = None) -> None:
        self._toggle_voice_setting("toggle_deafen", "Deafen")

    def _toggle_voice_setting(self, kind: str, name: str) -> None:
        if not self._require_connection():
            return
        if not isinstance(self._voice_settings, dict):
            self._show_action_error(
                f"Discord voice status is not available. Reconnect and try {name} again."
            )
            return
        if kind in self._pending_action_requests.values():
            return
        self._submit_action(kind)

    def _submit_action(self, kind: str, payload: dict | None = None) -> None:
        if self._worker is None:
            self._show_action_error("Discord Connect is not running.")
            return
        request_id = self._worker.submit(kind, payload)
        self._pending_action_requests[request_id] = kind

    def _submit_background(self, kind: str, payload: dict) -> None:
        if self._worker is None:
            return
        request_id = self._worker.submit(kind, payload)
        value_id = str(payload.get("guild_id") or payload.get("user_id") or "")
        self._background_requests[request_id] = (kind, value_id)

    def _require_connection(self) -> bool:
        if self.connected and self._worker is not None:
            return True
        self._show_action_error("Connect Discord from the plugin settings first.")
        return False

    def _join_title(self, _slot: int, _settings: dict) -> str:
        return ""

    def _leave_title(self, _slot: int, settings: dict) -> str:
        return str(settings.get("custom_title") or "Leave Channel")

    def _mute_title(self, _slot: int, _settings: dict) -> str:
        if not self.connected:
            return "Discord offline"
        muted = self._voice_settings.get("mute") if self._voice_settings else None
        return "Unmute" if muted is True else "Mute" if muted is False else "Syncing…"

    def _deafen_title(self, _slot: int, _settings: dict) -> str:
        if not self.connected:
            return "Discord offline"
        deafened = self._voice_settings.get("deaf") if self._voice_settings else None
        return (
            "Undeafen"
            if deafened is True
            else "Deafen"
            if deafened is False
            else "Syncing…"
        )

    def _mute_icon(self, _slot: int, _settings: dict) -> str:
        muted = self._voice_settings.get("mute") if self._voice_settings else None
        state = (
            "offline"
            if not self.connected
            else "unknown"
            if not isinstance(muted, bool)
            else "off"
            if muted
            else "on"
        )
        return self._make_state_icon("mic", state)

    def _deafen_icon(self, _slot: int, _settings: dict) -> str:
        deafened = self._voice_settings.get("deaf") if self._voice_settings else None
        state = (
            "offline"
            if not self.connected
            else "unknown"
            if not isinstance(deafened, bool)
            else "off"
            if deafened
            else "on"
        )
        return self._make_state_icon("headphones", state)

    def _make_state_icon(self, name: str, state: str) -> str:
        color = self._settings["button_color"]
        icon_name = (
            "headphone-off.svg"
            if name == "headphones" and state == "off"
            else f"{name}{'-off' if state == 'off' else ''}.svg"
        )
        icon_path = Path(__file__).with_name(icon_name)
        if not icon_path.is_file():
            raise FileNotFoundError(f"Required Discord icon is missing: {icon_name}")
        source = icon_path.read_text(encoding="utf-8")
        _root, separator, body = source.partition(">")
        if not separator or "</svg>" not in body:
            raise ValueError(f"Invalid Discord SVG resource: {icon_name}")
        body = body.rsplit("</svg>", 1)[0]
        foreground = OFF_STATE_COLOR if state == "off" else "#FFFFFF"
        background = (
            OFFLINE_BUTTON_COLOR if state in {"offline", "unknown"} else color
        )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" '
            'viewBox="0 0 24 24">'
            f'<rect width="24" height="24" rx="3" fill="{background}"/>'
            '<g transform="translate(5 5) scale(0.58)" fill="none" '
            f'stroke="{foreground}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</g></svg>'
        )
        digest = hashlib.sha256(
            f"{name}:{state}:{color}:{svg}".encode("utf-8")
        ).hexdigest()
        destination = self._generated_icons / f"{digest}.svg"
        if not destination.is_file():
            destination.write_text(svg, encoding="utf-8")
        return str(destination)

    def _join_icon(self, _slot: int, settings: dict) -> str:
        guild_id = str(settings.get("guild_id", ""))
        channel_id = str(settings.get("channel_id", ""))
        guild_name = self._name_for_id(self._guilds, guild_id, settings.get("guild_name"))
        channel_name = self._name_for_id(
            self._channels_by_guild.get(guild_id, []),
            channel_id,
            settings.get("channel_name"),
        )
        title = str(settings.get("custom_title") or channel_name or "Join channel")
        if guild_id and guild_id not in self._guild_icon_paths and guild_id not in self._pending_guild_icons:
            if self.connected and self._worker is not None:
                self._pending_guild_icons.add(guild_id)
                self._submit_background("guild_icon", {"guild_id": guild_id})
        icon_path = self._guild_icon_paths.get(guild_id)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "guild": guild_id,
                    "channel": channel_id,
                    "title": title,
                    "color": self._settings["button_color"],
                    "icon": icon_path,
                    "mtime": (
                        Path(icon_path).stat().st_mtime_ns
                        if icon_path and Path(icon_path).is_file()
                        else 0
                    ),
                    "connected": self.connected,
                },
                ensure_ascii=True,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        destination = self._generated_icons / f"join-{digest}.png"
        if not destination.is_file():
            self._render_join_icon(destination, title, icon_path)
        return str(destination)

    def _render_join_icon(self, destination: Path, title: str, icon_path: str | None) -> None:
        image = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(self._settings["button_color"]))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if icon_path and Path(icon_path).is_file():
            avatar = QImage(icon_path)
            if not avatar.isNull():
                scaled = avatar.scaled(
                    512,
                    512,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                source_x = max(0, (scaled.width() - 512) // 2)
                source_y = max(0, (scaled.height() - 512) // 2)
                painter.drawImage(
                    0,
                    0,
                    scaled,
                    source_x,
                    source_y,
                    512,
                    512,
                )
                painter.fillRect(0, 0, 512, 512, QColor(0, 0, 0, 105))
        else:
            painter.fillRect(0, 0, 512, 512, QColor(self._settings["button_color"]))
        if not self.connected:
            painter.setBrush(QColor(160, 35, 40, 225))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(340, 442, 150, 48, 10, 10)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Segoe UI", 19, QFont.DemiBold))
            painter.drawText(348, 474, "Offline")
        text_bottom = 420 if not self.connected else 480
        self._draw_fitted_text(painter, title, top=32, bottom=text_bottom)
        painter.end()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(destination), "PNG"):
            raise OSError("Could not render the Discord channel button.")

    @staticmethod
    def _draw_fitted_text(
        painter: QPainter,
        text: str,
        *,
        top: int = 32,
        bottom: int = 480,
    ) -> None:
        text = " ".join(text.split()) or "Join channel"
        max_width = 440
        max_height = bottom - top
        selected_font = QFont("Segoe UI", 16, QFont.DemiBold)
        selected_lines: list[str] = [text]
        for size in range(64, 6, -1):
            font = QFont("Segoe UI", size, QFont.DemiBold)
            metrics = QFontMetrics(font)
            lines: list[str] = []
            line = ""
            for word in text.split(" "):
                chunks: list[str] = []
                chunk = ""
                for character in word:
                    candidate = chunk + character
                    if chunk and metrics.horizontalAdvance(candidate) > max_width:
                        chunks.append(chunk)
                        chunk = character
                    else:
                        chunk = candidate
                if chunk:
                    chunks.append(chunk)
                for piece in chunks:
                    candidate = f"{line} {piece}".strip()
                    if line and metrics.horizontalAdvance(candidate) > max_width:
                        lines.append(line)
                        line = piece
                    else:
                        line = candidate
            if line:
                lines.append(line)
            line_height = metrics.height() + 8
            if (
                all(metrics.horizontalAdvance(item) <= max_width for item in lines)
                and len(lines) * line_height <= max_height
            ):
                selected_font = font
                selected_lines = lines
                break
        painter.setFont(selected_font)
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        metrics = QFontMetrics(selected_font)
        line_height = metrics.height() + 8
        total_height = len(selected_lines) * line_height
        y = top + (max_height - total_height) // 2 + metrics.ascent()
        for line in selected_lines:
            painter.drawText(
                36,
                y,
                440,
                line_height,
                Qt.AlignHCenter | Qt.AlignVCenter,
                line,
            )
            y += line_height

    @staticmethod
    def _name_for_id(rows: list[dict], item_id: str, fallback: object) -> str:
        for row in rows:
            if str(row.get("id")) == item_id:
                return str(row.get("name", ""))
        return str(fallback) if isinstance(fallback, str) else ""

    def _edit_join_settings(self, slot: int, current: dict) -> dict | None:
        dialog = JoinChannelDialog(self, slot, current)
        self._join_dialog = dialog
        if self._worker is not None and self.connected:
            dialog.request_guilds()
        try:
            if dialog.exec() != QDialog.Accepted:
                return None
            return dialog.result_settings()
        finally:
            self._join_dialog = None

    def _edit_leave_settings(self, _slot: int, current: dict) -> dict | None:
        dialog = ButtonTitleDialog(
            "Leave Channel button",
            "Button name (optional):",
            str(current.get("custom_title", "")),
        )
        if dialog.exec() != QDialog.Accepted:
            return None
        title = dialog.title_value()
        return {"custom_title": title} if title else {}

    def _on_status_changed(self, state: str, message: str, user: object) -> None:
        self._connection_state = state
        self._connection_message = message
        if state == "connected":
            self._saved_auth_available = True
        elif state == "authorization_required":
            self._saved_auth_available = False
            if self._auth_request_id is not None:
                self._auth_request_id = None
                if self._settings_dialog is not None:
                    self._settings_dialog.set_auth_pending(False)
        elif state == "error":
            if self._auth_request_id is not None:
                self._auth_request_id = None
                if self._settings_dialog is not None:
                    self._settings_dialog.set_auth_pending(False)
            self._pending_action_requests.clear()
            self._background_requests.clear()
            self._pending_guild_icons.clear()
            if self._credential_removal_request_id is not None:
                self._credential_removal_request_id = None
                if self._settings_dialog is not None:
                    self._settings_dialog.show_request_error(message)
        if isinstance(user, dict):
            self._user = user
        elif state in {"authorization_required", "disconnected", "error"}:
            self._user = None
        if state != "connected":
            self._voice_settings = None
            self._selected_channel = None
        self._refresh_actions()
        if self._settings_dialog is not None:
            self._settings_dialog.update_connection(state, message, self._user)
        if self._join_dialog is not None:
            self._join_dialog.update_connection(state == "connected", message)

    def _on_voice_settings_changed(self, settings: object) -> None:
        self._voice_settings = settings if isinstance(settings, dict) else None
        self._refresh_actions()

    def _on_selected_channel_changed(self, channel: object) -> None:
        self._selected_channel = channel if isinstance(channel, dict) else None

    def _on_user_changed(self, user: object) -> None:
        self._user = user if isinstance(user, dict) else None
        if (
            self._user
            and self._user.get("id")
            and self._user.get("avatar")
            and self._worker is not None
        ):
            self._submit_background(
                "user_avatar",
                {
                    "user_id": self._user["id"],
                    "avatar": self._user["avatar"],
                },
            )
        if self._settings_dialog is not None:
            self._settings_dialog.update_user(self._user, self._user_avatar_path)

    def _on_request_finished(
        self,
        request_id: str,
        success: bool,
        result: object,
    ) -> None:
        background_request = self._background_requests.pop(request_id, None)
        if background_request and background_request[0] == "guild_icon" and not success:
            self._pending_guild_icons.discard(background_request[1])
        if request_id and request_id == self._credential_removal_request_id:
            self._credential_removal_request_id = None
            if success:
                self._finish_credential_removal()
            elif self._settings_dialog is not None:
                self._settings_dialog.show_request_error(str(result))
        if request_id and request_id == self._auth_request_id:
            self._auth_request_id = None
            if self._settings_dialog is not None:
                self._settings_dialog.set_auth_pending(False)
        if success and isinstance(result, dict):
            kind = result.get("kind")
            if kind == "guilds":
                self._guilds = list(result.get("guilds", []))
                if self._settings_dialog is not None:
                    self._settings_dialog.update_guilds(self._guilds)
                if self._join_dialog is not None:
                    self._join_dialog.update_guilds(self._guilds)
            elif kind == "channels":
                guild_id = str(result.get("guild_id", ""))
                self._channels_by_guild[guild_id] = list(result.get("channels", []))
                if self._settings_dialog is not None:
                    self._settings_dialog.update_channels(guild_id, self._channels_by_guild[guild_id])
                if self._join_dialog is not None:
                    self._join_dialog.update_channels(guild_id, self._channels_by_guild[guild_id])
            elif kind == "guild_icon":
                guild_id = str(result.get("guild_id", ""))
                path = result.get("path")
                self._guild_icon_paths[guild_id] = str(path) if path else None
                self._pending_guild_icons.discard(guild_id)
                self._refresh_actions()
            elif kind == "user_avatar":
                path = result.get("path")
                self._user_avatar_path = str(path) if path else None
                if self._settings_dialog is not None:
                    self._settings_dialog.update_user(self._user, self._user_avatar_path)
        elif not success:
            message = str(result)
            if request_id in self._pending_action_requests:
                self._pending_action_requests.pop(request_id, None)
                self._show_action_error(message)
            elif self._settings_dialog is not None:
                self._settings_dialog.show_request_error(message)
            if self._join_dialog is not None:
                self._join_dialog.show_request_error(message)
        action_kind = self._pending_action_requests.pop(request_id, None)
        if action_kind == "join" and success and isinstance(result, dict):
            channel = result.get("channel")
            if isinstance(channel, dict):
                self._selected_channel = channel

    def _show_action_error(self, message: str) -> None:
        QMessageBox.warning(
            QApplication.activeWindow(),
            "Discord Connect",
            message,
        )

    def _refresh_actions(self) -> None:
        if self.context is not None and self.context.refresh_actions is not None:
            self.context.refresh_actions()

    def _connect(self, client_id: str, client_secret: str) -> bool:
        client_id = client_id.strip()
        if not re.fullmatch(r"\d{16,22}", client_id):
            if self._settings_dialog is not None:
                self._settings_dialog.status.setText("Enter a valid Discord Application ID.")
            QMessageBox.warning(
                QApplication.activeWindow(),
                "Discord Connect",
                "Enter a valid Discord Application ID.",
            )
            return False
        previous_client_id = self._settings["client_id"]
        self._settings["client_id"] = client_id
        if not self._save_plugin_settings():
            self._settings["client_id"] = previous_client_id
            return False
        if self._worker is None or not self._worker.isRunning():
            self.start()
        if self._worker is not None:
            self._auth_request_id = self._worker.submit(
                "authorize",
                {"client_id": client_id, "client_secret": client_secret},
            )
            if self._settings_dialog is not None:
                self._settings_dialog.set_auth_pending(True)
        return True

    def _reconnect(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            self.start()
            return
        if self._worker is not None:
            self._worker.submit("reconnect")

    def _disconnect(self) -> None:
        if self._worker is not None:
            self._worker.submit("disconnect")

    def _remove_credentials(self) -> None:
        answer = QMessageBox.question(
            QApplication.activeWindow(),
            "Remove Discord credentials?",
            "This removes the saved OAuth credentials and Application ID. "
            "Discord access can also be revoked in Discord's Authorized Apps settings. "
            "Button configurations and the button color will be kept.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self._worker is not None and self._worker.isRunning():
            self._credential_removal_request_id = self._worker.submit(
                "clear_credentials"
            )
            if self._settings_dialog is not None:
                self._settings_dialog.connection_status.setText(
                    "Removing saved Discord credentials…"
                )
            return
        try:
            self._credential_store.clear()
        except OSError as exc:
            self._show_action_error(
                f"Could not remove the encrypted Discord credentials: {exc}"
            )
            return
        self._finish_credential_removal()

    def _finish_credential_removal(self) -> None:
        self._settings["client_id"] = ""
        self._save_plugin_settings()
        self._saved_auth_available = False
        self._guilds.clear()
        self._channels_by_guild.clear()
        self._guild_icon_paths.clear()
        self._user_avatar_path = None
        self._user = None
        self._voice_settings = None
        self._selected_channel = None
        self._connection_state = "disconnected"
        self._connection_message = "Saved Discord credentials were removed."
        if self._settings_dialog is not None:
            self._settings_dialog.clear_credentials_fields()
            self._settings_dialog.update_connection(
                self._connection_state,
                self._connection_message,
                None,
            )
        self._refresh_actions()

    @staticmethod
    def _valid_color(value: object) -> str:
        color = QColor(str(value))
        return color.name(QColor.HexRgb).upper() if color.isValid() else DEFAULT_BUTTON_COLOR

    def _set_button_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        previous_color = self._settings["button_color"]
        self._settings["button_color"] = color.name(QColor.HexRgb).upper()
        if not self._save_plugin_settings():
            self._settings["button_color"] = previous_color
            return
        self._refresh_actions()

    def _save_plugin_settings(self) -> bool:
        try:
            self.context.save_settings(self._settings)
        except OSError as exc:
            self._show_action_error(
                f"Could not save Discord Connect settings: {exc}"
            )
            return False
        return True


class JoinChannelDialog(QDialog):
    def __init__(self, plugin: Plugin, slot: int, current: dict) -> None:
        super().__init__(QApplication.activeModalWidget() or QApplication.activeWindow())
        self.plugin = plugin
        self.slot = slot
        self.current = dict(current)
        self.setWindowTitle("Configure Join Channel")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose a Discord server and a voice channel."))
        form = QFormLayout()
        self.guilds = QComboBox(self)
        self.channels = QComboBox(self)
        self.custom_title = QLineEdit(str(current.get("custom_title", "")), self)
        self.custom_title.setMaxLength(80)
        self.custom_title.setPlaceholderText("Defaults to the selected channel name")
        form.addRow("Server:", self.guilds)
        form.addRow("Voice channel:", self.channels)
        form.addRow("Button name:", self.custom_title)
        layout.addLayout(form)
        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh_button = QPushButton("Refresh servers and channels", self)
        layout.addWidget(self.refresh_button)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        layout.addWidget(self.buttons)
        self.guilds.currentIndexChanged.connect(self._on_guild_selected)
        self.refresh_button.clicked.connect(self.request_guilds)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.update_guilds(plugin._guilds)
        self.update_connection(plugin.connected, plugin._connection_message)

    def request_guilds(self) -> None:
        if self.plugin._worker is None or not self.plugin.connected:
            self.status.setText("Connect Discord before refreshing servers.")
            return
        self.status.setText("Loading Discord servers…")
        self.plugin._worker.submit("guilds")

    def update_guilds(self, guilds: list[dict]) -> None:
        current_id = str(self.current.get("guild_id", ""))
        selected = str(self.guilds.currentData() or current_id)
        if not selected:
            selected = current_id
        self.guilds.blockSignals(True)
        self.guilds.clear()
        for guild in guilds:
            self.guilds.addItem(guild["name"], guild["id"])
        index = self.guilds.findData(selected)
        if index >= 0:
            self.guilds.setCurrentIndex(index)
        self.guilds.blockSignals(False)
        if self.guilds.count():
            self._load_channels(str(self.guilds.currentData()))

    def update_channels(self, guild_id: str, channels: list[dict]) -> None:
        if str(self.guilds.currentData() or "") != guild_id:
            return
        selected = str(self.current.get("channel_id", ""))
        self.channels.clear()
        for channel in channels:
            self.channels.addItem(channel["name"], channel["id"])
        index = self.channels.findData(selected)
        if index >= 0:
            self.channels.setCurrentIndex(index)
        self.status.setText(
            f"{len(channels)} supported voice channel(s) loaded."
            if channels
            else "No supported voice channels were found on this server."
        )

    def update_connection(self, connected: bool, message: str) -> None:
        self.refresh_button.setEnabled(connected)
        self.guilds.setEnabled(connected)
        self.channels.setEnabled(connected)
        if not connected:
            self.status.setText(message)

    def show_request_error(self, message: str) -> None:
        self.status.setText(message)

    def _on_guild_selected(self, _index: int) -> None:
        guild_id = str(self.guilds.currentData() or "")
        self.current["guild_id"] = guild_id
        self.current["channel_id"] = ""
        if guild_id in self.plugin._channels_by_guild:
            self.update_channels(guild_id, self.plugin._channels_by_guild[guild_id])
        elif self.plugin._worker is not None and self.plugin.connected and guild_id:
            self.status.setText("Loading voice channels…")
            self.plugin._worker.submit("channels", {"guild_id": guild_id})
        else:
            self.channels.clear()

    def _load_channels(self, guild_id: str) -> None:
        if guild_id in self.plugin._channels_by_guild:
            self.update_channels(guild_id, self.plugin._channels_by_guild[guild_id])
        elif self.plugin._worker is not None and self.plugin.connected:
            self.status.setText("Loading voice channels…")
            self.plugin._worker.submit("channels", {"guild_id": guild_id})

    def result_settings(self) -> dict:
        guild_id = str(self.guilds.currentData() or "")
        channel_id = str(self.channels.currentData() or "")
        guild_name = self.guilds.currentText()
        channel_name = self.channels.currentText()
        custom_title = self.custom_title.text().strip()
        return {
            "guild_id": guild_id,
            "guild_name": guild_name,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "custom_title": custom_title,
        }


class ButtonTitleDialog(QDialog):
    def __init__(self, title: str, label: str, current: str) -> None:
        super().__init__(QApplication.activeModalWidget() or QApplication.activeWindow())
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        self.line_edit = QLineEdit(current, self)
        self.line_edit.setMaxLength(80)
        layout.addWidget(QLabel(label))
        layout.addWidget(self.line_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def title_value(self) -> str:
        return self.line_edit.text().strip()


class DiscordSettingsDialog(QDialog):
    def __init__(self, plugin: Plugin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle("Discord Connect settings")
        self.setMinimumWidth(520)
        self.setMinimumHeight(500)
        root = QVBoxLayout(self)
        self.pages = QStackedWidget(self)
        root.addWidget(self.pages)
        self.setup_page = self._build_setup_page()
        self.connected_page = self._build_connected_page()
        self.pages.addWidget(self.setup_page)
        self.pages.addWidget(self.connected_page)
        self.update_connection(
            plugin._connection_state,
            plugin._connection_message,
            plugin._user,
        )
        self.update_guilds(plugin._guilds)
        self.update_user(plugin._user, plugin._user_avatar_path)

    def _build_setup_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        heading = QLabel("Connect your Discord application")
        heading.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(heading)
        instructions = QLabel(
            "1. Open Discord Developer Portal and create a New Application.\n"
            "2. Copy its Application ID (Client ID) from General Information.\n"
            "3. Add this Redirect URI under OAuth2 → Redirects:\n"
            f"   {self._redirect_uri()}\n"
            "4. Local Discord IPC does not use an RPC Origin. A Client Secret is optional; "
            "PKCE is used for the desktop authorization flow. Without a secret, enable "
            "Public Client in the Developer Portal."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        link_row = QHBoxLayout()
        portal = QPushButton("Discord Developer Portal", page)
        portal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DISCORD_PORTAL)))
        rpc_docs = QPushButton("RPC documentation", page)
        rpc_docs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RPC_DOCUMENTATION)))
        oauth_docs = QPushButton("OAuth2 documentation", page)
        oauth_docs.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(OAUTH_DOCUMENTATION))
        )
        link_row.addWidget(portal)
        link_row.addWidget(rpc_docs)
        link_row.addWidget(oauth_docs)
        layout.addLayout(link_row)
        form = QFormLayout()
        self.client_id = QLineEdit(str(self.plugin._settings.get("client_id", "")), page)
        self.client_id.setPlaceholderText("Discord Application ID")
        self.client_secret = QLineEdit("", page)
        self.client_secret.setEchoMode(QLineEdit.Password)
        self.client_secret.setPlaceholderText("Optional; not required for PKCE")
        self.show_secret = QCheckBox("Show Client Secret", page)
        self.show_secret.toggled.connect(
            lambda visible: self.client_secret.setEchoMode(
                QLineEdit.Normal if visible else QLineEdit.Password
            )
        )
        secret_row = QHBoxLayout()
        secret_row.addWidget(self.client_secret, 1)
        secret_row.addWidget(self.show_secret)
        form.addRow("Application ID:", self.client_id)
        form.addRow("Client Secret:", secret_row)
        layout.addLayout(form)
        access_note = QLabel(
            "Discord restricts RPC and voice scopes to approved applications. "
            "A test application may also require your account to be on its tester list. "
            "This plugin does not bypass Discord access controls."
        )
        access_note.setWordWrap(True)
        access_note.setStyleSheet("color: #e6b450;")
        layout.addWidget(access_note)
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Mute / deafen button color:"))
        self.setup_color_button = QPushButton(
            self.plugin._settings["button_color"], page
        )
        self.setup_color_button.clicked.connect(self._choose_color)
        self.setup_color_button.setStyleSheet(
            f"background-color: {self.plugin._settings['button_color']}; color: white;"
        )
        color_row.addWidget(self.setup_color_button)
        color_row.addStretch(1)
        layout.addLayout(color_row)
        self.status = QLabel(self.plugin._connection_message, page)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.connect_button = QPushButton("Connect Discord", page)
        self.connect_button.clicked.connect(self._connect)
        layout.addWidget(self.connect_button)
        clear_credentials = QPushButton("Remove saved Discord credentials", page)
        clear_credentials.clicked.connect(self.plugin._remove_credentials)
        layout.addWidget(clear_credentials)
        layout.addStretch(1)
        return page

    def _build_connected_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        heading = QLabel("Discord connection")
        heading.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(heading)
        self.connection_status = QLabel("", page)
        self.connection_status.setWordWrap(True)
        layout.addWidget(self.connection_status)
        user_row = QHBoxLayout()
        self.avatar = QLabel("DC", page)
        self.avatar.setFixedSize(56, 56)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(
            "background: #5865F2; color: white; border-radius: 28px; font-weight: bold;"
        )
        self.user_name = QLabel("Discord user", page)
        user_row.addWidget(self.avatar)
        user_row.addWidget(self.user_name, 1)
        layout.addLayout(user_row)
        buttons = QHBoxLayout()
        self.reconnect_button = QPushButton("Reconnect", page)
        self.reconnect_button.clicked.connect(self.plugin._reconnect)
        self.disconnect_button = QPushButton("Disconnect", page)
        self.disconnect_button.clicked.connect(self.plugin._disconnect)
        buttons.addWidget(self.reconnect_button)
        buttons.addWidget(self.disconnect_button)
        layout.addLayout(buttons)
        server_heading = QLabel("Available Discord voice channels")
        server_heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(server_heading)
        self.guilds = QComboBox(page)
        self.channels = QComboBox(page)
        self.guilds.currentIndexChanged.connect(self._guild_changed)
        list_form = QFormLayout()
        list_form.addRow("Server:", self.guilds)
        list_form.addRow("Voice channel:", self.channels)
        layout.addLayout(list_form)
        self.refresh_lists_button = QPushButton("Refresh servers and channels", page)
        self.refresh_lists_button.clicked.connect(self._refresh_guilds)
        layout.addWidget(self.refresh_lists_button)
        self.list_status = QLabel("", page)
        self.list_status.setWordWrap(True)
        layout.addWidget(self.list_status)
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Mute / deafen button color:"))
        self.color_button = QPushButton(self.plugin._settings["button_color"], page)
        self.color_button.clicked.connect(self._choose_color)
        self.color_button.setStyleSheet(
            f"background-color: {self.plugin._settings['button_color']}; color: white;"
        )
        color_row.addWidget(self.color_button)
        color_row.addStretch(1)
        layout.addLayout(color_row)
        self.remove_credentials_button = QPushButton(
            "Remove saved Discord credentials", page
        )
        self.remove_credentials_button.clicked.connect(self.plugin._remove_credentials)
        layout.addWidget(self.remove_credentials_button)
        note = QLabel(
            "Discord RPC currently allows only one app to modify voice settings at a time. "
            "Discord may reset voice settings when the controlling RPC app disconnects."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    @staticmethod
    def _redirect_uri() -> str:
        from discordconnect_rpc import OAUTH_REDIRECT_URI

        return OAUTH_REDIRECT_URI

    def _connect(self) -> None:
        self.status.setText("Waiting for Discord authorization…")
        if self.plugin._connect(
            self.client_id.text(),
            self.client_secret.text(),
        ):
            self.client_secret.clear()

    def set_auth_pending(self, pending: bool) -> None:
        self.connect_button.setEnabled(not pending)

    def _refresh_guilds(self) -> None:
        if self.plugin._worker is None or not self.plugin.connected:
            self.list_status.setText("Connect to Discord before refreshing lists.")
            return
        self.list_status.setText("Loading Discord servers…")
        self.plugin._worker.submit("guilds")

    def _guild_changed(self, _index: int) -> None:
        guild_id = str(self.guilds.currentData() or "")
        if not guild_id:
            self.channels.clear()
            return
        cached = self.plugin._channels_by_guild.get(guild_id)
        if cached is not None:
            self.update_channels(guild_id, cached)
        elif self.plugin._worker is not None and self.plugin.connected:
            self.list_status.setText("Loading voice channels…")
            self.plugin._worker.submit("channels", {"guild_id": guild_id})

    def update_connection(self, state: str, message: str, user: dict | None) -> None:
        self.connection_status.setText(message)
        self.refresh_lists_button.setEnabled(state == "connected")
        self.guilds.setEnabled(state == "connected")
        self.channels.setEnabled(state == "connected")
        self.disconnect_button.setEnabled(state in {"connected", "reconnecting"})
        self.reconnect_button.setEnabled(
            state not in {"connecting", "authorizing"}
            and bool(self.plugin._settings.get("client_id"))
        )
        if state == "connected":
            self.pages.setCurrentWidget(self.connected_page)
        elif self.plugin._saved_auth_available and state in {
            "disconnected",
            "connecting",
            "reconnecting",
        }:
            self.pages.setCurrentWidget(self.connected_page)
        elif state in {"authorization_required", "error"}:
            self.pages.setCurrentWidget(self.setup_page)
            self.status.setText(message)
        else:
            self.pages.setCurrentWidget(self.setup_page)
            self.status.setText(message)
        self.update_user(user, self.plugin._user_avatar_path)

    def update_user(self, user: dict | None, avatar_path: str | None) -> None:
        if not hasattr(self, "user_name"):
            return
        if not isinstance(user, dict):
            self.user_name.setText("Discord user not connected")
            self.avatar.setPixmap(QPixmap())
            self.avatar.setText("DC")
            return
        name = user.get("global_name") or user.get("username") or "Discord user"
        self.user_name.setText(str(name))
        if avatar_path and Path(avatar_path).is_file():
            pixmap = QPixmap(avatar_path).scaled(
                56,
                56,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            self.avatar.setPixmap(pixmap)
            self.avatar.setText("")
        else:
            self.avatar.setPixmap(QPixmap())
            self.avatar.setText(str(name)[:2].upper())

    def clear_credentials_fields(self) -> None:
        self.client_id.clear()
        self.client_secret.clear()

    def update_guilds(self, guilds: list[dict]) -> None:
        selected = str(self.guilds.currentData() or "")
        self.guilds.blockSignals(True)
        self.guilds.clear()
        for guild in guilds:
            self.guilds.addItem(guild["name"], guild["id"])
        index = self.guilds.findData(selected)
        if index >= 0:
            self.guilds.setCurrentIndex(index)
        self.guilds.blockSignals(False)
        if self.guilds.count():
            self._guild_changed(self.guilds.currentIndex())
        else:
            self.channels.clear()
            self.list_status.setText("No Discord servers were returned.")

    def update_channels(self, guild_id: str, channels: list[dict]) -> None:
        if str(self.guilds.currentData() or "") != guild_id:
            return
        self.channels.clear()
        for channel in channels:
            self.channels.addItem(channel["name"], channel["id"])
        self.list_status.setText(
            f"{len(channels)} supported voice channel(s) loaded."
            if channels
            else "No supported voice channels were found on this server."
        )

    def show_request_error(self, message: str) -> None:
        self.list_status.setText(message)
        self.status.setText(message)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self.plugin._settings["button_color"]),
            self,
            "Choose Discord button color",
        )
        if color.isValid():
            self.plugin._set_button_color(color)
            self.color_button.setText(self.plugin._settings["button_color"])
            self.color_button.setStyleSheet(
                f"background-color: {self.plugin._settings['button_color']}; color: white;"
            )
            self.setup_color_button.setText(self.plugin._settings["button_color"])
            self.setup_color_button.setStyleSheet(
                f"background-color: {self.plugin._settings['button_color']}; color: white;"
            )


__all__ = ["Plugin"]
