from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from keydeck.config import BUTTON_SIZE_MAP, AppSettings
from keydeck.plugin_api import Action, PluginBase
from keydeck.ui.deck_button import SquircleButton

MIME_SLOT_INDEX = "application/x-keydeck-slot-index"


class ModernCheckBox(QCheckBox):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFixedHeight(24)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        box_size = 20
        box_y = int((self.height() - box_size) / 2)
        box_rect = QRectF(2.0, float(box_y), float(box_size), float(box_size))

        if not self.isEnabled():
            bg_color = QColor("#18181b")
            border_color = QColor("#27272a")
            check_color = QColor("#52525b")
        elif self.isChecked():
            bg_color = QColor("#2563eb")
            border_color = QColor("#3b82f6")
            check_color = QColor("#ffffff")
        else:
            bg_color = QColor("#09090b")
            border_color = QColor("#52525b")
            check_color = QColor("transparent")

        path = QPainterPath()
        path.addRoundedRect(box_rect, 5.0, 5.0)
        painter.fillPath(path, bg_color)

        pen = QPen(border_color, 2.0 if self.isChecked() else 1.5)
        painter.setPen(pen)
        painter.drawPath(path)

        if self.isChecked():
            pen_check = QPen(check_color, 2.6)
            pen_check.setCapStyle(Qt.RoundCap)
            pen_check.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen_check)

            p1 = QPointF(box_rect.left() + 5.0, box_rect.top() + 10.0)
            p2 = QPointF(box_rect.left() + 8.5, box_rect.top() + 14.0)
            p3 = QPointF(box_rect.left() + 15.0, box_rect.top() + 6.5)

            path_check = QPainterPath()
            path_check.moveTo(p1)
            path_check.lineTo(p2)
            path_check.lineTo(p3)
            painter.drawPath(path_check)

        if self.text():
            font = self.font()
            font.setPixelSize(13)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            text_color = QColor("#52525b") if not self.isEnabled() else QColor("#f4f4f5")
            painter.setPen(text_color)
            text_rect = QRectF(float(box_size + 14), 0.0, float(self.width() - box_size - 14), float(self.height()))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())

        painter.end()


