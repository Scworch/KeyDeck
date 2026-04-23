from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from keydeck.config import AppSettings
from keydeck.plugin_api import Action
from keydeck.ui.deck_button import DeckButtonWidget


@dataclass
class GridMetrics:
    button_size: int
    gap: int


class DeckWindow(QWidget):
    settings_requested = Signal()
    action_requested = Signal(object)
    blur_hide_requested = Signal()

    def __init__(
        self,
        settings: AppSettings,
        actions: list[Action],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.actions = actions
        self._action_map: dict[int, Action | None] = {}

        self.setWindowTitle("KeyDeck")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)

        self.setStyleSheet(
            """
            QWidget {
                background-color: #141414;
                color: #e6e6e6;
            }
            """
        )

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        self._build_header()
        self._build_grid_container()
        self.rebuild_grid()

    def _build_header(self) -> None:
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("KeyDeck", self)
        title.setStyleSheet("font-weight: bold; font-size: 13px;")

        self.settings_button = QToolButton(self)
        self.settings_button.setToolTip("Settings")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        icon_path = (self._project_root() / "icons" / "settings.svg")
        if icon_path.exists():
            self.settings_button.setIcon(QIcon(str(icon_path)))
            self.settings_button.setIconSize(QSize(16, 16))
        else:
            self.settings_button.setText("CFG")
        self.settings_button.setStyleSheet(
            """
            QToolButton {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 12px;
                color: #e6e6e6;
                padding: 4px;
                min-width: 28px;
                min-height: 28px;
            }
            QToolButton:hover {
                background-color: #3a3a3a;
            }
            """
        )

        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.settings_button)
        self.main_layout.addLayout(header_layout)

    def _build_grid_container(self) -> None:
        self.grid_widget = QWidget(self)
        self.grid_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.grid_widget)

    def rebuild_grid(self) -> None:
        metrics = self._compute_grid_metrics()

        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self._action_map = {}
        self.grid_layout.setHorizontalSpacing(metrics.gap)
        self.grid_layout.setVerticalSpacing(metrics.gap)

        total = self.settings.rows * self.settings.columns
        empty_layout = not any(self.settings.slot_actions)
        for index in range(total):
            action = None
            slot_action_id = self.settings.slot_actions[index] if index < len(self.settings.slot_actions) else None
            if slot_action_id:
                action = self._find_action_by_id(slot_action_id)
            if action is None and empty_layout and self.actions:
                action = self.actions[index % len(self.actions)]

            title = action.title if action else f"Button {index + 1}"
            button_widget = DeckButtonWidget(
                index=index,
                title=title,
                size=metrics.button_size,
                icon_path=action.icon_path if action else None,
                icon_mode=action.icon_mode if action else "default",
                icon_zoom=action.icon_zoom if action else 1.0,
                icon_offset_x=action.icon_offset_x if action else 0,
                icon_offset_y=action.icon_offset_y if action else 0,
                parent=self.grid_widget,
            )
            button_widget.clicked.connect(self._on_button_clicked)
            row = index // self.settings.columns
            column = index % self.settings.columns
            self.grid_layout.addWidget(button_widget, row, column)
            self._action_map[index] = action

        self.grid_widget.adjustSize()
        self.grid_widget.updateGeometry()
        self.grid_layout.activate()
        self.main_layout.activate()

        target_size = self.sizeHint()
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.resize(target_size)
        self.setFixedSize(target_size)

        self.move_to_corner()

    def update_actions(self, actions: list[Action]) -> None:
        self.actions = actions
        self.rebuild_grid()

    def apply_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.rebuild_grid()

    def _on_button_clicked(self, index: int) -> None:
        self.action_requested.emit(self._action_map.get(index))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.move_to_corner()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._schedule_blur_hide()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self._schedule_blur_hide()

    def _schedule_blur_hide(self) -> None:
        if not self.isVisible():
            return
        QTimer.singleShot(0, self._emit_hide_if_inactive)

    def _emit_hide_if_inactive(self) -> None:
        if QApplication.activeModalWidget() is not None:
            return
        if self.isVisible() and not self.isActiveWindow():
            self.blur_hide_requested.emit()

    def move_to_corner(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        margin = 16
        max_w = max(220, available.width() - margin * 2)
        max_h = max(140, available.height() - margin * 2)
        if self.width() > max_w or self.height() > max_h:
            self.setFixedSize(min(self.width(), max_w), min(self.height(), max_h))

        x = available.right() - self.width() - margin + 1
        y = available.bottom() - self.height() - margin + 1
        x = max(available.left() + margin, x)
        y = max(available.top() + margin, y)
        self.move(x, y)

    def _find_action_by_id(self, action_id: str) -> Action | None:
        for action in self.actions:
            if action.action_id == action_id:
                return action
        return None

    def _compute_grid_metrics(self) -> GridMetrics:
        base_button = self.settings.button_pixels()
        base_gap = 10
        rows = max(1, self.settings.rows)
        columns = max(1, self.settings.columns)

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return GridMetrics(button_size=base_button, gap=base_gap)

        available = screen.availableGeometry()
        margin = 16
        allowed_width = max(260, available.width() - margin * 2)
        allowed_height = max(200, available.height() - margin * 2)

        # Approximate total size before actual widget layout pass.
        per_button_height = base_button + 28
        est_width = 20 + columns * base_button + (columns - 1) * base_gap
        est_height = 56 + rows * per_button_height + (rows - 1) * base_gap

        if est_width <= allowed_width and est_height <= allowed_height:
            return GridMetrics(button_size=base_button, gap=base_gap)

        scale_w = allowed_width / est_width
        scale_h = allowed_height / est_height
        scale = min(scale_w, scale_h, 1.0)
        scaled_button = max(44, int(base_button * scale))
        scaled_gap = max(4, int(base_gap * scale))
        return GridMetrics(button_size=scaled_button, gap=scaled_gap)

    def _project_root(self):
        from pathlib import Path

        return Path(__file__).resolve().parents[2]
