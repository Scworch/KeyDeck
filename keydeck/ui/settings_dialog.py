from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keydeck.config import BUTTON_SIZE_MAP, AppSettings
from keydeck.plugin_api import Action, PluginBase
from keydeck.ui.deck_button import SquircleButton

MIME_SLOT_INDEX = "application/x-keydeck-slot-index"


class SlotConfigDialog(QDialog):
    def __init__(
        self,
        slot_number: int,
        current_action_id: str | None,
        actions: list[Action],
        open_plugin_settings_callback: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Slot {slot_number} Settings")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._actions = actions
        self._action_by_id = {action.action_id: action for action in actions}
        self._open_plugin_settings_callback = open_plugin_settings_callback

        self.setStyleSheet(
            """
            QDialog {
                background: #101010;
                color: #f1f1f1;
            }
            QLabel {
                color: #f1f1f1;
            }
            QComboBox {
                background: #121212;
                border: 1px solid #2d2d2d;
                border-radius: 10px;
                padding: 6px 10px;
                min-height: 20px;
                color: #f1f1f1;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background: #111111;
                border: 1px solid #2b2b2b;
                selection-background-color: #252525;
                selection-color: #ffffff;
            }
            QPushButton#UiButton {
                background: #1b1b1b;
                border: 1px solid #303030;
                border-radius: 10px;
                padding: 7px 12px;
                min-height: 20px;
                color: #f3f3f3;
            }
            QPushButton#UiButton:hover {
                background: #242424;
                border-color: #3b3b3b;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        label = QLabel("Action for this button", self)
        label.setStyleSheet("font-size: 11px; color: #c9c9c9;")
        layout.addWidget(label)

        self.action_combo = QComboBox(self)
        self.action_combo.addItem("<Empty>", "")
        for action in actions:
            self.action_combo.addItem(f"{action.title} [{action.plugin_id}]", action.action_id)
        self._set_combo_data(self.action_combo, current_action_id or "")
        layout.addWidget(self.action_combo)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.plugin_settings_btn = QPushButton("Plugin Settings", self)
        self.plugin_settings_btn.setObjectName("UiButton")
        self.plugin_settings_btn.clicked.connect(self._open_plugin_settings)
        row.addWidget(self.plugin_settings_btn)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        for button in buttons.buttons():
            button.setObjectName("UiButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.action_combo.currentIndexChanged.connect(self._update_plugin_button_state)
        self._update_plugin_button_state()

    def selected_action_id(self) -> str | None:
        data = self.action_combo.currentData()
        return str(data) if data else None

    def refresh_actions(self, actions: list[Action], current_action_id: str | None) -> None:
        self._actions = actions
        self._action_by_id = {action.action_id: action for action in actions}
        self.action_combo.blockSignals(True)
        self.action_combo.clear()
        self.action_combo.addItem("<Empty>", "")
        for action in actions:
            self.action_combo.addItem(f"{action.title} [{action.plugin_id}]", action.action_id)
        self._set_combo_data(self.action_combo, current_action_id or "")
        self.action_combo.blockSignals(False)
        self._update_plugin_button_state()

    def _open_plugin_settings(self) -> None:
        action_id = self.selected_action_id()
        if not action_id:
            QMessageBox.information(self, "Plugin settings", "Select an action first.")
            return
        action = self._action_by_id.get(action_id)
        if action is None or action.settings_callback is None:
            QMessageBox.information(self, "Plugin settings", "This action has no plugin settings.")
            return
        self._open_plugin_settings_callback(action_id)

    def _update_plugin_button_state(self) -> None:
        action_id = self.selected_action_id()
        action = self._action_by_id.get(action_id) if action_id else None
        self.plugin_settings_btn.setEnabled(action is not None and action.settings_callback is not None)

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)


class PreviewSquircleButton(SquircleButton):
    settings_requested = Signal(int)
    swap_requested = Signal(int, int)

    def __init__(self, slot_index: int, size: int, settings_icon: QIcon, settings_icon_path: str, parent: QWidget | None = None) -> None:
        super().__init__(size=size, parent=parent)
        self.slot_index = slot_index
        self._drag_start = QPoint()
        self._settings_icon = settings_icon
        self._settings_svg = QSvgRenderer(settings_icon_path, self)
        self._show_settings_icon = False
        self._settings_icon_rect = QRect()
        self._dragging = False
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(size, size)
        self.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            """
        )

    def set_settings_enabled(self, enabled: bool) -> None:
        self._show_settings_icon = bool(enabled)
        self._sync_settings_button_visibility()

    def enterEvent(self, event) -> None:  # noqa: N802, ANN001
        super().enterEvent(event)
        self._sync_settings_button_visibility()

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        super().leaveEvent(event)
        self._sync_settings_button_visibility()

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        self._settings_icon_rect = self._build_settings_icon_rect()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            self.setCursor(Qt.PointingHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.buttons() & Qt.LeftButton:
            if (event.position().toPoint() - self._drag_start).manhattanLength() >= 8:
                self._dragging = True
                self.setCursor(Qt.OpenHandCursor)
                self._start_drag()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        self.setCursor(Qt.PointingHandCursor)
        if event.button() == Qt.LeftButton and not self._dragging:
            self.settings_requested.emit(self.slot_index)
            event.accept()
            return
        self._dragging = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        super().paintEvent(event)
        if not self._show_settings_icon or not self.underMouse():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        bg_rect = self._settings_icon_rect.adjusted(-6, -6, 6, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 92))
        painter.drawEllipse(bg_rect)
        self._paint_settings_svg(painter)

    def dragEnterEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.mimeData().hasFormat(MIME_SLOT_INDEX):
            self.set_drop_target(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.mimeData().hasFormat(MIME_SLOT_INDEX):
            self.set_drop_target(True)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self.set_drop_target(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802, ANN001
        self.set_drop_target(False)
        if not event.mimeData().hasFormat(MIME_SLOT_INDEX):
            super().dropEvent(event)
            return
        try:
            source_slot = int(bytes(event.mimeData().data(MIME_SLOT_INDEX)).decode("utf-8").strip())
        except (TypeError, ValueError):
            source_slot = -1
        if source_slot >= 0 and source_slot != self.slot_index:
            target_slot = self.slot_index
            event.acceptProposedAction()
            dialog = self.window()
            if hasattr(dialog, "_swap_slots"):
                QTimer.singleShot(0, lambda s=source_slot, t=target_slot: dialog._swap_slots(s, t))
            return
        super().dropEvent(event)



    def _start_drag(self) -> None:
        mime = QMimeData()
        mime.setData(MIME_SLOT_INDEX, str(self.slot_index).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(QPoint(self.width() // 2, self.height() // 2))
        self.setCursor(Qt.PointingHandCursor)
        drag.exec(Qt.MoveAction)
        self._dragging = False

    def _sync_settings_button_visibility(self) -> None:
        self.update()

    def _build_settings_icon_rect(self) -> QRect:
        icon_size = 22
        return QRect(
            (self.width() - icon_size) // 2,
            (self.height() - icon_size) // 2,
            icon_size,
            icon_size,
        )

    def _paint_settings_svg(self, painter: QPainter) -> None:
        if not self._settings_svg.isValid():
            pixmap = self._settings_icon.pixmap(QSize(22, 22))
            painter.drawPixmap(self._settings_icon_rect.topLeft(), pixmap)
            return

        target = QRectF(self._settings_icon_rect)
        target.translate(0.5, 0.5)

        svg_pixmap = QPixmap(self._settings_icon_rect.size())
        svg_pixmap.fill(Qt.transparent)

        svg_painter = QPainter(svg_pixmap)
        svg_painter.setRenderHint(QPainter.Antialiasing, True)
        self._settings_svg.render(
            svg_painter,
            QRectF(0.0, 0.0, float(self._settings_icon_rect.width()), float(self._settings_icon_rect.height())),
        )
        svg_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        svg_painter.fillRect(svg_pixmap.rect(), QColor("#ffffff"))
        svg_painter.end()

        painter.drawPixmap(self._settings_icon_rect.topLeft(), svg_pixmap)


class PreviewDeckButtonWidget(QWidget):
    swap_requested = Signal(int, int)
    settings_requested = Signal(int)
    clear_requested = Signal(int)

    def __init__(self, slot_index: int, size: int, settings_icon: QIcon, settings_icon_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.slot_index = slot_index
        self.setCursor(Qt.PointingHandCursor)
        self.current_action: Action | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.button = PreviewSquircleButton(slot_index, size, settings_icon, settings_icon_path, self)
        self.button.swap_requested.connect(self.swap_requested.emit)
        self.button.settings_requested.connect(self.settings_requested.emit)
        self.button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self.button, alignment=Qt.AlignHCenter)

        self.title = QLabel(self)
        self.title.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.title.setWordWrap(False)
        self.title.setStyleSheet("color: #888888; font-size: 10px; background: transparent;")
        self.title.setFixedWidth(size)
        layout.addWidget(self.title, alignment=Qt.AlignHCenter)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_action(self, action: Action | None) -> None:
        self.current_action = action
        if action is None:
            self.button.set_avatar(None)
            self.button.set_show_plus(True)
            self.button.set_settings_enabled(False)
            self._set_title("Add Action")
            self.title.setStyleSheet("color: #666666; font-size: 10px; font-weight: 500;")
            return

        self.button.set_show_plus(False)
        self.button.set_avatar(
            action.icon_path,
            icon_mode=action.icon_mode,
            icon_zoom=action.icon_zoom,
            icon_offset_x=action.icon_offset_x,
            icon_offset_y=action.icon_offset_y,
        )
        self.button.set_settings_enabled(action.settings_callback is not None)
        self._set_title(action.title)
        self.title.setStyleSheet("color: #d8d8d8; font-size: 10px; font-weight: 600;")

    def _set_title(self, title: str) -> None:
        metrics = QFontMetrics(self.title.font())
        self.title.setText(metrics.elidedText(title, Qt.ElideRight, self.title.width()))

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
            """
        )
        assign_act = menu.addAction("Assign / Change Action...")
        settings_act = None
        if self.current_action and self.current_action.settings_callback:
            settings_act = menu.addAction("Plugin Settings...")

        clear_act = None
        if self.current_action is not None:
            clear_act = menu.addAction("Clear Button")

        chosen = menu.exec(event.globalPos())
        if chosen == assign_act:
            self.settings_requested.emit(self.slot_index)
        elif chosen == settings_act:
            self.settings_requested.emit(self.slot_index)
        elif chosen == clear_act:
            self.clear_requested.emit(self.slot_index)



class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        actions: list[Action],
        plugins: list[PluginBase] | None = None,
        plugin_errors: list[str] | None = None,
        reload_plugins_callback: Callable[[], list[Action]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deck Settings")
        self.setModal(True)
        self.resize(860, 740)
        self.setMinimumSize(780, 640)
        self.plugins = plugins or []
        self.plugin_errors = plugin_errors or []
        self.actions = actions
        self._reload_plugins_callback = reload_plugins_callback
        self._action_by_id = {action.action_id: action for action in actions}
        self._slot_actions = list(settings.slot_actions)
        self._button_widgets: list[PreviewDeckButtonWidget] = []
        self._settings_icon_path = str(self._project_root() / "icons" / "settings.svg")
        self._settings_icon = self._load_white_icon(Path(self._settings_icon_path), 16)
        self._normalize_slot_actions()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(self._build_layout_panel(settings))
        root.addWidget(self._build_plugins_panel(self.plugins, self.plugin_errors))
        root.addWidget(self._build_preview_panel(), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        for button in buttons.buttons():
            button.setObjectName("UiButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.rows_spin.valueChanged.connect(self._rebuild_preview)
        self.columns_spin.valueChanged.connect(self._rebuild_preview)
        self.size_combo.currentIndexChanged.connect(self._rebuild_preview)
        self.reload_plugins_btn.clicked.connect(self._reload_plugins)

        self._rebuild_preview()

    def _build_plugins_panel(self, plugins: list[PluginBase], errors: list[str]) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel("Loaded Plugins & Background Services", panel)
        title.setObjectName("HeaderTitle")
        layout.addWidget(title)

        if not plugins and not errors:
            empty_lbl = QLabel("No active plugins detected.", panel)
            empty_lbl.setObjectName("Hint")
            layout.addWidget(empty_lbl)
            return panel

        for plugin in plugins:
            row = QHBoxLayout()
            row.setSpacing(10)
            
            plugin_name = getattr(plugin, "plugin_name", plugin.__class__.__name__)
            plugin_id = plugin.context.plugin_id if plugin.context else getattr(plugin, "plugin_id", "core")
            
            name_lbl = QLabel(f"• {plugin_name}", panel)
            name_lbl.setStyleSheet("font-weight: 600; font-size: 12px;")
            row.addWidget(name_lbl)

            id_lbl = QLabel(f"[{plugin_id}]", panel)
            id_lbl.setObjectName("Hint")
            row.addWidget(id_lbl)

            row.addStretch(1)

            settings_btn = QPushButton("Configure / Settings", panel)
            settings_btn.setObjectName("UiButton")
            settings_btn.clicked.connect(lambda _, p=plugin: p.open_settings())
            row.addWidget(settings_btn)

            layout.addLayout(row)

        for err in errors:
            row = QHBoxLayout()
            row.setSpacing(10)
            err_lbl = QLabel(f"⚠ FAILED TO LOAD: {err}", panel)
            err_lbl.setStyleSheet("color: #ff5555; font-size: 11px; font-weight: 600;")
            row.addWidget(err_lbl)
            row.addStretch(1)
            layout.addLayout(row)

        return panel



    def _build_layout_panel(self, settings: AppSettings) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("Panel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("Layout", panel)
        title.setObjectName("HeaderTitle")
        hint = QLabel("Configure deck size. Drag buttons below to reorder slots.", panel)
        hint.setObjectName("Hint")
        left.addWidget(title)
        left.addWidget(hint)
        layout.addLayout(left, 1)

        self.rows_spin = QSpinBox(panel)
        self.rows_spin.setRange(1, 8)
        self.rows_spin.setValue(settings.rows)

        self.columns_spin = QSpinBox(panel)
        self.columns_spin.setRange(1, 8)
        self.columns_spin.setValue(settings.columns)

        self.size_combo = QComboBox(panel)
        self.size_combo.addItem("Small", "small")
        self.size_combo.addItem("Medium", "medium")
        self.size_combo.addItem("Large", "large")
        self._set_combo_data(self.size_combo, settings.button_size)

        for label_text, widget in (
            ("Rows", self.rows_spin),
            ("Columns", self.columns_spin),
            ("Button size", self.size_combo),
        ):
            col = QVBoxLayout()
            col.setSpacing(5)
            label = QLabel(label_text, panel)
            label.setObjectName("FieldLabel")
            col.addWidget(label)
            col.addWidget(widget)
            layout.addLayout(col)

        return panel

    def _build_preview_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Deck Preview", panel)
        title.setObjectName("HeaderTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.reload_plugins_btn = QPushButton("Reload Plugins", panel)
        self.reload_plugins_btn.setObjectName("UiButton")
        header.addWidget(self.reload_plugins_btn)
        layout.addLayout(header)

        self.preview_scroll = QScrollArea(panel)
        self.preview_scroll.setWidgetResizable(True)

        self.preview_host = QWidget(self.preview_scroll)
        self.preview_grid = QGridLayout(self.preview_host)
        self.preview_grid.setContentsMargins(0, 0, 0, 0)
        self.preview_grid.setHorizontalSpacing(10)
        self.preview_grid.setVerticalSpacing(10)
        self.preview_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.preview_scroll.setWidget(self.preview_host)
        layout.addWidget(self.preview_scroll, 1)
        return panel

    def to_settings(self) -> AppSettings:
        settings = AppSettings(
            rows=self.rows_spin.value(),
            columns=self.columns_spin.value(),
            button_size=str(self.size_combo.currentData() or "medium"),
            slot_actions=self._slot_actions,
        )
        return settings.clamp()

    def _rebuild_preview(self) -> None:
        while self.preview_grid.count():
            item = self.preview_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._button_widgets = []

        rows = self.rows_spin.value()
        cols = self.columns_spin.value()
        total = rows * cols
        if len(self._slot_actions) < total:
            self._slot_actions.extend([None] * (total - len(self._slot_actions)))
        self._slot_actions = self._slot_actions[:total]

        button_size = BUTTON_SIZE_MAP.get(str(self.size_combo.currentData() or "medium"), BUTTON_SIZE_MAP["medium"])
        for slot in range(total):
            widget = PreviewDeckButtonWidget(
                slot,
                button_size,
                self._settings_icon,
                self._settings_icon_path,
                self.preview_host,
            )
            widget.swap_requested.connect(self._swap_slots)
            widget.settings_requested.connect(self._open_slot_config)
            widget.clear_requested.connect(self._clear_slot)
            widget.set_action(self._action_for_slot(slot))
            row_idx = slot // cols
            col_idx = slot % cols
            self.preview_grid.addWidget(widget, row_idx, col_idx, alignment=Qt.AlignTop | Qt.AlignLeft)
            self._button_widgets.append(widget)

    def _swap_slots(self, source_slot: int, target_slot: int) -> None:
        if source_slot == target_slot:
            return
        if source_slot >= len(self._slot_actions) or target_slot >= len(self._slot_actions):
            return
        self._slot_actions[source_slot], self._slot_actions[target_slot] = (
            self._slot_actions[target_slot],
            self._slot_actions[source_slot],
        )
        self._refresh_slot(source_slot)
        self._refresh_slot(target_slot)

    def _clear_slot(self, slot: int) -> None:
        if 0 <= slot < len(self._slot_actions):
            self._slot_actions[slot] = None
            self._refresh_slot(slot)


    def _open_slot_config(self, slot: int) -> None:
        if slot < 0 or slot >= len(self._slot_actions):
            return

        current_action_id = self._slot_actions[slot]
        dialog = SlotConfigDialog(
            slot_number=slot + 1,
            current_action_id=current_action_id,
            actions=self.actions,
            open_plugin_settings_callback=lambda action_id: self._open_plugin_settings_from_config(dialog, action_id),
            parent=self,
        )
        if dialog.exec():
            self._slot_actions[slot] = dialog.selected_action_id()
            self._refresh_slot(slot)

    def _open_plugin_settings_from_config(self, config_dialog: SlotConfigDialog, action_id: str) -> None:
        action = self._action_by_id.get(action_id)
        if action is None or action.settings_callback is None:
            QMessageBox.information(self, "Plugin settings", "Selected action has no plugin settings.")
            return

        config_dialog.setEnabled(False)
        try:
            action.settings_callback()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Plugin settings", str(exc))
        finally:
            config_dialog.setEnabled(True)
            config_dialog.raise_()
            config_dialog.activateWindow()

        self._reload_plugins()
        config_dialog.refresh_actions(self.actions, config_dialog.selected_action_id())

    def _reload_plugins(self) -> None:
        if self._reload_plugins_callback is None:
            return
        try:
            self.actions = self._reload_plugins_callback()
            self._action_by_id = {action.action_id: action for action in self.actions}
            self._normalize_slot_actions()
            self._rebuild_preview()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Reload Plugins", str(exc))

    def _action_for_slot(self, slot: int) -> Action | None:
        action_id = self._slot_actions[slot] if slot < len(self._slot_actions) else None
        return self._action_by_id.get(action_id) if action_id else None

    def _refresh_slot(self, slot: int) -> None:
        if slot < 0 or slot >= len(self._button_widgets):
            return
        self._button_widgets[slot].set_action(self._action_for_slot(slot))

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)

    def _normalize_slot_actions(self) -> None:
        valid_action_ids = set(self._action_by_id)
        aliases: dict[str, str] = {}
        for action in self.actions:
            for alias in action.aliases:
                aliases[str(alias)] = action.action_id

        normalized: list[str | None] = []
        for action_id in self._slot_actions:
            if not action_id:
                normalized.append(None)
            elif action_id in valid_action_ids:
                normalized.append(action_id)
            else:
                normalized.append(aliases.get(action_id))
        self._slot_actions = normalized

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _load_white_icon(self, icon_path: Path, size: int) -> QIcon:
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
