from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
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
    blur_hide_requested = Signal()
    page_changed = Signal(int)
    action_requested = Signal(object, int, int)

    def __init__(
        self,
        settings: AppSettings,
        actions: list[Action],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        settings.clamp()
        self.settings = settings
        self.actions = actions
        self._action_map: dict[int, Action | None] = {}
        self.current_page_index = settings.active_page
        self._pending_page_index: int | None = None
        self._page_transition_stage = 0
        self._page_animation: QPropertyAnimation | None = None
        self._prewarm_page_index = 0
        self._prewarm_scheduled = False

        self.setWindowTitle("KeyDeck")
        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        self.setObjectName("DeckWindow")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)

        self.setStyleSheet(
            """
            QWidget#DeckWindow {
                background-color: #262626;
                border-radius: 14px;
            }
            """
        )

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(14, 14, 14, 14)
        self.main_layout.setSpacing(10)

        self._build_header()
        self._build_grid_container()
        self._build_page_indicator()
        self.rebuild_grid()


    def _build_header(self) -> None:
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.setAlignment(Qt.AlignTop)

        title = QLabel("KeyDeck", self)
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        title.setFixedHeight(24)

        self.settings_button = QToolButton(self)
        self.settings_button.setObjectName("SettingsButton")
        self.settings_button.setToolTip("Settings")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setAutoRaise(True)
        self.settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        icon_path = (self._project_root() / "icons" / "settings.svg")
        if icon_path.exists():
            self.settings_button.setIcon(self._load_white_icon(icon_path, 16))
            self.settings_button.setIconSize(QSize(16, 16))
        else:
            self.settings_button.setText("CFG")
        self.settings_button.setFixedSize(24, 24)
        self.settings_button.setStyleSheet(
            """
            QToolButton {
                background: transparent;
                border: none;
                color: #e6e6e6;
                padding: 0px;
                min-height: 24px;
                min-width: 24px;
                max-height: 24px;
                max-width: 24px;
            }
            QToolButton:hover {
                background: transparent;
            }
            """
        )

        header_layout.addWidget(title, 0, Qt.AlignTop)
        header_layout.addStretch(1)
        header_layout.addWidget(self.settings_button, 0, Qt.AlignTop)
        self.main_layout.addLayout(header_layout)

    def _build_grid_container(self) -> None:
        self.page_stack = QStackedWidget(self)
        self.page_stack.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.page_stack.installEventFilter(self)
        self.main_layout.addWidget(self.page_stack)
        self._page_grids: dict[str, tuple[QWidget, QGridLayout, dict[int, Action | None]]] = {}
        self.grid_widget: QWidget | None = None
        self.grid_layout: QGridLayout | None = None
        self._grid_opacity = QGraphicsOpacityEffect(self.page_stack)
        self._grid_opacity.setOpacity(1.0)
        self.page_stack.setGraphicsEffect(self._grid_opacity)

    def _build_page_indicator(self) -> None:
        self.page_indicator = QWidget(self)
        self.page_indicator.installEventFilter(self)
        self.page_indicator_layout = QHBoxLayout(self.page_indicator)
        self.page_indicator_layout.setContentsMargins(0, 0, 0, 0)
        self.page_indicator_layout.setSpacing(7)
        self.page_indicator_layout.setAlignment(Qt.AlignCenter)
        self.main_layout.addWidget(self.page_indicator)
        self._update_page_indicator()

    def _update_page_indicator(self) -> None:
        while self.page_indicator_layout.count():
            item = self.page_indicator_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        pages = self.settings.pages
        has_multiple_pages = len(pages) > 1
        self.page_indicator.setVisible(has_multiple_pages)
        self.page_indicator.setMinimumHeight(14 if has_multiple_pages else 0)
        self.page_indicator.setMaximumHeight(14 if has_multiple_pages else 0)
        for index, page in enumerate(pages):
            dot = QToolButton(self.page_indicator)
            dot.setAccessibleName(f"Go to {page.name}")
            dot.setToolTip(page.name)
            dot.setFixedSize(14, 14)
            dot.setCursor(Qt.PointingHandCursor)
            dot.installEventFilter(self)
            dot.setText("●")
            color = "#3b82f6" if index == self.current_page_index else "#52525b"
            dot.setStyleSheet(
                f"QToolButton {{ border: 1px solid #444444; border-radius: 2px; "
                f"background-color: #343434; color: {color}; font-size: 11px; padding: 0; }}"
                f"QToolButton:hover {{ background-color: #414141; "
                f"color: {'#60a5fa' if index == self.current_page_index else '#a1a1aa'}; }}"
            )
            dot.clicked.connect(lambda checked=False, target=index: self.set_page(target))
            self.page_indicator_layout.addWidget(dot)

    def set_page(self, page_index: int) -> None:
        if not 0 <= page_index < len(self.settings.pages) or page_index == self.current_page_index:
            return
        if (
            self._page_animation is not None
            and self._page_animation.state() == QAbstractAnimation.State.Running
        ):
            return

        self._pending_page_index = page_index
        self._page_transition_stage = 0
        self._animate_page_opacity(1.0, 0.35, 100)

    def _animate_page_opacity(self, start: float, end: float, duration: int) -> None:
        animation = QPropertyAnimation(self._grid_opacity, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.finished.connect(self._finish_page_transition)
        self._page_animation = animation
        animation.start()

    def _finish_page_transition(self) -> None:
        if self._page_transition_stage == 0:
            if self._pending_page_index is None:
                return
            self.current_page_index = self._pending_page_index
            self.settings.active_page = self.current_page_index
            self._pending_page_index = None
            self._page_transition_stage = 1
            self._update_page_indicator()
            self.rebuild_grid(resize_window=True)
            self.page_changed.emit(self.current_page_index)
            self._animate_page_opacity(0.35, 1.0, 110)
            return

        self._page_transition_stage = 0
        self._page_animation = None

    def _change_page_by_wheel(self, delta: int) -> bool:
        page_count = len(self.settings.pages)
        if page_count < 2:
            return False
        target = self.current_page_index + (1 if delta < 0 else -1)
        if self.settings.infinite_scroll:
            target %= page_count
        elif not 0 <= target < page_count:
            return True
        self.set_page(target)
        return True

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            if delta:
                return self._change_page_by_wheel(delta)
        return super().eventFilter(watched, event)

    def rebuild_grid(self, resize_window: bool = True) -> None:
        if self._page_transition_stage == 0:
            self._grid_opacity.setOpacity(1.0)
        page = self.settings.pages[self.current_page_index]
        cached_grid = self._page_grids.get(page.page_id)
        if cached_grid is None:
            cached_grid = self._create_page_grid(self.current_page_index)
            self._page_grids[page.page_id] = cached_grid

        self.grid_widget, self.grid_layout, self._action_map = cached_grid
        self.page_stack.setCurrentWidget(self.grid_widget)
        self.grid_widget.adjustSize()
        self.grid_widget.updateGeometry()
        self.grid_layout.activate()
        self.main_layout.activate()

        if resize_window:
            self.page_stack.setFixedSize(self.grid_widget.sizeHint())
            QApplication.processEvents()
            target_size = self.sizeHint()
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.resize(target_size)
            self.setFixedSize(target_size)
            self.move_to_corner()

    def _create_page_grid(
        self,
        page_index: int,
    ) -> tuple[QWidget, QGridLayout, dict[int, Action | None]]:
        page = self.settings.pages[page_index]
        metrics = self._compute_grid_metrics(page_index)
        grid_widget = QWidget(self.page_stack)
        grid_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        grid_widget.installEventFilter(self)
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(metrics.gap)
        grid_layout.setVerticalSpacing(metrics.gap)

        action_map: dict[int, Action | None] = {}
        total = page.rows * page.columns
        empty_layout = not any(page.slot_actions[:total])
        for index in range(total):
            action = None
            slot_action_id = page.slot_actions[index] if index < len(page.slot_actions) else None
            if slot_action_id:
                action = self._find_action_by_id(slot_action_id)
            if action is None and empty_layout and self.actions:
                action = self.actions[index % len(self.actions)]

            title = action.title if action else f"Button {index + 1}"
            icon_path = action.icon_path if action else None
            slot_settings = page.slot_settings.get(str(index), {})
            slot_overrides = page.slot_overrides.get(str(index), {})

            if action and action.action_icon_callback:
                dyn_icon = action.action_icon_callback(index, slot_settings)
                if dyn_icon:
                    icon_path = dyn_icon
            custom_icon_path = slot_overrides.get("icon_path")
            if custom_icon_path and Path(custom_icon_path).is_file():
                icon_path = custom_icon_path

            if action and "account_name" in slot_settings:
                title = slot_settings["account_name"]
            if slot_overrides.get("title"):
                title = slot_overrides["title"]

            icon_mode = slot_overrides.get(
                "image_mode",
                action.icon_mode if action else "default",
            )
            icon_zoom = slot_overrides.get(
                "image_zoom",
                action.icon_zoom if action else 1.0,
            )
            icon_offset_x = slot_overrides.get(
                "image_offset_x",
                action.icon_offset_x if action else 0,
            )
            icon_offset_y = slot_overrides.get(
                "image_offset_y",
                action.icon_offset_y if action else 0,
            )
            button_widget = DeckButtonWidget(
                index=index,
                title=title,
                size=metrics.button_size,
                icon_path=icon_path,
                icon_mode=icon_mode,
                icon_zoom=icon_zoom,
                icon_offset_x=icon_offset_x,
                icon_offset_y=icon_offset_y,
                parent=grid_widget,
            )
            button_widget.clicked.connect(self._on_button_clicked)
            button_widget.installEventFilter(self)
            for child in button_widget.findChildren(QWidget):
                child.installEventFilter(self)
            grid_layout.addWidget(
                button_widget,
                index // page.columns,
                index % page.columns,
            )
            action_map[index] = action

        grid_widget.adjustSize()
        grid_layout.activate()
        self.page_stack.addWidget(grid_widget)
        return grid_widget, grid_layout, action_map

    def update_actions(self, actions: list[Action]) -> None:
        self.actions = actions
        self._clear_page_grids()
        self.rebuild_grid(resize_window=False)

    def apply_settings(self, settings: AppSettings) -> None:
        settings.clamp()
        if self._page_animation is not None:
            self._page_animation.stop()
            self._page_animation = None
        self._pending_page_index = None
        self._page_transition_stage = 0
        self._grid_opacity.setOpacity(1.0)
        self.settings = settings
        self.current_page_index = settings.active_page
        self._clear_page_grids()
        self._update_page_indicator()
        self.rebuild_grid(resize_window=True)

    def _clear_page_grids(self) -> None:
        self._page_grids.clear()
        self._prewarm_page_index = 0
        self._prewarm_scheduled = False
        while self.page_stack.count():
            widget = self.page_stack.widget(0)
            self.page_stack.removeWidget(widget)
            widget.deleteLater()
        if self.isVisible():
            self._prewarm_scheduled = True
            QTimer.singleShot(0, self._prewarm_next_page)
        self.grid_widget = None
        self.grid_layout = None
        self._action_map = {}

    def _on_button_clicked(self, index: int) -> None:
        self.action_requested.emit(self._action_map.get(index), index, self.current_page_index)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.move_to_corner()
        if not self._prewarm_scheduled:
            self._prewarm_scheduled = True
            QTimer.singleShot(0, self._prewarm_next_page)

    def _prewarm_next_page(self) -> None:
        if self._prewarm_page_index >= len(self.settings.pages):
            return

        page_index = self._prewarm_page_index
        self._prewarm_page_index += 1
        page_id = self.settings.pages[page_index].page_id
        if page_id not in self._page_grids:
            self._page_grids[page_id] = self._create_page_grid(page_index)
        QTimer.singleShot(0, self._prewarm_next_page)

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

    def _compute_grid_metrics(self, page_index: int | None = None) -> GridMetrics:
        base_button = self.settings.button_pixels()
        base_gap = 10
        page = self.settings.pages[
            self.current_page_index if page_index is None else page_index
        ]
        rows = max(1, page.rows)
        columns = max(1, page.columns)

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

    def _load_white_icon(self, icon_path, size: int) -> QIcon:
        base = QIcon(str(icon_path))
        pix = base.pixmap(size, size)
        if pix.isNull():
            return base

        white = QPixmap(pix.size())
        white.fill(Qt.transparent)

        painter = QPainter(white)
        painter.drawPixmap(0, 0, pix)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(white.rect(), QColor("#ffffff"))
        painter.end()
        return QIcon(white)
