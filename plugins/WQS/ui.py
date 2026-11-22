from __future__ import annotations

import json
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from devices import DeviceManager
from widgets import value


STYLE = """
QDialog, QWidget { background:#11151d; color:#e7edf5; font-family:'Segoe UI'; }
QPushButton, QComboBox, QPlainTextEdit, QListWidget {
  background:#1b2330; color:#e7edf5; border:1px solid #2d394b;
  border-radius:10px; padding:8px;
}
QPushButton:hover { background:#28364a; border-color:#79cfff; }
QLabel#muted { color:#91a0b4; }
QLabel#widget { background:#1b2330; border-radius:12px; padding:10px; }
"""


class DesktopOverlay(QWidget):
    def __init__(self, screen: Any, emergency: Callable[[], None]) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet("background:#080b10;")
        self.setGeometry(screen.geometry())
        QShortcut(QKeySequence("Ctrl+Alt+Escape"), self, activated=emergency)


class Launcher(QDialog):
    def __init__(self, plugin: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.overlays: list[DesktopOverlay] = []
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(980, 650)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(42, 30, 42, 25)
        root.setSpacing(18)
        header = QHBoxLayout()
        title = QLabel("WQS")
        title.setStyleSheet("font-size:26px; font-weight:600;")
        header.addWidget(title)
        header.addStretch()
        self.clock = QLabel()
        self.clock.setObjectName("muted")
        header.addWidget(self.clock)
        settings = QPushButton("Настроить")
        settings.clicked.connect(self.plugin.open_settings)
        header.addWidget(settings)
        root.addLayout(header)

        widgets = QHBoxLayout()
        self.widget_labels: list[tuple[dict[str, Any], QLabel]] = []
        for item in self.plugin.settings.get("widgets", []):
            if item.get("enabled", True):
                label = QLabel(value(item))
                label.setObjectName("widget")
                widgets.addWidget(label)
                self.widget_labels.append((item, label))
        widgets.addStretch()
        root.addLayout(widgets)

        hint = QLabel("Выберите рабочее пространство")
        hint.setStyleSheet("font-size:18px; color:#aebbd0;")
        root.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        cards = QWidget()
        grid = QGridLayout(cards)
        grid.setSpacing(14)
        for index, preset in enumerate(self.plugin.presets):
            button = QPushButton(f"{preset.get('name', 'Без имени')}\n{preset.get('description', '')}")
            button.setMinimumSize(int(preset.get("card_width", 280)), 130)
            button.setStyleSheet(
                f"QPushButton {{ background:{preset.get('color', '#1b2330')}; "
                f"border:1px solid {preset.get('accent', '#2d394b')}; font-size:17px; }}"
            )
            icon = self.plugin.context.plugin_dir / str(preset.get("icon", ""))
            if icon.exists():
                button.setIcon(QIcon(str(icon)))
            button.clicked.connect(lambda checked=False, p=preset: self.plugin.launch_preset(p))
            grid.addWidget(button, index // 3, index % 3)
        scroll.setWidget(cards)
        root.addWidget(scroll, 1)

        network = QHBoxLayout()
        network.addWidget(QLabel("Сеть:"))
        self.mode = QComboBox()
        self.mode.addItem("OFF", "off")
        self.mode.addItem("ZAPRET", "zapret")
        self.mode.addItem("VPN", "vpn")
        network.addWidget(self.mode)
        network.addWidget(QLabel("Сервер:"))
        self.server = QComboBox()
        self.server.addItems([str(item) for item in self.plugin.settings["network"].get("servers", [])])
        network.addWidget(self.server, 1)
        self.status = QLabel("Готово")
        self.status.setObjectName("muted")
        network.addWidget(self.status)
        root.addLayout(network)

        devices = QHBoxLayout()
        for device in DeviceManager(self.plugin.settings.get("devices", [])).read():
            state = f"{device.battery}%" if device.battery is not None else device.status
            icon_path = self.plugin.context.plugin_dir / "icons" / (
                "headphones.svg" if device.icon == "headphones" else
                "headphone-off.svg" if device.icon == "headphone-off.svg" else
                "mouse.svg" if device.icon == "mouse" else
                "mouse-off.svg" if device.icon == "mouse-off.svg" else ""
            )
            device_widget = QWidget()
            device_layout = QHBoxLayout(device_widget)
            device_layout.setContentsMargins(0, 0, 8, 0)
            icon_label = QLabel()
            if icon_path.exists():
                icon_label.setPixmap(QIcon(str(icon_path)).pixmap(22, 22))
            device_layout.addWidget(icon_label)
            text_label = QLabel(f"{device.name}  {state}")
            text_label.setObjectName("muted")
            text_label.setToolTip(f"{device.name}: {state}")
            device_layout.addWidget(text_label)
            devices.addWidget(device_widget)
        devices.addStretch()
        skip = QPushButton("Skip")
        skip.clicked.connect(self.skip)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        devices.addWidget(skip)
        devices.addWidget(close)
        root.addLayout(devices)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        import datetime
        self.clock.setText(datetime.datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))
        for item, label in self.widget_labels:
            label.setText(value(item))

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.overlays = [DesktopOverlay(screen, self.emergency_close) for screen in self._other_screens()]
        for overlay in self.overlays:
            overlay.show()
        screen = self.screen()
        if screen:
            self.setGeometry(screen.geometry())
        QShortcut(QKeySequence("Ctrl+Alt+Escape"), self, activated=self.emergency_close)

    def _other_screens(self) -> list[Any]:
        from PySide6.QtGui import QGuiApplication
        primary = QGuiApplication.primaryScreen()
        return [screen for screen in QGuiApplication.screens() if screen != primary]

    def emergency_close(self) -> None:
        self.plugin.log(False, "WQS аварийно закрыт пользователем")
        self.close()

    def skip(self) -> None:
        if self.mode.currentData() == "off":
            self.close()
            return
        self.plugin.start_network(self.mode.currentData(), self.server.currentText())
        self.status.setText("Сетевой режим запущен")

    def closeEvent(self, event: Any) -> None:
        for overlay in self.overlays:
            overlay.close()
        self.overlays.clear()
        self.plugin.restore_desktop()
        super().closeEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, plugin: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle("WQS settings")
        self.resize(900, 700)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        presets_tab = QWidget()
        presets_layout = QVBoxLayout(presets_tab)
        self.preset_list = QListWidget()
        self.preset_list.addItems([str(p.get("name", "Без имени")) for p in plugin.presets])
        presets_layout.addWidget(self.preset_list)
        test_launch = QPushButton("Тестовый запуск интерфейса")
        test_launch.setToolTip("Открыть WQS без запуска приложений и сетевых профилей")
        test_launch.clicked.connect(self.plugin.show_launcher)
        presets_layout.addWidget(test_launch)
        preset_buttons = QHBoxLayout()
        for title, callback in (
            ("Новый", self.new_preset), ("Дублировать", self.duplicate_preset),
            ("Удалить", self.delete_preset), ("Save current layout", self.save_layout)
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            preset_buttons.addWidget(button)
        presets_layout.addLayout(preset_buttons)
        tabs.addTab(presets_tab, "Presets")

        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        config_layout.addWidget(QLabel("Полная конфигурация: пресеты, приложения, действия, виджеты, устройства и сеть"))
        self.editor = QPlainTextEdit(json.dumps(plugin.settings, ensure_ascii=False, indent=2))
        config_layout.addWidget(self.editor)
        tabs.addTab(config_tab, "Advanced")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def new_preset(self) -> None:
        self.plugin.settings["presets"].append({"id": "new", "name": "Новый пресет", "description": "", "apps": [], "actions": [], "network": {"mode": "off"}})
        self.preset_list.addItem("Новый пресет")

    def duplicate_preset(self) -> None:
        index = self.preset_list.currentRow()
        if index < 0:
            return
        clone = json.loads(json.dumps(self.plugin.settings["presets"][index]))
        clone["id"] = f"{clone.get('id', 'preset')}_copy"
        clone["name"] = f"{clone.get('name', 'Пресет')} копия"
        self.plugin.settings["presets"].append(clone)
        self.preset_list.addItem(clone["name"])

    def delete_preset(self) -> None:
        index = self.preset_list.currentRow()
        if index >= 0:
            self.plugin.settings["presets"].pop(index)
            self.preset_list.takeItem(index)

    def save_layout(self) -> None:
        index = self.preset_list.currentRow()
        if index < 0:
            return
        preset = self.plugin.settings["presets"][index]
        names = [str(item.get("name", "")) for item in preset.get("apps", [])]
        preset["saved_layout"] = self.plugin.window_manager.save_current_layout(names)
        self.editor.setPlainText(json.dumps(self.plugin.settings, ensure_ascii=False, indent=2))

    def save(self) -> None:
        try:
            data = json.loads(self.editor.toPlainText())
            if not isinstance(data, dict):
                raise ValueError("Корень конфигурации должен быть объектом JSON")
            self.plugin.replace_settings(data)
            self.accept()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "WQS", f"Не удалось сохранить настройки:\n{exc}")