class ActionPickerDialog(QDialog):
    def __init__(
        self,
        slot_number: int,
        current_action_id: str | None,
        actions: list[Action],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Select Action for Slot {slot_number}")
        self.setModal(True)
        self.resize(480, 420)
        self._selected_id = current_action_id

        self.setStyleSheet(
            """
            QDialog {
                background-color: #121214;
                color: #f4f4f5;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
            QLabel#Header {
                font-size: 15px;
                font-weight: 700;
                color: #ffffff;
            }
            QListWidget {
                background-color: #18181b;
                border: 1px solid #27272a;
                border-radius: 8px;
                outline: none;
                padding: 6px;
            }
            QListWidget::item {
                background-color: #27272a;
                border-radius: 6px;
                padding: 8px 12px;
                margin-bottom: 4px;
                color: #f4f4f5;
            }
            QListWidget::item:hover {
                background-color: #3f3f46;
            }
            QListWidget::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            QPushButton#Btn {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 8px 16px;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#Btn:hover {
                background-color: #3f3f46;
            }
            QPushButton#PrimaryBtn {
                background-color: #2563eb;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #1d4ed8;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel(f"Assign Action to Slot #{slot_number}", self)
        header.setObjectName("Header")
        layout.addWidget(header)

        self.list_widget = QListWidget(self)

        # Add Empty option
        empty_item = QListWidgetItem("🚫  < Empty / Clear Slot >")
        empty_item.setData(Qt.UserRole, "")
        self.list_widget.addItem(empty_item)

        for action in actions:
            emoji = "🔌"
            pid = action.plugin_id
            aid = action.action_id
            if "SteamSwitcher" in pid or "SteamSwitcher" in aid:
                emoji = "👤"
            elif "SteamLauncher" in pid or "Steam" in pid:
                emoji = "🎮"
            elif "GtaClearSession" in pid or "Gta" in pid or "session" in aid.lower():
                emoji = "🧹"
            elif "ResolutionSwitcher" in pid or "Resolution" in pid:
                emoji = "🖥️"
            elif "WaveLink" in pid:
                emoji = "🎵"
            elif "ZapretToggler" in pid or "Zapret" in pid:
                emoji = "🌐"

            text = f"{emoji}  {action.title}  ({action.plugin_id})"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, action.action_id)
            self.list_widget.addItem(item)
            if current_action_id == action.action_id:
                self.list_widget.setCurrentItem(item)

        if current_action_id is None:
            self.list_widget.setCurrentItem(empty_item)

        self.list_widget.itemDoubleClicked.connect(self._on_select)
        layout.addWidget(self.list_widget, 1)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setObjectName("Btn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        select_btn = QPushButton("Select Action", self)
        select_btn.setObjectName("PrimaryBtn")
        select_btn.clicked.connect(self._on_select)
        btn_box.addWidget(select_btn)

        layout.addLayout(btn_box)

    def _on_select(self) -> None:
        item = self.list_widget.currentItem()
        if item:
            self._selected_id = item.data(Qt.UserRole)
        self.accept()

    def selected_action_id(self) -> str | None:
        return self._selected_id if self._selected_id else None


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

    def set_settings_enabled(self, enabled: bool) -> None:
        self._show_settings_icon = bool(enabled)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)

        # Stronger dark hover effect with white settings gear icon for configured slots
        if self._hovered and not self._show_plus:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            w = float(self.width())
            h = float(self.height())
            rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
            radius = max(8.0, float(min(w, h) * 0.28))
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            # Strong dark translucent overlay
            painter.fillPath(path, QColor(0, 0, 0, 190))

            # White settings gear icon (rendered directly from SVG vector for exact centering)
            if self._settings_svg and self._settings_svg.isValid():
                icon_size = int(max(18.0, float(min(w, h) * 0.42)))
                pixmap = QPixmap(icon_size, icon_size)
                pixmap.fill(Qt.transparent)

                p = QPainter(pixmap)
                p.setRenderHint(QPainter.Antialiasing, True)
                self._settings_svg.render(p)
                p.setCompositionMode(QPainter.CompositionMode_SourceIn)
                p.fillRect(pixmap.rect(), QColor("#ffffff"))
                p.end()

                target_x = float((w - float(icon_size)) / 2.0)
                target_y = float((h - float(icon_size)) / 2.0)
                painter.drawPixmap(QRectF(target_x, target_y, float(icon_size), float(icon_size)), pixmap, QRectF(pixmap.rect()))
            painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            self.setCursor(Qt.PointingHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            if (event.position().toPoint() - self._drag_start).manhattanLength() >= 8:
                self._dragging = True
                self.setCursor(Qt.OpenHandCursor)
                self._start_drag()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.setCursor(Qt.PointingHandCursor)
        if event.button() == Qt.LeftButton and not self._dragging:
            self.settings_requested.emit(self.slot_index)
            event.accept()
            return
        self._dragging = False
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_SLOT_INDEX):
            self.set_drop_target(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_SLOT_INDEX):
            self.set_drop_target(True)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_drop_target(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
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
        self.button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.button.settings_requested.connect(self.settings_requested.emit)
        layout.addWidget(self.button, alignment=Qt.AlignHCenter)

        self.title = QLabel(self)
        self.title.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.title.setWordWrap(False)
        self.title.setStyleSheet("color: #888888; font-size: 10px; background: transparent;")
        self.title.setFixedWidth(size)
        layout.addWidget(self.title, alignment=Qt.AlignHCenter)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_action(self, action: Action | None, settings: dict | None = None) -> None:
        self.current_action = action
        if action is None:
            self.button.set_avatar(None)
            self.button.set_show_plus(True)
            self.button.set_settings_enabled(False)
            self._set_title("Add Action")
            self.title.setStyleSheet("color: #71717a; font-size: 10px; font-weight: 500;")
            return

        icon_path = action.icon_path
        if action.action_icon_callback and settings is not None:
            dyn_icon = action.action_icon_callback(self.slot_index, settings)
            if dyn_icon:
                icon_path = dyn_icon

        self.button.set_show_plus(False)
        self.button.set_avatar(
            icon_path,
            icon_mode=action.icon_mode,
            icon_zoom=action.icon_zoom,
            icon_offset_x=action.icon_offset_x,
            icon_offset_y=action.icon_offset_y,
        )
        self.button.set_settings_enabled(action.settings_callback is not None or action.action_settings_callback is not None)
        
        # dynamic title if available
        title = action.title
        if settings and "account_name" in settings:
            title = settings["account_name"]

        self._set_title(title)
        self.title.setStyleSheet("color: #f4f4f5; font-size: 10px; font-weight: 600;")

    def _set_title(self, title: str) -> None:
        metrics = QFontMetrics(self.title.font())
        self.title.setText(metrics.elidedText(title, Qt.ElideRight, self.title.width()))

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #18181b;
                color: #e4e4e7;
                border: 1px solid #27272a;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            """
        )
        assign_act = menu.addAction("Assign / Change Action...")
        
        hotkey_act = None
        settings_act = None
        plugin_settings_act = None
        clear_act = None
        
        if self.current_action is not None:
            hotkey_act = menu.addAction("Assign Hotkey...")
            
            if getattr(self.current_action, "action_settings_callback", None):
                settings_act = menu.addAction("Action Settings...")
                
            if self.current_action.settings_callback:
                plugin_settings_act = menu.addAction("Plugin Settings...")

            menu.addSeparator()
            clear_act = menu.addAction("Clear Button")

        chosen = menu.exec(event.globalPos())
        dialog = self.window()
        if chosen == assign_act:
            if hasattr(dialog, "_open_action_picker"):
                dialog._open_action_picker(self.slot_index)
        elif chosen and hotkey_act and chosen == hotkey_act:
            if hasattr(dialog, "_assign_hotkey"):
                dialog._assign_hotkey(self.slot_index)
        elif chosen and settings_act and chosen == settings_act:
            if hasattr(dialog, "_open_action_settings"):
                dialog._open_action_settings(self.slot_index, self.current_action)
                if hasattr(dialog, "_refresh_slot"):
                    dialog._refresh_slot(self.slot_index)
        elif chosen and plugin_settings_act and chosen == plugin_settings_act:
            self.current_action.settings_callback()
            if hasattr(dialog, "_refresh_slot"):
                dialog._refresh_slot(self.slot_index)
        elif chosen and clear_act and chosen == clear_act:
            self.clear_requested.emit(self.slot_index)


class StreamDeckChassis(QFrame):
    """Realistic physical Stream Deck device body container."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Chassis")
        self.setStyleSheet(
            """
            QFrame#Chassis {
                background-color: #09090b;
                border: 1px solid #27272a;
                border-radius: 12px;
            }
            """
        )


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
        self.setWindowTitle("KeyDeck Control Center")
        self.setModal(True)
        self.resize(920, 680)
        self.setMinimumSize(820, 580)

        self.plugins = plugins or []
        self.plugin_errors = plugin_errors or []
        self.actions = actions
        self._reload_plugins_callback = reload_plugins_callback
        self._action_by_id = {action.action_id: action for action in actions}
        self._slot_actions = list(settings.slot_actions)
        self._slot_settings = dict(settings.slot_settings)
        self._slot_hotkeys = dict(settings.slot_hotkeys)
        self._auto_start = settings.auto_start
        self._high_priority = settings.high_priority
        self._button_widgets: list[PreviewDeckButtonWidget] = []
        self._settings_icon_path = str(self._project_root() / "icons" / "settings.svg")
        self._settings_icon = self._load_white_icon(Path(self._settings_icon_path), 16)
        self._normalize_slot_actions()

        self.setStyleSheet(
            """
            QDialog {
                background-color: #09090b;
                color: #f4f4f5;
                font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            }
            QListWidget#Sidebar {
                background-color: #121215;
                border: none;
                border-right: 1px solid #27272a;
                outline: none;
                padding: 16px 12px;
            }
            QListWidget#Sidebar::item {
                background-color: transparent;
                border-radius: 8px;
                padding: 14px 16px;
                color: #a1a1aa;
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 8px;
            }
            QListWidget#Sidebar::item:hover {
                background-color: #18181b;
                color: #f4f4f5;
            }
            QListWidget#Sidebar::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            QLabel#PageTitle {
                font-size: 18px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel#PageSubtitle {
                font-size: 12px;
                color: #71717a;
            }
            QFrame#Card {
                background-color: #18181b;
                border: 1px solid #27272a;
                border-radius: 12px;
            }
            QPushButton#UiButton {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                padding: 8px 16px;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#UiButton:hover {
                background-color: #3f3f46;
            }
            QPushButton#PrimaryButton {
                background-color: #2563eb;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#PrimaryButton:hover {
                background-color: #1d4ed8;
            }
            QSpinBox, QComboBox {
                background-color: #18181b;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 6px 10px;
                color: #ffffff;
                font-weight: 600;
            }
            """
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Sidebar Navigation
        self.sidebar = QListWidget(self)
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(220)

        item_deck = QListWidgetItem("🎛  Deck Editor")
        item_plugins = QListWidgetItem("🔌  Plugins & Services")
        item_system = QListWidgetItem("⚡  System & Autorun")

        self.sidebar.addItem(item_deck)
        self.sidebar.addItem(item_plugins)
        self.sidebar.addItem(item_system)
        self.sidebar.setCurrentItem(item_deck)

        root.addWidget(self.sidebar)

        # 2. Main Stacked Content Area
        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(24, 20, 24, 20)
        right_layout.setSpacing(16)

        self.stack = QStackedWidget(right_container)
        
        # Build Pages
        self.page_deck = self._build_deck_editor_page(settings)
        self.page_plugins = self._build_plugins_page(self.plugins, self.plugin_errors)
        self.page_system = self._build_system_page()

        self.stack.addWidget(self.page_deck)
        self.stack.addWidget(self.page_plugins)
        self.stack.addWidget(self.page_system)

        right_layout.addWidget(self.stack, 1)

        # Bottom Button Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch(1)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setObjectName("UiButton")
        cancel_btn.clicked.connect(self.reject)
        bottom_bar.addWidget(cancel_btn)

        save_btn = QPushButton("Save", self)
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(save_btn)

        right_layout.addLayout(bottom_bar)
        root.addWidget(right_container, 1)

        # Sidebar navigation connection
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        self._rebuild_preview()

    def _build_deck_editor_page(self, settings: AppSettings) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Page Header
        header_col = QVBoxLayout()
        header_col.setSpacing(2)
        title = QLabel("Deck Layout & Editor", page)
        title.setObjectName("PageTitle")
        sub = QLabel("Customize your virtual Stream Deck layout, grid size, and button actions.", page)
        sub.setObjectName("PageSubtitle")
        header_col.addWidget(title)
        header_col.addWidget(sub)
        layout.addLayout(header_col)

        # Settings Card (Rows / Cols / Size)
        card_controls = QFrame(page)
        card_controls.setObjectName("Card")
        ctrl_layout = QHBoxLayout(card_controls)
        ctrl_layout.setContentsMargins(16, 12, 16, 12)
        ctrl_layout.setSpacing(16)

        from PySide6.QtWidgets import QSlider

        # Rows Slider
        rows_col = QVBoxLayout()
        rows_lbl = QLabel(f"Rows: {settings.rows}", card_controls)
        rows_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #a1a1aa; background: transparent;")
        self.rows_spin = QSlider(Qt.Horizontal, card_controls)
        self.rows_spin.setRange(1, 8)
        self.rows_spin.setValue(settings.rows)
        self.rows_spin.setFixedWidth(120)
        self.rows_spin.valueChanged.connect(lambda v: rows_lbl.setText(f"Rows: {v}"))
        self.rows_spin.valueChanged.connect(self._rebuild_preview)
        rows_col.addWidget(rows_lbl)
        rows_col.addWidget(self.rows_spin)
        ctrl_layout.addLayout(rows_col)

        # Columns Slider
        cols_col = QVBoxLayout()
        cols_lbl = QLabel(f"Columns: {settings.columns}", card_controls)
        cols_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #a1a1aa; background: transparent;")
        self.columns_spin = QSlider(Qt.Horizontal, card_controls)
        self.columns_spin.setRange(1, 8)
        self.columns_spin.setValue(settings.columns)
        self.columns_spin.setFixedWidth(120)
        self.columns_spin.valueChanged.connect(lambda v: cols_lbl.setText(f"Columns: {v}"))
        self.columns_spin.valueChanged.connect(self._rebuild_preview)
        cols_col.addWidget(cols_lbl)
        cols_col.addWidget(self.columns_spin)
        ctrl_layout.addLayout(cols_col)

        # Button Size Slider
        size_col = QVBoxLayout()
        size_lbl = QLabel(f"Size: {settings.button_size.capitalize()}", card_controls)
        size_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #a1a1aa; background: transparent;")
        self.size_spin = QSlider(Qt.Horizontal, card_controls)
        self.size_spin.setRange(0, 2)
        sizes = ["small", "medium", "large"]
        try:
            self.size_spin.setValue(sizes.index(settings.button_size))
        except ValueError:
            self.size_spin.setValue(1)
        self.size_spin.setFixedWidth(120)
        self.size_spin.valueChanged.connect(lambda v: size_lbl.setText(f"Size: {sizes[v].capitalize()}"))
        self.size_spin.valueChanged.connect(self._rebuild_preview)
        size_col.addWidget(size_lbl)
        size_col.addWidget(self.size_spin)
        ctrl_layout.addLayout(size_col)

        ctrl_layout.addStretch(1)

        self.reload_plugins_btn = QPushButton("🔄 Reload Plugins", card_controls)
        self.reload_plugins_btn.setObjectName("UiButton")
        self.reload_plugins_btn.clicked.connect(self._reload_plugins)
        ctrl_layout.addWidget(self.reload_plugins_btn, 0, Qt.AlignVCenter)

        layout.addWidget(card_controls)

        # Device Chassis Preview
        self.chassis = StreamDeckChassis(page)
        chassis_layout = QVBoxLayout(self.chassis)
        chassis_layout.setContentsMargins(20, 20, 20, 20)

        self.preview_scroll = QScrollArea(self.chassis)
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setStyleSheet("background: transparent; border: none;")

        self.preview_host = QWidget(self.preview_scroll)
        self.preview_host.setStyleSheet("background: transparent;")
        self.preview_grid = QGridLayout(self.preview_host)
        self.preview_grid.setContentsMargins(0, 0, 0, 0)
        self.preview_grid.setHorizontalSpacing(14)
        self.preview_grid.setVerticalSpacing(14)
        self.preview_grid.setAlignment(Qt.AlignCenter)
        self.preview_scroll.setWidget(self.preview_host)

        chassis_layout.addWidget(self.preview_scroll)
        layout.addWidget(self.chassis, 1)

        return page

    def _build_plugins_page(self, plugins: list[PluginBase], errors: list[str]) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Loaded Plugins & Background Services", page)
        title.setObjectName("PageTitle")
        sub = QLabel("Manage background services, global key listeners, and plugin settings.", page)
        sub.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(sub)

        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget(scroll)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)

        if not plugins and not errors:
            lbl = QLabel("No active plugins found.", container)
            lbl.setStyleSheet("color: #71717a;")
            container_layout.addWidget(lbl)
        else:
            for plugin in plugins:
                card = QFrame(container)
                card.setObjectName("Card")
                card_layout = QHBoxLayout(card)
                card_layout.setContentsMargins(16, 14, 16, 14)
                card_layout.setSpacing(12)

                plugin_name = getattr(plugin, "plugin_name", plugin.__class__.__name__)
                plugin_id = plugin.context.plugin_id if plugin.context else getattr(plugin, "plugin_id", "core")

                # Custom Emoji mapping
                plugin_emoji = "🔌"
                if "SteamSwitcher" in plugin_id:
                    plugin_emoji = "👤"
                elif "SteamLauncher" in plugin_id or "Steam" in plugin_id:
                    plugin_emoji = "🎮"
                elif "GtaClearSession" in plugin_id or "Gta" in plugin_id:
                    plugin_emoji = "🧹"
                elif "ResolutionSwitcher" in plugin_id or "Resolution" in plugin_id:
                    plugin_emoji = "🖥️"
                elif "WaveLink" in plugin_id:
                    plugin_emoji = "🎵"
                elif "ZapretToggler" in plugin_id or "Zapret" in plugin_id:
                    plugin_emoji = "🌐"

                # Icon
                icon_lbl = QLabel(card)
                icon_lbl.setFixedSize(36, 36)
                icon_lbl.setStyleSheet("background-color: #27272a; border-radius: 8px; font-size: 16px;")
                icon_lbl.setAlignment(Qt.AlignCenter)
                icon_lbl.setText(plugin_emoji)
                card_layout.addWidget(icon_lbl)

                info_col = QVBoxLayout()
                info_col.setSpacing(2)
                
                name_lbl = QLabel(plugin_name, card)
                name_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #ffffff; background: transparent;")
                
                id_lbl = QLabel(f"ID: {plugin_id}  •  Status: Active Background Daemon", card)
                id_lbl.setStyleSheet("font-size: 11px; color: #22c55e; background: transparent;")

                info_col.addWidget(name_lbl)
                info_col.addWidget(id_lbl)
                card_layout.addLayout(info_col, 1)

                settings_btn = QPushButton("Configure", card)
                settings_btn.setObjectName("UiButton")
                settings_btn.clicked.connect(lambda _, p=plugin: p.open_settings())
                card_layout.addWidget(settings_btn)

                container_layout.addWidget(card)

            for err in errors:
                card = QFrame(container)
                card.setStyleSheet("background-color: #271616; border: 1px solid #7f1d1d; border-radius: 12px;")
                card_layout = QHBoxLayout(card)
                card_layout.setContentsMargins(16, 12, 16, 12)
                err_lbl = QLabel(f"⚠ Failed to load plugin: {err}", card)
                err_lbl.setStyleSheet("color: #f87171; font-weight: 600; font-size: 12px;")
                card_layout.addWidget(err_lbl)
                container_layout.addWidget(card)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        return page


    def _build_system_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("System & Startup Settings", page)
        title.setObjectName("PageTitle")
        sub = QLabel("Configure autostart, process priority, and low-level Windows integration.", page)
        sub.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(sub)

        card = QFrame(page)
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)

        # Theme Selector
        theme_layout = QHBoxLayout()
        theme_lbl = QLabel("Theme:", card)
        theme_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #a1a1aa; background: transparent;")
        theme_combo = QComboBox(card)
        theme_combo.addItem("Dark")
        theme_combo.addItem("Midnight (Coming Soon)")
        theme_combo.addItem("Light (Coming Soon)")
        theme_layout.addWidget(theme_lbl)
        theme_layout.addWidget(theme_combo)
        theme_layout.addStretch(1)
        card_layout.addLayout(theme_layout)

        card_layout.addSpacing(8)

        # Auto Start Checkbox
        self.chk_auto_start = ModernCheckBox("Enable Auto-Start on Windows Logon", card)
        self.chk_auto_start.setChecked(self._auto_start)
        card_layout.addWidget(self.chk_auto_start)

        auto_start_desc = QLabel("Configures Windows Task Scheduler to start KeyDeck in background.", card)
        auto_start_desc.setStyleSheet("color: #71717a; font-size: 11px; margin-left: 34px; background: transparent;")
        card_layout.addWidget(auto_start_desc)

        card_layout.addSpacing(4)

        # High Priority Checkbox
        self.chk_high_priority = ModernCheckBox("Enable High Process Priority", card)
        self.chk_high_priority.setChecked(self._high_priority)
        card_layout.addWidget(self.chk_high_priority)

        high_prio_desc = QLabel("Sets HIGH_PRIORITY_CLASS (0x80) for instant hotkey response.", card)
        high_prio_desc.setStyleSheet("color: #71717a; font-size: 11px; margin-left: 34px; background: transparent;")
        card_layout.addWidget(high_prio_desc)

        # Link auto_start with high_priority
        def on_auto_start_changed(state):
            is_checked = (state == Qt.Checked.value or state == 2)
            self._auto_start = is_checked
            self.chk_high_priority.setEnabled(is_checked)
            if not is_checked:
                self.chk_high_priority.setChecked(False)

        def on_high_priority_changed(state):
            self._high_priority = (state == Qt.Checked.value or state == 2)

        self.chk_auto_start.stateChanged.connect(on_auto_start_changed)
        self.chk_high_priority.stateChanged.connect(on_high_priority_changed)
        
        # Trigger initial state
        on_auto_start_changed(Qt.Checked.value if self._auto_start else Qt.Unchecked.value)

        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def to_settings(self) -> AppSettings:
        sizes = ["small", "medium", "large"]
        try:
            size_str = sizes[self.size_spin.value()]
        except IndexError:
            size_str = "medium"
            
        settings = AppSettings(
            rows=self.rows_spin.value(),
            columns=self.columns_spin.value(),
            button_size=size_str,
            slot_actions=self._slot_actions,
            slot_settings=self._slot_settings,
            slot_hotkeys=self._slot_hotkeys,
            auto_start=self._auto_start,
            high_priority=self._high_priority,
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

        sizes = ["small", "medium", "large"]
        try:
            size_str = sizes[self.size_spin.value()]
        except IndexError:
            size_str = "medium"
            
        button_size = BUTTON_SIZE_MAP.get(size_str, BUTTON_SIZE_MAP["medium"])
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
            self.preview_grid.addWidget(widget, row_idx, col_idx, alignment=Qt.AlignCenter)
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
        action = self._action_for_slot(slot)

        if not current_action_id or not action:
            self._open_action_picker(slot)
        else:
            if getattr(action, "action_settings_callback", None):
                self._open_action_settings(slot, action)
                self._refresh_slot(slot)
            elif action.settings_callback:
                action.settings_callback()
                self._refresh_slot(slot)
            else:
                self._open_action_picker(slot)

    def _open_action_picker(self, slot: int) -> None:
        current_action_id = self._slot_actions[slot]
        dialog = ActionPickerDialog(
            slot_number=slot + 1,
            current_action_id=current_action_id,
            actions=self.actions,
            parent=self,
        )
        if dialog.exec():
            self._slot_actions[slot] = dialog.selected_action_id()
            self._refresh_slot(slot)

    def _assign_hotkey(self, slot: int) -> None:
        from PySide6.QtWidgets import QInputDialog
        current_hotkey = self._slot_hotkeys.get(str(slot), "")
        text, ok = QInputDialog.getText(
            self,
            "Assign Hotkey",
            f"Enter hotkey for slot {slot + 1} (e.g. 'f16', 'ctrl+shift+a'):",
            text=current_hotkey
        )
        if ok:
            val = text.strip()
            if val:
                self._slot_hotkeys[str(slot)] = val
            else:
                self._slot_hotkeys.pop(str(slot), None)

    def _open_action_settings(self, slot: int, action: Action) -> None:
        if action.action_settings_callback:
            current_settings = self._slot_settings.get(str(slot), {})
            new_settings = action.action_settings_callback(slot, current_settings)
            if new_settings is not None:
                self._slot_settings[str(slot)] = new_settings

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
        settings = self._slot_settings.get(str(slot))
        self._button_widgets[slot].set_action(self._action_for_slot(slot), settings)

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
