from __future__ import annotations

import sys
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

from keydeck import __version__
from keydeck.config import BUTTON_SIZE_MAP, AppSettings, DeckPage
from keydeck.plugin_api import Action, PluginBase
from keydeck.plugin_manager import PluginInfo
from keydeck.ui.deck_button import SquircleButton
from keydeck.ui.controls import ToggleSwitch, add_dialog_header, style_dialog_buttons
from keydeck.ui.theme import size_dialog

MIME_SLOT_INDEX = "application/x-keydeck-slot-index"


class ActionPickerDialog(QDialog):
    def __init__(
        self,
        slot_number: int,
        current_action_id: str | None,
        actions: list[Action],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Choose action · Button {slot_number}")
        self.setModal(True)
        size_dialog(self, 760, 720, 620, 560)
        self._selected_id = current_action_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        eyebrow = QLabel(f"BUTTON {slot_number}", self)
        eyebrow.setObjectName("SectionEyebrow")
        layout.addWidget(eyebrow)

        header = QLabel("Choose an action", self)
        header.setObjectName("PageTitle")
        layout.addWidget(header)

        subtitle = QLabel(
            "Select what this button should do, or clear its current assignment.",
            self,
        )
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        self.search_edit = QLineEdit(self)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("Search actions or plugins")
        self.search_edit.setAccessibleName("Search available actions")
        layout.addWidget(self.search_edit)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("ActionList")
        self.list_widget.setUniformItemSizes(True)

        empty_item = QListWidgetItem("Clear this button")
        empty_item.setData(Qt.UserRole, "")
        self.list_widget.addItem(empty_item)

        for action in actions:
            item = QListWidgetItem(action.title)
            if action.icon_path:
                item.setIcon(QIcon(action.icon_path))
            item.setToolTip(f"{action.title}\nProvided by {action.plugin_id}")
            item.setData(Qt.UserRole, action.action_id)
            self.list_widget.addItem(item)
            if current_action_id == action.action_id:
                self.list_widget.setCurrentItem(item)

        if current_action_id is None:
            self.list_widget.setCurrentItem(empty_item)

        self.list_widget.itemDoubleClicked.connect(self._on_select)
        self.list_widget.currentItemChanged.connect(self._update_selection_label)
        self.search_edit.textChanged.connect(self._filter_actions)
        layout.addWidget(self.list_widget, 1)

        self.selection_label = QLabel(self)
        self.selection_label.setObjectName("Muted")
        layout.addWidget(self.selection_label)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setObjectName("QuietButton")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        self.select_button = QPushButton("Assign action", self)
        self.select_button.setObjectName("PrimaryButton")
        self.select_button.clicked.connect(self._on_select)
        btn_box.addWidget(self.select_button)

        layout.addLayout(btn_box)
        self._update_selection_label(self.list_widget.currentItem(), None)

    def _filter_actions(self, text: str) -> None:
        query = text.strip().casefold()
        first_visible = None
        first_visible_action = None
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            is_clear_action = not item.data(Qt.UserRole)
            hidden = (
                not is_clear_action
                and query not in item.text().casefold()
                and query not in item.toolTip().casefold()
            )
            item.setHidden(hidden)
            if not hidden and first_visible is None:
                first_visible = item
            if not hidden and not is_clear_action and first_visible_action is None:
                first_visible_action = item
        current = self.list_widget.currentItem()
        if current is None or current.isHidden():
            self.list_widget.setCurrentItem(first_visible_action or first_visible)

    def _update_selection_label(self, current, _previous) -> None:
        if current is None:
            self.selection_label.setText("No matching actions.")
            self.select_button.setEnabled(False)
            return
        action_id = current.data(Qt.UserRole)
        self.selection_label.setText(
            "This button will be cleared."
            if not action_id
            else f"Provided by {current.toolTip().splitlines()[-1].removeprefix('Provided by ')}"
        )
        self.select_button.setEnabled(True)

    def _on_select(self) -> None:
        item = self.list_widget.currentItem()
        if item:
            self._selected_id = item.data(Qt.UserRole)
        self.accept()

    def selected_action_id(self) -> str | None:
        return self._selected_id if self._selected_id else None


class ButtonAppearanceDialog(QDialog):
    def __init__(
        self,
        title: str,
        icon_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Button appearance")
        self.setModal(True)
        size_dialog(self, 560, 300, 460, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        add_dialog_header(
            layout,
            "Button appearance",
            "Customize the title and icon shown for this button.",
            self,
        )

        form = QFormLayout()
        form.setSpacing(10)
        self.title_edit = QLineEdit(title, self)
        self.title_edit.setPlaceholderText("Leave blank to use the plugin title")
        form.addRow("Button title", self.title_edit)

        icon_row = QWidget(self)
        icon_layout = QHBoxLayout(icon_row)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(8)
        self.icon_edit = QLineEdit(icon_path, icon_row)
        self.icon_edit.setReadOnly(True)
        self.icon_edit.setToolTip(icon_path)
        icon_layout.addWidget(self.icon_edit, 1)

        browse_button = QPushButton("Browse…", icon_row)
        browse_button.setObjectName("QuietButton")
        browse_button.clicked.connect(self._browse_icon)
        icon_layout.addWidget(browse_button)

        clear_button = QPushButton("Clear", icon_row)
        clear_button.setObjectName("QuietButton")
        clear_button.clicked.connect(self.icon_edit.clear)
        icon_layout.addWidget(clear_button)
        form.addRow("Custom icon", icon_row)
        layout.addLayout(form)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        style_dialog_buttons(button_box, QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _browse_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose button icon",
            self.icon_edit.text(),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.ico *.svg);;All files (*)",
        )
        if not path:
            return
        if QIcon(path).isNull():
            QMessageBox.warning(self, "Button icon", "The selected file is not a supported image.")
            return
        self.icon_edit.setText(str(Path(path).resolve()))
        self.icon_edit.setToolTip(self.icon_edit.text())


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
            radius = max(4.0, float(min(w, h) * 0.04))
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
        self.button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.button.customContextMenuRequested.connect(
            lambda position: self._show_context_menu(
                self.button.mapToGlobal(position)
            )
        )
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

    def set_action(
        self,
        action: Action | None,
        settings: dict | None = None,
        overrides: dict[str, str] | None = None,
    ) -> None:
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
        custom_icon_path = overrides.get("icon_path", "") if overrides else ""
        if custom_icon_path and Path(custom_icon_path).is_file():
            icon_path = custom_icon_path

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
        if overrides and overrides.get("title"):
            title = overrides["title"]

        self._set_title(title)
        self.title.setStyleSheet("color: #f4f4f5; font-size: 10px; font-weight: 600;")

    def _set_title(self, title: str) -> None:
        metrics = QFontMetrics(self.title.font())
        self.title.setText(metrics.elidedText(title, Qt.ElideRight, self.title.width()))

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self._show_context_menu(event.globalPos())
        event.accept()

    def _show_context_menu(self, global_position: QPoint) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        assign_act = menu.addAction("Assign / Change Action...")
        
        hotkey_act = None
        appearance_act = None
        settings_act = None
        plugin_settings_act = None
        clear_act = None
        
        if self.current_action is not None:
            hotkey_act = menu.addAction("Assign Hotkey...")
            appearance_act = menu.addAction("Button Appearance...")
            
            if getattr(self.current_action, "action_settings_callback", None):
                settings_act = menu.addAction("Action Settings...")
                
            if self.current_action.settings_callback:
                plugin_settings_act = menu.addAction("Plugin Settings...")

            menu.addSeparator()
            clear_act = menu.addAction("Clear Button")

        chosen = menu.exec(global_position)
        dialog = self.window()
        if chosen == assign_act:
            if hasattr(dialog, "_open_action_picker"):
                dialog._open_action_picker(self.slot_index)
        elif chosen and appearance_act and chosen == appearance_act:
            if hasattr(dialog, "_open_button_appearance"):
                dialog._open_button_appearance(self.slot_index)
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
            if hasattr(dialog, "_refresh_plugin_actions"):
                dialog._refresh_plugin_actions()
            if hasattr(dialog, "_refresh_slot"):
                dialog._refresh_slot(self.slot_index)
        elif chosen and clear_act and chosen == clear_act:
            self.clear_requested.emit(self.slot_index)


class StreamDeckChassis(QFrame):
    """Realistic physical Stream Deck device body container."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Chassis")


class SettingsDialog(QDialog):
    update_check_requested = Signal()
    update_install_requested = Signal()
    autostart_task_requested = Signal(bool)
    actions_changed = Signal(object)

    def __init__(
        self,
        settings: AppSettings,
        actions: list[Action],
        plugins: list[PluginBase] | None = None,
        plugin_errors: list[str] | None = None,
        reload_plugins_callback: (
            Callable[
                [set[str]],
                tuple[list[Action], list[PluginBase], list[str], list[PluginInfo]],
            ]
            | None
        ) = None,
        parent: QWidget | None = None,
        refresh_actions_callback: Callable[[], list[Action]] | None = None,
        available_plugins: list[PluginInfo] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("KeyDeck Settings")
        self.setModal(True)
        size_dialog(self, 1240, 900, 1040, 740)

        self.plugins = plugins or []
        self.plugin_errors = plugin_errors or []
        self.actions = actions
        self._disabled_plugins = set(settings.disabled_plugins)
        self.available_plugins = (
            list(available_plugins)
            if available_plugins is not None
            else self._build_plugin_catalog(self.plugins, self.actions)
        )
        self._plugins_by_id = {self._plugin_id(plugin): plugin for plugin in self.plugins}
        self._reload_plugins_callback = reload_plugins_callback
        self._refresh_actions_callback = refresh_actions_callback
        self._action_by_id = {action.action_id: action for action in actions}
        self._pages = deepcopy(settings.pages) or [
            DeckPage(
                rows=settings.rows,
                columns=settings.columns,
                slot_actions=list(settings.slot_actions),
                slot_settings=dict(settings.slot_settings),
            ).clamp()
        ]
        self._selected_page_index = max(
            0,
            min(settings.active_page, len(self._pages) - 1),
        )
        self._slot_hotkeys = dict(settings.slot_hotkeys)
        self._right_alt_toggle = settings.right_alt_toggle
        self._infinite_scroll = settings.infinite_scroll
        self._auto_start = settings.auto_start
        self._high_priority = settings.high_priority
        self._run_as_admin = settings.run_as_admin
        self._current_version = __version__
        self._button_widgets: list[PreviewDeckButtonWidget] = []
        self._preview_rebuild_pending = False
        self._preview_generation = 0
        self._settings_icon_path = str(self._project_root() / "icons" / "settings.svg")
        self._settings_icon = self._load_white_icon(Path(self._settings_icon_path), 16)
        self._normalize_slot_actions()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav_panel = QFrame(self)
        nav_panel.setObjectName("NavigationPanel")
        nav_panel.setFixedWidth(230)
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(18, 24, 14, 18)
        nav_layout.setSpacing(10)

        brand = QLabel("KEYDECK", nav_panel)
        brand.setObjectName("SectionTitle")
        nav_layout.addWidget(brand)
        nav_caption = QLabel("CONTROL CENTER", nav_panel)
        nav_caption.setObjectName("SectionEyebrow")
        nav_layout.addWidget(nav_caption)
        nav_layout.addSpacing(20)

        section_label = QLabel("SETTINGS", nav_panel)
        section_label.setObjectName("SectionEyebrow")
        nav_layout.addWidget(section_label)

        self.sidebar = QListWidget(nav_panel)
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFrameShape(QFrame.NoFrame)
        for title in ("Button layout", "Plugins", "System", "Updates"):
            self.sidebar.addItem(QListWidgetItem(title))
        nav_layout.addWidget(self.sidebar, 1)

        version_label = QLabel(f"KeyDeck  ·  v{self._current_version}", nav_panel)
        version_label.setObjectName("Muted")
        nav_layout.addWidget(version_label)
        root.addWidget(nav_panel)

        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(30, 24, 30, 20)
        right_layout.setSpacing(18)

        heading = QVBoxLayout()
        heading.setSpacing(4)
        self.section_title = QLabel(right_container)
        self.section_title.setObjectName("PageTitle")
        self.section_description = QLabel(right_container)
        self.section_description.setObjectName("PageSubtitle")
        self.section_description.setWordWrap(True)
        heading.addWidget(self.section_title)
        heading.addWidget(self.section_description)
        right_layout.addLayout(heading)

        self.stack = QStackedWidget(right_container)
        self.page_deck = self._build_deck_editor_page(settings)
        self.page_plugins = self._build_plugins_page(self.plugins, self.plugin_errors)
        self.page_system = self._build_system_page()
        self.page_updates = self._build_updates_page()

        self.stack.addWidget(self.page_deck)
        self.stack.addWidget(self.page_plugins)
        self.stack.addWidget(self.page_system)
        self.stack.addWidget(self.page_updates)

        right_layout.addWidget(self.stack, 1)

        bottom_bar = QHBoxLayout()
        save_hint = QLabel("Changes are applied when saved.", right_container)
        save_hint.setObjectName("Muted")
        bottom_bar.addWidget(save_hint)
        bottom_bar.addStretch(1)

        cancel_btn = QPushButton("Cancel", right_container)
        cancel_btn.setObjectName("QuietButton")
        cancel_btn.clicked.connect(self.reject)
        bottom_bar.addWidget(cancel_btn)

        save_btn = QPushButton("Save changes", right_container)
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(save_btn)

        right_layout.addLayout(bottom_bar)
        root.addWidget(right_container, 1)

        self.sidebar.currentRowChanged.connect(self._select_section)
        self.sidebar.setCurrentRow(0)

        self._select_section(0)
        self._refresh_page_list()
        self._schedule_preview_rebuild()

    @property
    def _current_page(self) -> DeckPage:
        return self._pages[self._selected_page_index]

    @property
    def _slot_actions(self) -> list[str | None]:
        return self._current_page.slot_actions

    @_slot_actions.setter
    def _slot_actions(self, actions: list[str | None]) -> None:
        self._current_page.slot_actions = actions

    @property
    def _slot_settings(self) -> dict[str, dict]:
        return self._current_page.slot_settings

    @_slot_settings.setter
    def _slot_settings(self, settings: dict[str, dict]) -> None:
        self._current_page.slot_settings = settings

    @property
    def _slot_overrides(self) -> dict[str, dict[str, str]]:
        return self._current_page.slot_overrides

    @_slot_overrides.setter
    def _slot_overrides(self, overrides: dict[str, dict[str, str]]) -> None:
        self._current_page.slot_overrides = overrides

    def _select_section(self, section_index: int) -> None:
        sections = (
            ("Button layout", "Organize pages, grid dimensions, and button assignments."),
            ("Plugins", "Enable, disable, and configure installed plugins."),
            ("System", "Configure startup behavior and keyboard interaction."),
            ("Updates", "Check the installed version and manage KeyDeck updates."),
        )
        if not 0 <= section_index < len(sections):
            return
        title, description = sections[section_index]
        self.stack.setCurrentIndex(section_index)
        self.section_title.setText(title)
        self.section_description.setText(description)

    def _refresh_page_list(self) -> None:
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for index, page in enumerate(self._pages):
            item = QListWidgetItem(page.name)
            item.setToolTip(
                f"{page.rows} rows × {page.columns} columns · {page.rows * page.columns} buttons"
            )
            item.setData(Qt.UserRole, page.page_id)
            item.setData(Qt.UserRole + 1, index)
            self.page_list.addItem(item)
        self.page_list.setCurrentRow(self._selected_page_index)
        self.page_list.blockSignals(False)
        self.remove_page_btn.setEnabled(self._selected_page_index > 0)

    def _update_page_tooltip(self, page_index: int) -> None:
        if not 0 <= page_index < len(self._pages):
            return
        item = self.page_list.item(page_index)
        if item is None:
            return
        page = self._pages[page_index]
        item.setToolTip(
            f"{page.rows} rows × {page.columns} columns · {page.rows * page.columns} buttons"
        )

    def _set_page_rows(self, rows: int) -> None:
        self._current_page.rows = rows
        self.rows_label.setText(f"Rows: {rows}")
        self._update_page_tooltip(self._selected_page_index)
        self._schedule_preview_rebuild()

    def _set_page_columns(self, columns: int) -> None:
        self._current_page.columns = columns
        self.columns_label.setText(f"Columns: {columns}")
        self._update_page_tooltip(self._selected_page_index)
        self._schedule_preview_rebuild()

    def _select_page(self, page_index: int) -> None:
        if not 0 <= page_index < len(self._pages):
            return
        self._selected_page_index = page_index
        page = self._current_page
        self.rows_spin.setValue(page.rows)
        self.columns_spin.setValue(page.columns)
        self.rows_label.setText(f"Rows: {page.rows}")
        self.columns_label.setText(f"Columns: {page.columns}")
        self.preview_page_title.setText(page.name)
        self.page_position_label.setText(
            f"Page {page_index + 1} of {len(self._pages)}"
        )
        self._refresh_page_list()
        self._schedule_preview_rebuild()

    def _add_page(self) -> None:
        existing_names = {page.name.casefold() for page in self._pages}
        page_number = 1
        while f"page {page_number}".casefold() in existing_names:
            page_number += 1
        self._pages.append(
            DeckPage(
                name=f"Page {page_number}",
                rows=self.rows_spin.value(),
                columns=self.columns_spin.value(),
            ).clamp()
        )
        self._selected_page_index = len(self._pages) - 1
        self._refresh_page_list()
        self._select_page(self._selected_page_index)

    def _rename_page(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        page = self._current_page
        name, accepted = QInputDialog.getText(
            self,
            "Rename page",
            "Page name:",
            text=page.name,
        )
        if accepted and name.strip():
            page.name = name.strip()
            self._refresh_page_list()
            self.preview_page_title.setText(page.name)

    def _remove_page(self) -> None:
        if self._selected_page_index == 0:
            return
        page = self._current_page
        answer = QMessageBox.question(
            self,
            "Remove page",
            f"Remove '{page.name}' and all of its button assignments?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._slot_hotkeys = {
            key: value
            for key, value in self._slot_hotkeys.items()
            if not key.startswith(f"{page.page_id}:")
        }
        self._pages.pop(self._selected_page_index)
        self._selected_page_index = min(self._selected_page_index, len(self._pages) - 1)
        self._refresh_page_list()
        self._select_page(self._selected_page_index)

    def _build_deck_editor_page(self, settings: AppSettings) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        pages_card = QFrame(page)
        pages_card.setObjectName("Card")
        pages_card.setMinimumWidth(170)
        pages_card.setMaximumWidth(205)
        pages_layout = QVBoxLayout(pages_card)
        pages_layout.setContentsMargins(14, 16, 14, 14)
        pages_layout.setSpacing(10)

        pages_title = QLabel("Pages", pages_card)
        pages_title.setObjectName("SectionTitle")
        pages_layout.addWidget(pages_title)
        pages_hint = QLabel("Each page has its own button grid.", pages_card)
        pages_hint.setObjectName("Muted")
        pages_hint.setWordWrap(True)
        pages_layout.addWidget(pages_hint)

        self.page_list = QListWidget(pages_card)
        self.page_list.setObjectName("PageList")
        self.page_list.currentRowChanged.connect(self._select_page)
        pages_layout.addWidget(self.page_list, 1)

        self.add_page_btn = QPushButton("Add page", pages_card)
        self.add_page_btn.setObjectName("PrimaryButton")
        self.add_page_btn.clicked.connect(self._add_page)
        pages_layout.addWidget(self.add_page_btn)

        page_actions = QHBoxLayout()
        self.rename_page_btn = QPushButton("Rename", pages_card)
        self.rename_page_btn.setObjectName("QuietButton")
        self.rename_page_btn.clicked.connect(self._rename_page)
        page_actions.addWidget(self.rename_page_btn)
        self.remove_page_btn = QPushButton("Remove", pages_card)
        self.remove_page_btn.setObjectName("DangerButton")
        self.remove_page_btn.clicked.connect(self._remove_page)
        page_actions.addWidget(self.remove_page_btn)
        pages_layout.addLayout(page_actions)

        separator = QFrame(pages_card)
        separator.setFrameShape(QFrame.HLine)
        pages_layout.addWidget(separator)
        self.chk_infinite_scroll = ToggleSwitch("Wrap pages at ends", pages_card)
        self.chk_infinite_scroll.setChecked(self._infinite_scroll)
        self.chk_infinite_scroll.setToolTip(
            "Continue from the last page to the first when scrolling."
        )
        self.chk_infinite_scroll.stateChanged.connect(
            lambda state: setattr(
                self,
                "_infinite_scroll",
                state == Qt.Checked.value or state == 2,
            )
        )
        pages_layout.addWidget(self.chk_infinite_scroll)
        layout.addWidget(pages_card)

        editor = QWidget(page)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(12)

        card_controls = QFrame(editor)
        card_controls.setObjectName("Card")
        ctrl_layout = QVBoxLayout(card_controls)
        ctrl_layout.setContentsMargins(16, 14, 16, 14)
        ctrl_layout.setSpacing(12)

        controls_heading = QHBoxLayout()
        controls_title = QLabel("Grid and button size", card_controls)
        controls_title.setObjectName("SectionTitle")
        controls_heading.addWidget(controls_title)
        controls_heading.addStretch(1)
        self.page_position_label = QLabel("", card_controls)
        self.page_position_label.setObjectName("Muted")
        controls_heading.addWidget(self.page_position_label)
        ctrl_layout.addLayout(controls_heading)

        sliders = QHBoxLayout()
        sliders.setSpacing(20)

        from PySide6.QtWidgets import QSlider

        rows_col = QVBoxLayout()
        self.rows_label = QLabel(f"Rows: {self._current_page.rows}", card_controls)
        self.rows_label.setObjectName("Muted")
        self.rows_spin = QSlider(Qt.Horizontal, card_controls)
        self.rows_spin.setRange(1, 8)
        self.rows_spin.setValue(self._current_page.rows)
        self.rows_spin.setMinimumWidth(100)
        self.rows_spin.setToolTip("Number of button rows on this page.")
        self.rows_spin.valueChanged.connect(self._set_page_rows)
        rows_col.addWidget(self.rows_label)
        rows_col.addWidget(self.rows_spin)
        sliders.addLayout(rows_col, 1)

        cols_col = QVBoxLayout()
        self.columns_label = QLabel(f"Columns: {self._current_page.columns}", card_controls)
        self.columns_label.setObjectName("Muted")
        self.columns_spin = QSlider(Qt.Horizontal, card_controls)
        self.columns_spin.setRange(1, 8)
        self.columns_spin.setValue(self._current_page.columns)
        self.columns_spin.setMinimumWidth(100)
        self.columns_spin.setToolTip("Number of button columns on this page.")
        self.columns_spin.valueChanged.connect(self._set_page_columns)
        cols_col.addWidget(self.columns_label)
        cols_col.addWidget(self.columns_spin)
        sliders.addLayout(cols_col, 1)

        size_col = QVBoxLayout()
        self.size_label = QLabel(f"Size: {settings.button_size.capitalize()}", card_controls)
        self.size_label.setObjectName("Muted")
        self.size_spin = QSlider(Qt.Horizontal, card_controls)
        self.size_spin.setRange(0, 2)
        sizes = ["small", "medium", "large"]
        try:
            self.size_spin.setValue(sizes.index(settings.button_size))
        except ValueError:
            self.size_spin.setValue(1)
        self.size_spin.setMinimumWidth(100)
        self.size_spin.setToolTip("Button size applies to every page.")
        self.size_spin.valueChanged.connect(lambda v: self.size_label.setText(f"Size: {sizes[v].capitalize()}"))
        self.size_spin.valueChanged.connect(self._schedule_preview_rebuild)
        size_col.addWidget(self.size_label)
        size_col.addWidget(self.size_spin)
        sliders.addLayout(size_col, 1)
        ctrl_layout.addLayout(sliders)
        editor_layout.addWidget(card_controls)

        preview_header = QHBoxLayout()
        self.preview_page_title = QLabel(self._current_page.name, editor)
        self.preview_page_title.setObjectName("SectionTitle")
        preview_header.addWidget(self.preview_page_title)
        preview_header.addStretch(1)
        preview_hint = QLabel(
            "Click to assign · right-click for button options",
            editor,
        )
        preview_hint.setObjectName("Muted")
        preview_header.addWidget(preview_hint)
        editor_layout.addLayout(preview_header)

        self.chassis = StreamDeckChassis(editor)
        chassis_layout = QVBoxLayout(self.chassis)
        chassis_layout.setContentsMargins(16, 16, 16, 16)

        self.preview_scroll = QScrollArea(self.chassis)
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.viewport().setObjectName("DeckPreviewViewport")
        self.preview_scroll.viewport().setStyleSheet(
            "background-color: #242424; border: none;"
        )

        self.preview_host = QWidget(self.preview_scroll)
        self.preview_grid = QGridLayout(self.preview_host)
        self.preview_grid.setContentsMargins(0, 0, 0, 0)
        self.preview_grid.setHorizontalSpacing(12)
        self.preview_grid.setVerticalSpacing(12)
        self.preview_grid.setAlignment(Qt.AlignCenter)
        self.preview_scroll.setWidget(self.preview_host)

        chassis_layout.addWidget(self.preview_scroll)
        editor_layout.addWidget(self.chassis, 1)
        layout.addWidget(editor, 1)

        return page

    def _build_plugins_page(self, plugins: list[PluginBase], errors: list[str]) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        self.plugin_count_label = QLabel("", page)
        self.plugin_count_label.setObjectName("Muted")
        toolbar.addWidget(self.plugin_count_label)
        toolbar.addStretch(1)
        self.reload_plugins_btn = QPushButton("Reload plugins", page)
        self.reload_plugins_btn.setObjectName("QuietButton")
        self.reload_plugins_btn.clicked.connect(self._reload_plugins)
        self.reload_plugins_btn.setEnabled(self._reload_plugins_callback is not None)
        toolbar.addWidget(self.reload_plugins_btn)
        layout.addLayout(toolbar)

        content = QHBoxLayout()
        content.setSpacing(14)

        list_card = QFrame(page)
        list_card.setObjectName("Card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(10, 12, 10, 10)
        list_layout.setSpacing(8)
        list_heading = QLabel("Available plugins", list_card)
        list_heading.setObjectName("SectionTitle")
        list_layout.addWidget(list_heading)
        self.plugin_list = QListWidget(list_card)
        self.plugin_list.setObjectName("PluginList")
        self.plugin_list.currentRowChanged.connect(self._show_plugin_details)
        list_layout.addWidget(self.plugin_list, 1)
        content.addWidget(list_card, 1)

        details_card = QFrame(page)
        details_card.setObjectName("Card")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(20, 20, 20, 18)
        details_layout.setSpacing(8)

        self.plugin_name_label = QLabel("Select a plugin", details_card)
        self.plugin_name_label.setObjectName("PageTitle")
        self.plugin_id_label = QLabel("", details_card)
        self.plugin_id_label.setObjectName("Muted")
        self.plugin_status_label = QLabel("", details_card)
        self.plugin_status_label.setObjectName("StatusBadge")
        self.plugin_enabled_toggle = ToggleSwitch("Enable this plugin", details_card)
        self.plugin_enabled_toggle.toggled.connect(self._set_selected_plugin_enabled)
        self.plugin_summary_label = QLabel(
            "Choose a plugin to view its status and settings.",
            details_card,
        )
        self.plugin_summary_label.setObjectName("PageSubtitle")
        self.plugin_summary_label.setWordWrap(True)
        self.plugin_actions_label = QLabel("", details_card)
        self.plugin_actions_label.setObjectName("Muted")
        details_layout.addWidget(self.plugin_name_label)
        details_layout.addWidget(self.plugin_id_label)
        details_layout.addWidget(self.plugin_status_label, 0, Qt.AlignLeft)
        details_layout.addWidget(self.plugin_enabled_toggle)
        details_layout.addSpacing(8)
        details_layout.addWidget(self.plugin_summary_label)
        details_layout.addWidget(self.plugin_actions_label)

        self.configure_plugin_btn = QPushButton("Open plugin settings", details_card)
        self.configure_plugin_btn.setObjectName("PrimaryButton")
        self.configure_plugin_btn.clicked.connect(self._configure_selected_plugin)
        details_layout.addWidget(self.configure_plugin_btn, 0, Qt.AlignLeft)
        details_layout.addStretch(1)

        self.plugin_error_card = QFrame(details_card)
        self.plugin_error_card.setObjectName("ErrorCard")
        error_layout = QVBoxLayout(self.plugin_error_card)
        error_layout.setContentsMargins(14, 12, 14, 12)
        error_layout.setSpacing(6)
        error_heading = QLabel("Plugin load issues", self.plugin_error_card)
        error_heading.setObjectName("ErrorTitle")
        error_layout.addWidget(error_heading)
        self.plugin_error_list = QListWidget(self.plugin_error_card)
        self.plugin_error_list.setObjectName("ErrorList")
        self.plugin_error_list.setMaximumHeight(132)
        error_layout.addWidget(self.plugin_error_list)
        details_layout.addWidget(self.plugin_error_card)
        content.addWidget(details_card, 2)

        layout.addLayout(content, 1)
        self._populate_plugin_list(plugins, errors, self.available_plugins)

        return page

    def _plugin_id(self, plugin: PluginBase) -> str:
        return (
            plugin.context.plugin_id
            if plugin.context
            else getattr(plugin, "plugin_id", "core")
        )

    def _build_plugin_catalog(
        self,
        plugins: list[PluginBase],
        actions: list[Action],
    ) -> list[PluginInfo]:
        catalog: dict[str, PluginInfo] = {}
        for plugin in plugins:
            plugin_id = self._plugin_id(plugin)
            catalog[plugin_id] = PluginInfo(
                plugin_id,
                getattr(plugin, "plugin_name", plugin.__class__.__name__),
            )
        for action in actions:
            catalog.setdefault(action.plugin_id, PluginInfo(action.plugin_id, action.title))
        return list(catalog.values())

    def _populate_plugin_list(
        self,
        plugins: list[PluginBase],
        errors: list[str],
        available_plugins: list[PluginInfo] | None = None,
    ) -> None:
        selected_plugin_id = (
            self.plugin_list.currentItem().data(Qt.UserRole)
            if self.plugin_list.currentItem()
            else None
        )
        self.plugins = plugins
        self._plugins_by_id = {self._plugin_id(plugin): plugin for plugin in plugins}
        self.plugin_errors = errors
        if available_plugins is not None:
            self.available_plugins = list(available_plugins)
        else:
            self.available_plugins = self._build_plugin_catalog(plugins, self.actions)
        self.plugin_list.blockSignals(True)
        self.plugin_list.clear()
        selected_row = 0
        for index, plugin_info in enumerate(self.available_plugins):
            item = QListWidgetItem(plugin_info.plugin_name)
            item.setData(Qt.UserRole, plugin_info.plugin_id)
            item.setToolTip(plugin_info.plugin_id)
            self.plugin_list.addItem(item)
            if plugin_info.plugin_id == selected_plugin_id:
                selected_row = index
        self.plugin_list.setCurrentRow(
            selected_row if self.available_plugins else -1
        )
        self.plugin_list.blockSignals(False)

        disabled_count = sum(
            plugin.plugin_id in self._disabled_plugins
            for plugin in self.available_plugins
        )
        self.plugin_count_label.setText(
            f"{len(self.available_plugins)} available · {disabled_count} disabled"
        )
        self.plugin_error_list.clear()
        for error in errors:
            item = QListWidgetItem(error)
            item.setToolTip(error)
            self.plugin_error_list.addItem(item)
        self.plugin_error_card.setVisible(bool(errors))
        if self.available_plugins:
            self._show_plugin_details(self.plugin_list.currentRow())
        else:
            self._show_plugin_details(-1)

    def _show_plugin_details(self, row: int) -> None:
        if not 0 <= row < len(self.available_plugins):
            self.plugin_name_label.setText("No plugin selected")
            self.plugin_id_label.clear()
            self.plugin_status_label.clear()
            self.plugin_summary_label.setText(
                "No installed plugins were found. Check plugin load issues below if any are listed."
            )
            self.plugin_actions_label.clear()
            self.configure_plugin_btn.setEnabled(False)
            self.plugin_enabled_toggle.setEnabled(False)
            return

        plugin_info = self.available_plugins[row]
        plugin_id = plugin_info.plugin_id
        plugin_name = plugin_info.plugin_name
        action_count = sum(action.plugin_id == plugin_id for action in self.actions)
        disabled = plugin_id in self._disabled_plugins
        plugin = self._plugins_by_id.get(plugin_id)
        has_settings = plugin is not None or any(
            action.plugin_id == plugin_id and action.settings_callback is not None
            for action in self.actions
        )
        self.plugin_name_label.setText(plugin_name)
        self.plugin_id_label.setText(plugin_id)
        self.plugin_status_label.setText(
            "Disabled" if disabled else "Loaded" if plugin is not None or action_count else "Not loaded"
        )
        if disabled:
            summary = (
                "This plugin is disabled. Its actions and background services are stopped "
                "when changes are saved; its button assignments are kept."
            )
        elif plugin is None and not action_count:
            summary = "This plugin is enabled but was not loaded. Check plugin load issues below."
        else:
            summary = (
                "Configure this plugin's shared settings. Button-specific options remain "
                "available from the layout preview."
            )
        self.plugin_summary_label.setText(summary)
        self.plugin_actions_label.setText(
            f"{action_count} active {'action' if action_count == 1 else 'actions'}"
        )
        self.plugin_enabled_toggle.blockSignals(True)
        self.plugin_enabled_toggle.setChecked(not disabled)
        self.plugin_enabled_toggle.blockSignals(False)
        self.plugin_enabled_toggle.setEnabled(True)
        self.configure_plugin_btn.setEnabled(not disabled and has_settings)

    def _configure_selected_plugin(self) -> None:
        row = self.plugin_list.currentRow()
        if not 0 <= row < len(self.available_plugins):
            return
        plugin_id = self.available_plugins[row].plugin_id
        if plugin_id in self._disabled_plugins:
            return
        plugin = self._plugins_by_id.get(plugin_id)
        if plugin is not None:
            plugin.open_settings()
        else:
            callback = next(
                (
                    action.settings_callback
                    for action in self.actions
                    if action.plugin_id == plugin_id and action.settings_callback is not None
                ),
                None,
            )
            if callback is not None:
                callback()
        self._refresh_plugin_actions()

    def _set_selected_plugin_enabled(self, enabled: bool) -> None:
        item = self.plugin_list.currentItem()
        if item is None:
            return
        plugin_id = item.data(Qt.UserRole)
        if enabled:
            self._disabled_plugins.discard(plugin_id)
        else:
            self._disabled_plugins.add(plugin_id)
        self._show_plugin_details(self.plugin_list.currentRow())

    def _refresh_plugin_actions(self) -> None:
        if self._refresh_actions_callback is not None:
            self.actions = self._refresh_actions_callback()
            self._action_by_id = {action.action_id: action for action in self.actions}
            self._normalize_slot_actions()
            self._show_plugin_details(self.plugin_list.currentRow())
            self._schedule_preview_rebuild()
            self.actions_changed.emit(self.actions)


    def _build_system_page(self) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        startup_card = QFrame(content)
        startup_card.setObjectName("Card")
        startup_layout = QVBoxLayout(startup_card)
        startup_layout.setContentsMargins(18, 18, 18, 18)
        startup_layout.setSpacing(10)

        startup_title = QLabel("Startup", startup_card)
        startup_title.setObjectName("SectionTitle")
        startup_layout.addWidget(startup_title)
        startup_description = QLabel(
            "Choose whether KeyDeck starts with Windows and which permissions it uses.",
            startup_card,
        )
        startup_description.setObjectName("PageSubtitle")
        startup_description.setWordWrap(True)
        startup_layout.addWidget(startup_description)

        self.chk_auto_start = ToggleSwitch(
            "Start KeyDeck when I sign in to Windows",
            startup_card,
        )
        self.chk_auto_start.setChecked(self._auto_start)
        startup_layout.addWidget(self.chk_auto_start)

        auto_start_desc = QLabel(
            "Uses Windows Task Scheduler to launch KeyDeck in the background.",
            startup_card,
        )
        auto_start_desc.setObjectName("Muted")
        auto_start_desc.setWordWrap(True)
        startup_layout.addWidget(auto_start_desc)

        self.autostart_task_button = QPushButton(
            "Create or update startup task",
            startup_card,
        )
        self.autostart_task_button.setObjectName("QuietButton")
        self.autostart_task_button.setEnabled(self._auto_start)
        self.autostart_task_button.setToolTip(
            "Register the current auto-start and administrator settings immediately."
        )
        self.autostart_task_button.clicked.connect(
            lambda: self.autostart_task_requested.emit(self._run_as_admin)
        )
        startup_layout.addWidget(self.autostart_task_button, 0, Qt.AlignLeft)

        self.chk_run_as_admin = ToggleSwitch(
            "Always run KeyDeck as administrator",
            startup_card,
        )
        self.chk_run_as_admin.setChecked(self._run_as_admin)
        startup_layout.addWidget(self.chk_run_as_admin)
        run_as_admin_desc = QLabel(
            "Shows a Windows UAC prompt when KeyDeck starts. Scheduled startup uses the same privilege level.",
            startup_card,
        )
        run_as_admin_desc.setObjectName("Muted")
        run_as_admin_desc.setWordWrap(True)
        startup_layout.addWidget(run_as_admin_desc)

        self.chk_high_priority = ToggleSwitch(
            "Use high process priority",
            startup_card,
        )
        self.chk_high_priority.setChecked(self._high_priority)
        startup_layout.addWidget(self.chk_high_priority)
        high_prio_desc = QLabel(
            "Requests the Windows HIGH_PRIORITY_CLASS when KeyDeck starts.",
            startup_card,
        )
        high_prio_desc.setObjectName("Muted")
        high_prio_desc.setWordWrap(True)
        startup_layout.addWidget(high_prio_desc)

        interaction_card = QFrame(content)
        interaction_card.setObjectName("Card")
        interaction_layout = QVBoxLayout(interaction_card)
        interaction_layout.setContentsMargins(18, 18, 18, 18)
        interaction_layout.setSpacing(10)
        interaction_title = QLabel("Interaction", interaction_card)
        interaction_title.setObjectName("SectionTitle")
        interaction_layout.addWidget(interaction_title)
        interaction_description = QLabel(
            "Configure the global keyboard shortcut used to show or hide the deck.",
            interaction_card,
        )
        interaction_description.setObjectName("PageSubtitle")
        interaction_description.setWordWrap(True)
        interaction_layout.addWidget(interaction_description)
        self.chk_right_alt_toggle = ToggleSwitch(
            "Use Right Alt to show or hide KeyDeck",
            interaction_card,
        )
        self.chk_right_alt_toggle.setChecked(self._right_alt_toggle)
        interaction_layout.addWidget(self.chk_right_alt_toggle)

        right_alt_desc = QLabel(
            "When enabled, Right Alt toggles the deck instead of being sent to other apps.",
            interaction_card,
        )
        right_alt_desc.setObjectName("Muted")
        right_alt_desc.setWordWrap(True)
        interaction_layout.addWidget(right_alt_desc)

        self.chk_right_alt_toggle.stateChanged.connect(
            lambda state: setattr(
                self,
                "_right_alt_toggle",
                state == Qt.Checked.value or state == 2,
            )
        )

        def on_auto_start_changed(state: int) -> None:
            is_checked = (state == Qt.Checked.value or state == 2)
            self._auto_start = is_checked
            self.chk_high_priority.setEnabled(is_checked)
            self.autostart_task_button.setEnabled(is_checked)
            if not is_checked:
                self.chk_high_priority.setChecked(False)

        def on_high_priority_changed(state: int) -> None:
            self._high_priority = (state == Qt.Checked.value or state == 2)

        self.chk_auto_start.stateChanged.connect(on_auto_start_changed)
        self.chk_high_priority.stateChanged.connect(on_high_priority_changed)
        self.chk_run_as_admin.stateChanged.connect(
            lambda state: setattr(
                self,
                "_run_as_admin",
                state == Qt.Checked.value or state == 2,
            )
        )
        on_auto_start_changed(Qt.Checked.value if self._auto_start else Qt.Unchecked.value)

        layout.addWidget(startup_card)
        layout.addWidget(interaction_card)
        layout.addStretch(1)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def _build_updates_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame(page)
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(14)

        self.installed_version_label = QLabel(
            f"Version {self._current_version}",
            card,
        )
        self.installed_version_label.setObjectName("VersionValue")
        card_layout.addWidget(self.installed_version_label)

        self.update_status_label = QLabel(
            "Automatic update checks run once every 24 hours.",
            card,
        )
        self.update_status_label.setObjectName("PageSubtitle")
        self.update_status_label.setWordWrap(True)
        card_layout.addWidget(self.update_status_label)

        actions = QHBoxLayout()
        self.check_updates_button = QPushButton("Check for updates", card)
        self.check_updates_button.setObjectName("QuietButton")
        self.check_updates_button.clicked.connect(self.update_check_requested.emit)
        actions.addWidget(self.check_updates_button)

        install_text = (
            "Download and install"
            if getattr(sys, "frozen", False)
            else "Open release page"
        )
        self.install_update_button = QPushButton(install_text, card)
        self.install_update_button.setObjectName("PrimaryButton")
        self.install_update_button.setVisible(False)
        self.install_update_button.setEnabled(False)
        self.install_update_button.clicked.connect(self.update_install_requested.emit)
        actions.addWidget(self.install_update_button)
        actions.addStretch(1)
        card_layout.addLayout(actions)

        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def set_update_status(
        self,
        status: str,
        available_version: str | None = None,
        install_enabled: bool = False,
    ) -> None:
        self.update_status_label.setText(status)
        self.install_update_button.setVisible(available_version is not None)
        self.install_update_button.setEnabled(install_enabled)
        if available_version is not None:
            action = (
                "Download and install"
                if getattr(sys, "frozen", False)
                else "Open release page"
            )
            self.install_update_button.setText(
                f"{action} {available_version}"
            )

    def to_settings(self) -> AppSettings:
        sizes = ["small", "medium", "large"]
        try:
            size_str = sizes[self.size_spin.value()]
        except IndexError:
            size_str = "medium"
        self._current_page.rows = self.rows_spin.value()
        self._current_page.columns = self.columns_spin.value()
        first_page = self._pages[0]
        settings = AppSettings(
            rows=first_page.rows,
            columns=first_page.columns,
            button_size=size_str,
            slot_actions=list(first_page.slot_actions),
            slot_settings=dict(first_page.slot_settings),
            slot_hotkeys=self._slot_hotkeys,
            right_alt_toggle=self._right_alt_toggle,
            pages=self._pages,
            active_page=self._selected_page_index,
            infinite_scroll=self._infinite_scroll,
            auto_start=self._auto_start,
            high_priority=self._high_priority,
            run_as_admin=self._run_as_admin,
            disabled_plugins=sorted(self._disabled_plugins),
        )
        return settings.clamp()

    def release_plugin_references(self) -> None:
        self._preview_generation += 1
        self._preview_rebuild_pending = False
        for button in self._button_widgets:
            button.set_action(None, {}, None)
        self._button_widgets.clear()
        self.actions.clear()
        self._action_by_id.clear()
        self.plugins.clear()
        self._plugins_by_id.clear()

    def _rebuild_preview(self) -> None:
        self._preview_rebuild_pending = False
        self._preview_generation += 1
        generation = self._preview_generation
        page = self._current_page
        page.rows = self.rows_spin.value()
        page.columns = self.columns_spin.value()
        page.clamp()
        while self.preview_grid.count():
            item = self.preview_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._button_widgets = []

        rows = page.rows
        cols = page.columns
        total = rows * cols
        if len(self._slot_actions) < total:
            self._slot_actions.extend([None] * (total - len(self._slot_actions)))

        sizes = ["small", "medium", "large"]
        try:
            size_str = sizes[self.size_spin.value()]
        except IndexError:
            size_str = "medium"
            
        button_size = BUTTON_SIZE_MAP.get(size_str, BUTTON_SIZE_MAP["medium"])
        self._build_preview_chunk(generation, page, button_size, total, 0)

    def _build_preview_chunk(
        self,
        generation: int,
        page: DeckPage,
        button_size: int,
        total: int,
        start_slot: int,
    ) -> None:
        if generation != self._preview_generation:
            return

        end_slot = min(start_slot + 8, total)
        cols = page.columns
        for slot in range(start_slot, end_slot):
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
            widget.set_action(
                self._action_for_slot(slot),
                self._slot_settings.get(str(slot), {}),
                self._slot_overrides.get(str(slot), {}),
            )
            row_idx = slot // cols
            col_idx = slot % cols
            self.preview_grid.addWidget(widget, row_idx, col_idx, alignment=Qt.AlignCenter)
            self._button_widgets.append(widget)

        if end_slot < total:
            QTimer.singleShot(
                0,
                lambda: self._build_preview_chunk(
                    generation,
                    page,
                    button_size,
                    total,
                    end_slot,
                ),
            )

    def _schedule_preview_rebuild(self) -> None:
        if self._preview_rebuild_pending:
            return
        self._preview_rebuild_pending = True
        QTimer.singleShot(0, self._rebuild_preview)

    def _swap_slots(self, source_slot: int, target_slot: int) -> None:
        if source_slot == target_slot:
            return
        if source_slot >= len(self._slot_actions) or target_slot >= len(self._slot_actions):
            return
        self._slot_actions[source_slot], self._slot_actions[target_slot] = (
            self._slot_actions[target_slot],
            self._slot_actions[source_slot],
        )
        for mapping in (self._slot_settings, self._slot_overrides):
            source_key = str(source_slot)
            target_key = str(target_slot)
            source_value = mapping.pop(source_key, None)
            target_value = mapping.pop(target_key, None)
            if source_value is not None:
                mapping[target_key] = source_value
            if target_value is not None:
                mapping[source_key] = target_value
        self._refresh_slot(source_slot)
        self._refresh_slot(target_slot)

    def _clear_slot(self, slot: int) -> None:
        if 0 <= slot < len(self._slot_actions):
            self._slot_actions[slot] = None
            self._slot_overrides.pop(str(slot), None)
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
            selected_action_id = dialog.selected_action_id()
            if selected_action_id != current_action_id:
                self._slot_overrides.pop(str(slot), None)
            self._slot_actions[slot] = selected_action_id
            self._refresh_slot(slot)

    def _open_button_appearance(self, slot: int) -> None:
        action = self._action_for_slot(slot)
        if action is None:
            return

        slot_key = str(slot)
        overrides = dict(self._slot_overrides.get(slot_key, {}))
        current_settings = self._slot_settings.get(slot_key, {})
        current_title = overrides.get(
            "title",
            str(current_settings.get("account_name", action.title)),
        )
        dialog = ButtonAppearanceDialog(
            current_title,
            overrides.get("icon_path", ""),
            self,
        )
        if not dialog.exec():
            return

        title = dialog.title_edit.text().strip()
        icon_path = dialog.icon_edit.text().strip()
        if title:
            overrides["title"] = title
        else:
            overrides.pop("title", None)
        if icon_path:
            overrides["icon_path"] = icon_path
        else:
            overrides.pop("icon_path", None)

        if overrides:
            self._slot_overrides[slot_key] = overrides
        else:
            self._slot_overrides.pop(slot_key, None)
        self._refresh_slot(slot)

    def _assign_hotkey(self, slot: int) -> None:
        from PySide6.QtWidgets import QInputDialog
        hotkey_key = str(slot) if self._selected_page_index == 0 else f"{self._current_page.page_id}:{slot}"
        current_hotkey = self._slot_hotkeys.get(hotkey_key, "")
        text, ok = QInputDialog.getText(
            self,
            "Assign Hotkey",
            f"Enter hotkey for button {slot + 1} on '{self._current_page.name}' (e.g. 'f16', 'ctrl+shift+a'):",
            text=current_hotkey
        )
        if ok:
            val = text.strip()
            if val:
                self._slot_hotkeys[hotkey_key] = val
            else:
                self._slot_hotkeys.pop(hotkey_key, None)

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
            self.release_plugin_references()
            result = self._reload_plugins_callback(set(self._disabled_plugins))
            plugin_result: tuple[list[PluginBase], list[str], list[PluginInfo] | None] | None = None
            if isinstance(result, tuple):
                if len(result) == 4:
                    actions, plugins, errors, available_plugins = result
                    plugin_result = (plugins, errors, available_plugins)
                elif len(result) == 3:
                    actions, plugins, errors = result
                    plugin_result = (plugins, errors, None)
                else:
                    raise ValueError("Invalid plugin reload result")
            else:
                actions = result
            self.actions = actions
            self._action_by_id = {action.action_id: action for action in self.actions}
            self._normalize_slot_actions()
            if plugin_result is not None:
                self._populate_plugin_list(*plugin_result)
            self._schedule_preview_rebuild()
            self.actions_changed.emit(self.actions)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Reload Plugins", str(exc))

    def _action_for_slot(self, slot: int) -> Action | None:
        action_id = self._slot_actions[slot] if slot < len(self._slot_actions) else None
        return self._action_by_id.get(action_id) if action_id else None

    def _refresh_slot(self, slot: int) -> None:
        if slot < 0 or slot >= len(self._button_widgets):
            return
        slot_key = str(slot)
        self._button_widgets[slot].set_action(
            self._action_for_slot(slot),
            self._slot_settings.get(slot_key, {}),
            self._slot_overrides.get(slot_key),
        )

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)

    def _normalize_slot_actions(self) -> None:
        valid_action_ids = set(self._action_by_id)
        preserved_prefixes = tuple(
            f"{plugin_id}."
            for plugin_id in self._disabled_plugins
        )
        aliases: dict[str, str] = {}
        for action in self.actions:
            for alias in action.aliases:
                aliases[str(alias)] = action.action_id

        for page in self._pages:
            normalized: list[str | None] = []
            for action_id in page.slot_actions:
                if (
                    not action_id
                    or action_id in valid_action_ids
                    or action_id.startswith(preserved_prefixes)
                ):
                    normalized.append(action_id)
                else:
                    normalized.append(aliases.get(action_id))
            page.slot_actions = normalized

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
