from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext


@dataclass
class LaunchProfile:
    profile_id: str
    title: str
    steam_id: str
    launch_args: str = ""
    icon_zoom: float = 1.0
    icon_offset_x: int = 0
    icon_offset_y: int = 0

    @classmethod
    def from_dict(cls, data: dict, idx: int) -> "LaunchProfile":
        pid = str(data.get("profile_id", "")).strip() or f"profile_{idx + 1}"
        title = str(data.get("title", "")).strip() or f"Steam Launch {idx + 1}"
        steam_id = str(data.get("steam_id", "")).strip()
        launch_args = str(data.get("launch_args", "")).strip()
        icon_zoom = float(data.get("icon_zoom", 1.0))
        icon_offset_x = int(data.get("icon_offset_x", 0))
        icon_offset_y = int(data.get("icon_offset_y", 0))
        return cls(
            profile_id=pid,
            title=title,
            steam_id=steam_id,
            launch_args=launch_args,
            icon_zoom=max(0.2, min(icon_zoom, 3.0)),
            icon_offset_x=max(-80, min(icon_offset_x, 80)),
            icon_offset_y=max(-80, min(icon_offset_y, 80)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class IconPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(140, 150)
        self._title = "Preview"
        self._pixmap = QPixmap()
        self._zoom = 1.0
        self._offset_x = 0
        self._offset_y = 0

    def set_preview(
        self,
        title: str,
        icon_path: str | None,
        zoom: float,
        offset_x: int,
        offset_y: int,
    ) -> None:
        self._title = title or "Preview"
        self._zoom = max(0.2, min(zoom, 3.0))
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._pixmap = QPixmap()
        if icon_path:
            icon = QIcon(icon_path)
            if not icon.isNull():
                pm = icon.pixmap(256, 256)
                if not pm.isNull():
                    self._pixmap = QPixmap.fromImage(pm.toImage())
                    self._pixmap.setDevicePixelRatio(1.0)
                else:
                    raw = QPixmap(icon_path)
                    self._pixmap = QPixmap.fromImage(raw.toImage()) if not raw.isNull() else QPixmap()
            else:
                raw = QPixmap(icon_path)
                self._pixmap = QPixmap.fromImage(raw.toImage()) if not raw.isNull() else QPixmap()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        _ = event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        p.fillRect(self.rect(), QColor("#0f1115"))

        button_size = 84
        btn_rect = QRectF(
            (self.width() - button_size) / 2,
            14,
            button_size,
            button_size,
        )
        radius = 24

        shape = QPainterPath()
        shape.addRoundedRect(btn_rect, radius, radius)
        p.fillPath(shape, QColor("#2a2a2a"))

        if not self._pixmap.isNull():
            p.save()
            p.setClipPath(shape)
            scaled = self._pixmap.scaled(
                int(btn_rect.width() * 0.74 * self._zoom),
                int(btn_rect.height() * 0.74 * self._zoom),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            target = QRectF(0.0, 0.0, float(scaled.width()), float(scaled.height()))
            target.moveCenter(
                QPointF(
                    btn_rect.center().x() + self._offset_x,
                    btn_rect.center().y() + self._offset_y,
                )
            )
            source = QRectF(0.0, 0.0, float(scaled.width()), float(scaled.height()))
            p.drawPixmap(target, scaled, source)
            p.restore()

        p.setPen(QPen(QColor("#3a3a3a"), 1))
        p.drawPath(shape)

        p.setPen(QColor("#d8d8d8"))
        metrics = QFontMetrics(p.font())
        title = metrics.elidedText(self._title, Qt.ElideRight, self.width() - 12)
        p.drawText(QRectF(6, 108, self.width() - 12, 28), Qt.AlignCenter, title)


class SettingsDialog(QDialog):
    def __init__(
        self,
        profiles: list[LaunchProfile],
        icon_resolver: Callable[[str], str | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("SteamLauncher settings")
        self.setModal(True)
        self.setMinimumWidth(860)
        self.setMinimumHeight(520)
        self._profiles = profiles
        self._icon_resolver = icon_resolver
        self._icon_cache: dict[str, str | None] = {}

        main = QVBoxLayout(self)
        row = QHBoxLayout()
        main.addLayout(row)

        self.list_widget = QListWidget(self)
        row.addWidget(self.list_widget, 1)

        editor_wrap = QVBoxLayout()
        row.addLayout(editor_wrap, 2)

        form = QFormLayout()
        editor_wrap.addLayout(form)

        self.title_edit = QLineEdit(self)
        form.addRow("Button title", self.title_edit)

        self.steam_id_edit = QLineEdit(self)
        self.steam_id_edit.setPlaceholderText("Game/App Steam ID, e.g. 730")
        form.addRow("Steam ID", self.steam_id_edit)

        self.args_edit = QLineEdit(self)
        self.args_edit.setPlaceholderText("Optional launch args")
        form.addRow("Launch args", self.args_edit)

        self.zoom_spin = QDoubleSpinBox(self)
        self.zoom_spin.setRange(0.2, 3.0)
        self.zoom_spin.setSingleStep(0.05)
        self.zoom_spin.setDecimals(2)
        form.addRow("Icon zoom", self.zoom_spin)

        self.offset_x_spin = QSpinBox(self)
        self.offset_x_spin.setRange(-80, 80)
        form.addRow("Icon offset X", self.offset_x_spin)

        self.offset_y_spin = QSpinBox(self)
        self.offset_y_spin.setRange(-80, 80)
        form.addRow("Icon offset Y", self.offset_y_spin)

        self.preview = IconPreviewWidget(self)
        editor_wrap.addWidget(self.preview, alignment=Qt.AlignLeft)

        hint = QLabel(
            "Live preview: adjust Zoom / Offset to center icon exactly as you want.",
            self,
        )
        hint.setWordWrap(True)
        editor_wrap.addWidget(hint)
        editor_wrap.addStretch(1)

        action_row = QHBoxLayout()
        main.addLayout(action_row)

        add_btn = QPushButton("Add profile", self)
        add_btn.clicked.connect(self._add_profile)
        action_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove profile", self)
        remove_btn.clicked.connect(self._remove_profile)
        action_row.addWidget(remove_btn)
        action_row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

        self.title_edit.textEdited.connect(self._on_editor_changed)
        self.steam_id_edit.textEdited.connect(self._on_editor_changed)
        self.args_edit.textEdited.connect(self._on_editor_changed)
        self.zoom_spin.valueChanged.connect(self._on_editor_changed)
        self.offset_x_spin.valueChanged.connect(self._on_editor_changed)
        self.offset_y_spin.valueChanged.connect(self._on_editor_changed)
        self.list_widget.currentRowChanged.connect(self._load_profile_to_editor)

        self._refresh_list()
        if self._profiles:
            self.list_widget.setCurrentRow(0)

    def profiles(self) -> list[LaunchProfile]:
        return self._profiles

    def _refresh_list(self) -> None:
        current = self.list_widget.currentRow()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for idx, profile in enumerate(self._profiles):
            name = profile.title.strip() or f"Profile {idx + 1}"
            sid = profile.steam_id.strip() or "no steam id"
            self.list_widget.addItem(f"{name} [{sid}]")
        self.list_widget.blockSignals(False)
        if self._profiles:
            self.list_widget.setCurrentRow(max(0, min(current, len(self._profiles) - 1)))
        else:
            self.title_edit.clear()
            self.steam_id_edit.clear()
            self.args_edit.clear()
            self.zoom_spin.setValue(1.0)
            self.offset_x_spin.setValue(0)
            self.offset_y_spin.setValue(0)
            self.preview.set_preview("Preview", None, 1.0, 0, 0)

    def _add_profile(self) -> None:
        idx = len(self._profiles) + 1
        self._profiles.append(
            LaunchProfile(
                profile_id=f"profile_{idx}",
                title=f"Steam Launch {idx}",
                steam_id="730",
                launch_args="",
                icon_zoom=1.0,
                icon_offset_x=0,
                icon_offset_y=0,
            )
        )
        self._refresh_list()
        self.list_widget.setCurrentRow(len(self._profiles) - 1)

    def _remove_profile(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        del self._profiles[row]
        self._refresh_list()

    def _load_profile_to_editor(self, row: int) -> None:
        if row < 0 or row >= len(self._profiles):
            return
        p = self._profiles[row]
        self.title_edit.blockSignals(True)
        self.steam_id_edit.blockSignals(True)
        self.args_edit.blockSignals(True)
        self.zoom_spin.blockSignals(True)
        self.offset_x_spin.blockSignals(True)
        self.offset_y_spin.blockSignals(True)

        self.title_edit.setText(p.title)
        self.steam_id_edit.setText(p.steam_id)
        self.args_edit.setText(p.launch_args)
        self.zoom_spin.setValue(p.icon_zoom)
        self.offset_x_spin.setValue(p.icon_offset_x)
        self.offset_y_spin.setValue(p.icon_offset_y)

        self.title_edit.blockSignals(False)
        self.steam_id_edit.blockSignals(False)
        self.args_edit.blockSignals(False)
        self.zoom_spin.blockSignals(False)
        self.offset_x_spin.blockSignals(False)
        self.offset_y_spin.blockSignals(False)
        self._update_preview()

    def _on_editor_changed(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        p = self._profiles[row]
        p.title = self.title_edit.text().strip()
        p.steam_id = self.steam_id_edit.text().strip()
        p.launch_args = self.args_edit.text().strip()
        p.icon_zoom = float(self.zoom_spin.value())
        p.icon_offset_x = int(self.offset_x_spin.value())
        p.icon_offset_y = int(self.offset_y_spin.value())
        self._refresh_list()
        self.list_widget.setCurrentRow(row)
        self._update_preview()

    def _update_preview(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._profiles):
            self.preview.set_preview("Preview", None, 1.0, 0, 0)
            return
        p = self._profiles[row]
        icon = self._icon_for_steam_id(p.steam_id)
        self.preview.set_preview(
            p.title.strip() or "Steam Launch",
            icon,
            p.icon_zoom,
            p.icon_offset_x,
            p.icon_offset_y,
        )

    def _icon_for_steam_id(self, steam_id: str) -> str | None:
        sid = steam_id.strip()
        if not sid:
            return None
        if sid in self._icon_cache:
            return self._icon_cache[sid]
        icon = self._icon_resolver(sid)
        self._icon_cache[sid] = icon
        return icon


class Plugin(PluginBase):
    plugin_id = "SteamLauncher"
    plugin_name = "Steam Launcher"

    def __init__(self, context: PluginContext | None = None) -> None:
        super().__init__(context=context)
        self._profiles = self._load_profiles()
        if not self._profiles:
            self._profiles = [
                LaunchProfile(
                    profile_id="profile_1",
                    title="Steam Launch",
                    steam_id="730",
                    launch_args="",
                    icon_zoom=1.0,
                    icon_offset_x=0,
                    icon_offset_y=0,
                )
            ]
            self._save_profiles()

    def actions(self) -> list[Action]:
        actions: list[Action] = []
        for idx, profile in enumerate(self._profiles):
            title = profile.title.strip() or f"Steam Launch {idx + 1}"
            icon_path = self._resolve_game_icon(profile.steam_id)
            actions.append(
                Action(
                    action_id=f"{self.plugin_id}.{profile.profile_id}",
                    title=title,
                    callback=lambda p=profile: self._launch(p),
                    plugin_id=self.plugin_id,
                    settings_callback=self.open_settings,
                    icon_path=icon_path,
                    icon_mode="centered",
                    icon_zoom=profile.icon_zoom,
                    icon_offset_x=profile.icon_offset_x,
                    icon_offset_y=profile.icon_offset_y,
                )
            )
        return actions

    def open_settings(self) -> None:
        profiles = [LaunchProfile(**p.to_dict()) for p in self._profiles]
        dialog = SettingsDialog(
            profiles=profiles,
            icon_resolver=self._resolve_game_icon,
        )
        if not dialog.exec():
            return

        updated = dialog.profiles()
        for idx, p in enumerate(updated):
            if not p.profile_id.strip():
                p.profile_id = f"profile_{idx + 1}"
            p.profile_id = p.profile_id.replace(" ", "_").lower()
            p.title = p.title.strip() or f"Steam Launch {idx + 1}"
            p.steam_id = p.steam_id.strip()
            p.launch_args = p.launch_args.strip()
            p.icon_zoom = max(0.2, min(float(p.icon_zoom), 3.0))
            p.icon_offset_x = max(-80, min(int(p.icon_offset_x), 80))
            p.icon_offset_y = max(-80, min(int(p.icon_offset_y), 80))

        if not updated:
            QMessageBox.warning(None, "SteamLauncher", "At least one profile is required.")
            return

        self._profiles = updated
        self._save_profiles()
        QMessageBox.information(
            None,
            "SteamLauncher",
            "Saved. Reload plugins or restart KeyDeck to refresh actions list.",
        )

    def _launch(self, profile: LaunchProfile) -> None:
        steam_id = profile.steam_id.strip()
        if not steam_id:
            raise RuntimeError(f"Profile '{profile.title}' has empty Steam ID")

        args = profile.launch_args.strip()
        if args:
            encoded = urllib.parse.quote(args, safe="")
            uri = f"steam://rungameid/{steam_id}//{encoded}"
        else:
            uri = f"steam://rungameid/{steam_id}"
        os.startfile(uri)

    def _load_profiles(self) -> list[LaunchProfile]:
        if not self.context:
            return []
        raw = self.context.load_settings(default={"profiles": []})
        profiles_raw = raw.get("profiles", [])
        if not isinstance(profiles_raw, list):
            return []
        profiles: list[LaunchProfile] = []
        for idx, item in enumerate(profiles_raw):
            if isinstance(item, dict):
                profiles.append(LaunchProfile.from_dict(item, idx))
        return profiles

    def _save_profiles(self) -> None:
        if not self.context:
            return
        self.context.save_settings(
            {
                "profiles": [p.to_dict() for p in self._profiles],
            }
        )

    def _resolve_game_icon(self, steam_id: str) -> str | None:
        appid = steam_id.strip()
        if not appid.isdigit():
            return None

        cache_dir = self._logo_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Prefer client icon assets for list-style mini icon quality.
        client_cached = [
            cache_dir / f"{appid}_clienticon.png",
            cache_dir / f"{appid}_clienticon.ico",
        ]
        for candidate in client_cached:
            if candidate.exists():
                return str(candidate)

        client_icon_hash = self._fetch_client_icon_hash(appid)
        if client_icon_hash:
            local_steam_games_ico = self._steam_games_ico_path(client_icon_hash)
            if local_steam_games_ico is not None and local_steam_games_ico.exists():
                converted = self._convert_ico_to_png(local_steam_games_ico, appid)
                return converted or str(local_steam_games_ico)

            ico_url = (
                "https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/"
                f"{appid}/{client_icon_hash}.ico"
            )
            ico_file = cache_dir / f"{appid}_clienticon.ico"
            if ico_file.exists():
                converted = self._convert_ico_to_png(ico_file, appid)
                return converted or str(ico_file)
            if self._download_to_file(ico_url, ico_file):
                converted = self._convert_ico_to_png(ico_file, appid)
                return converted or str(ico_file)

        # Fallbacks for apps missing clienticon.
        fallback_cached = [
            cache_dir / f"{appid}_logo.png",
            cache_dir / f"{appid}_logo.jpg",
            cache_dir / f"{appid}_header.jpg",
        ]
        for candidate in fallback_cached:
            if candidate.exists():
                return str(candidate)

        remote_candidates = [
            (
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/logo.png",
                cache_dir / f"{appid}_logo.png",
            ),
            (
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/logo.jpg",
                cache_dir / f"{appid}_logo.jpg",
            ),
            (
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
                cache_dir / f"{appid}_header.jpg",
            ),
        ]
        for url, local_file in remote_candidates:
            if self._download_to_file(url, local_file):
                return str(local_file)
        return None

    def _logo_cache_dir(self) -> Path:
        if self.context:
            return self.context.plugin_dir / "cache"
        return Path(__file__).resolve().parent / "cache"

    def _fetch_client_icon_hash(self, appid: str) -> str | None:
        meta_file = self._logo_cache_dir() / f"{appid}_meta.json"
        if meta_file.exists():
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
                cached = str(raw.get("clienticon", "")).strip()
                if cached:
                    return cached
            except Exception:
                pass

        url = f"https://api.steamcmd.net/v1/info/{appid}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as response:  # nosec B310
                data = json.loads(response.read().decode("utf-8", "replace"))
            common = data.get("data", {}).get(str(appid), {}).get("common", {})
            icon_hash = str(common.get("clienticon", "")).strip()
            if icon_hash:
                meta_file.write_text(
                    json.dumps({"clienticon": icon_hash}, ensure_ascii=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                return icon_hash
        except Exception:
            return None
        return None

    def _download_to_file(self, url: str, local_file: Path) -> bool:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3) as response:  # nosec B310
                data = response.read()
            if data:
                local_file.write_bytes(data)
                return True
        except Exception:
            return False
        return False

    def _steam_games_ico_path(self, client_icon_hash: str) -> Path | None:
        steam_root = self._steam_root()
        if steam_root is None:
            return None
        return steam_root / "steam" / "games" / f"{client_icon_hash}.ico"

    def _steam_root(self) -> Path | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_path, value_type = winreg.QueryValueEx(key, "SteamPath")
                if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    return None
                return Path(str(steam_path))
        except OSError:
            return None

    def _convert_ico_to_png(self, ico_path: Path, appid: str) -> str | None:
        try:
            from PySide6.QtWidgets import QApplication

            if QApplication.instance() is None:
                return None

            icon = QIcon(str(ico_path))
            if icon.isNull():
                return None
            pixmap = icon.pixmap(256, 256)
            if pixmap.isNull():
                return None

            normalized = QPixmap.fromImage(pixmap.toImage())
            normalized.setDevicePixelRatio(1.0)

            png_path = self._logo_cache_dir() / f"{appid}_clienticon.png"
            if normalized.save(str(png_path), "PNG"):
                return str(png_path)
        except Exception:
            return None
        return None
