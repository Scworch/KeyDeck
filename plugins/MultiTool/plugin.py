from __future__ import annotations

import base64
import os
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext
from keydeck.ui.controls import ToggleSwitch, add_dialog_header, style_dialog_buttons
from keydeck.ui.theme import size_dialog

RUN_COMMAND_SCRIPT = (
    "$shell = New-Object -ComObject WScript.Shell; "
    "$shell.Run($env:KEYDECK_RUN_COMMAND, 1, $false)"
)
STEP_TYPES = {
    "program": "Open program",
    "url": "Open web link",
    "command": "Run a Win+R command",
    "plugin": "Legacy assigned plugin button",
    "plugin_action": "Run plugin action",
    "delay": "Wait",
}


class SequenceStepCard(QFrame):
    selected = Signal()

    def __init__(
        self,
        number: int,
        step: dict,
        item: QListWidgetItem,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SequenceStepCard")
        self.setProperty("selected", False)
        self.setMinimumHeight(72)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        number_label = QLabel(f"{number:02}", self)
        number_label.setObjectName("SequenceStepNumber")
        number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number_label.setFixedSize(34, 34)
        number_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(number_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        type_label = QLabel(STEP_TYPES.get(step.get("type"), "Unknown step"), self)
        type_label.setObjectName("SequenceStepType")
        type_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        detail = (
            step.get("label", "Plugin button")
            if step.get("type") in {"plugin", "plugin_action"}
            else step.get("value", "")
        )
        detail_label = QLabel(str(detail), self)
        detail_label.setObjectName("SequenceStepDetail")
        detail_label.setWordWrap(True)
        detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        detail_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text_layout.addWidget(type_label)
        text_layout.addWidget(detail_label)
        layout.addLayout(text_layout, 1)

        self.enabled_toggle = ToggleSwitch("Enabled", self)
        self.enabled_toggle.setFixedWidth(104)
        self.enabled_toggle.setChecked(item.checkState() != Qt.CheckState.Unchecked)
        self.enabled_toggle.toggled.connect(
            lambda checked: item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
        )
        layout.addWidget(self.enabled_toggle)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit()
        super().mousePressEvent(event)


class SequenceEditorDialog(QDialog):
    def __init__(
        self,
        steps: list[dict],
        plugin_actions: list[Action],
        plugin_slots: list[dict] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MultiTool sequence")
        self.setModal(True)
        size_dialog(self, 820, 740, 650, 540)
        self.plugin_actions = plugin_actions
        self.plugin_slots = plugin_slots or []
        self.setMinimumWidth(650)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        add_dialog_header(
            layout,
            "Button sequence",
            "Steps run from top to bottom. Disable individual steps or change their order.",
            self,
        )
        self.step_list = QListWidget(self)
        self.step_list.setObjectName("PluginList")
        self.step_list.setSpacing(6)
        layout.addWidget(self.step_list, 1)

        controls = QHBoxLayout()
        self.add_button = QPushButton("Add step", self)
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.clicked.connect(self._show_add_menu)
        controls.addWidget(self.add_button)
        self.edit_button = QPushButton("Edit", self)
        self.edit_button.setObjectName("QuietButton")
        self.edit_button.clicked.connect(self._edit_selected)
        controls.addWidget(self.edit_button)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.setObjectName("QuietButton")
        self.remove_button.clicked.connect(self._remove_selected)
        controls.addWidget(self.remove_button)
        controls.addStretch(1)
        self.up_button = QPushButton("Move up", self)
        self.up_button.setObjectName("QuietButton")
        self.up_button.clicked.connect(lambda: self._move_selected(-1))
        controls.addWidget(self.up_button)
        self.down_button = QPushButton("Move down", self)
        self.down_button.setObjectName("QuietButton")
        self.down_button.clicked.connect(lambda: self._move_selected(1))
        controls.addWidget(self.down_button)
        layout.addLayout(controls)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        style_dialog_buttons(buttons, QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for step in steps:
            self._append_step(step)
        self.step_list.currentRowChanged.connect(self._update_control_state)
        self.step_list.currentItemChanged.connect(self._update_card_selection)
        self._update_control_state(self.step_list.currentRow())
        self._update_card_selection(self.step_list.currentItem(), None)

    def result_steps(self) -> list[dict]:
        steps: list[dict] = []
        for index in range(self.step_list.count()):
            item = self.step_list.item(index)
            step = dict(item.data(Qt.ItemDataRole.UserRole))
            step["enabled"] = item.checkState() == Qt.CheckState.Checked
            steps.append(step)
        return steps

    def _append_step(self, step: dict) -> None:
        item = QListWidgetItem(self._step_label(step))
        item.setData(Qt.ItemDataRole.UserRole, dict(step))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Unchecked
            if step.get("enabled") is False
            else Qt.CheckState.Checked
        )
        self.step_list.addItem(item)
        item.setSizeHint(QSize(0, 88))
        card = SequenceStepCard(self.step_list.count(), step, item, self.step_list)
        card.selected.connect(lambda item=item: self.step_list.setCurrentItem(item))
        self.step_list.setItemWidget(item, card)
        self._renumber_cards()

    def _renumber_cards(self) -> None:
        for index in range(self.step_list.count()):
            item = self.step_list.item(index)
            card = self.step_list.itemWidget(item)
            if card is None:
                continue
            number_label = card.findChild(QLabel, "SequenceStepNumber")
            if number_label is not None:
                number_label.setText(f"{index + 1:02}")

    def _update_card_selection(self, current, previous) -> None:
        _ = previous
        for index in range(self.step_list.count()):
            item = self.step_list.item(index)
            card = self.step_list.itemWidget(item)
            if isinstance(card, SequenceStepCard):
                card.set_selected(item is current)

    def _step_label(self, step: dict) -> str:
        label = STEP_TYPES.get(step.get("type"), "Unknown step")
        if step.get("type") in {"plugin", "plugin_action"}:
            detail = step.get("label", "Plugin button")
        else:
            detail = step.get("value", "")
        return f"{label}  ·  {detail}"

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        step_types = (
            ("program", "Program (.exe)"),
            ("url", "Web link"),
            ("command", "Win+R command / deep link"),
            ("plugin_action", "Any installed plugin action"),
            ("delay", "Delay between actions"),
        )
        for step_type, title in step_types:
            action = QAction(title, menu)
            action.triggered.connect(
                lambda _checked=False, kind=step_type: self._add_step(kind)
            )
            menu.addAction(action)
        menu.exec(self.add_button.mapToGlobal(self.add_button.rect().bottomLeft()))

    def _add_step(self, step_type: str, initial: dict | None = None) -> None:
        initial = initial or {}
        value = str(initial.get("value", ""))
        if step_type == "program":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Choose program",
                value,
                "Applications (*.exe);;All files (*)",
            )
            if not path:
                return
            if Path(path).suffix.casefold() != ".exe":
                QMessageBox.warning(self, "MultiTool", "Choose an .exe file.")
                return
            step = {"type": "program", "value": str(Path(path).resolve())}
        elif step_type in ("url", "command"):
            title = "Web link" if step_type == "url" else "Win+R command"
            prompt = (
                "Enter an http or https URL."
                if step_type == "url"
                else "Enter a command or deep link as you would in Windows Run."
            )
            text, accepted = QInputDialog.getText(
                self,
                title,
                prompt,
                text=value,
            )
            if not accepted or not text.strip():
                return
            text = text.strip()
            if step_type == "url" and urlparse(text).scheme.casefold() not in {
                "http",
                "https",
            }:
                QMessageBox.warning(self, "MultiTool", "Web links must use http or https.")
                return
            step = {"type": step_type, "value": text}
        elif step_type == "delay":
            try:
                default_milliseconds = int(initial.get("milliseconds", 1000))
            except (TypeError, ValueError, OverflowError):
                default_milliseconds = 1000
            milliseconds, accepted = QInputDialog.getInt(
                self,
                "Delay between actions",
                "Wait time (milliseconds):",
                max(0, min(default_milliseconds, 600000)),
                0,
                600000,
                100,
            )
            if not accepted:
                return
            step = {"type": "delay", "milliseconds": milliseconds}
        elif step_type == "plugin_action":
            actions = [
                action
                for action in self.plugin_actions
                if action.plugin_id not in {"core", "MultiTool"}
            ]
            if not actions:
                QMessageBox.information(
                    self,
                    "MultiTool",
                    "No other installed plugin actions are available.",
                )
                return
            labels = [f"{action.plugin_id} · {action.title}" for action in actions]
            selected_id = str(initial.get("action_id", ""))
            initial_index = next(
                (
                    index
                    for index, action in enumerate(actions)
                    if action.action_id == selected_id
                ),
                0,
            )
            selected, accepted = QInputDialog.getItem(
                self,
                "Plugin action",
                "Choose an installed plugin action:",
                labels,
                initial_index,
                False,
            )
            if not accepted:
                return
            action = actions[labels.index(selected)]
            current_settings = initial.get("settings", {})
            action_settings = (
                dict(current_settings)
                if isinstance(current_settings, dict)
                else {}
            )
            if action.action_settings_callback is not None:
                configured = action.action_settings_callback(0, action_settings)
                if configured is None:
                    return
                action_settings = configured
            step = {
                "type": "plugin_action",
                "action_id": action.action_id,
                "settings": action_settings,
                "label": labels[labels.index(selected)],
            }
        elif step_type == "plugin":
            slots = [
                slot
                for slot in self.plugin_slots
                if slot.get("plugin_id") != "MultiTool"
            ]
            if not slots:
                QMessageBox.information(
                    self,
                    "MultiTool",
                    "Assign another plugin action to a deck button first.",
                )
                return
            labels = [
                f"{slot['page_name']} · Button {slot['slot'] + 1} · {slot['title']}"
                for slot in slots
            ]
            preferred_id = initial.get("page_id")
            preferred_slot = initial.get("slot")
            initial_index = next(
                (
                    index
                    for index, slot in enumerate(slots)
                    if slot.get("page_id") == preferred_id
                    and slot.get("slot") == preferred_slot
                ),
                0,
            )
            selected, accepted = QInputDialog.getItem(
                self,
                "Plugin button",
                "Choose an assigned plugin button:",
                labels,
                initial_index,
                False,
            )
            if not accepted:
                return
            slot = slots[labels.index(selected)]
            step = {
                "type": "plugin",
                "page_id": slot["page_id"],
                "slot": slot["slot"],
                "label": labels[labels.index(selected)],
            }
        else:
            return
        step["enabled"] = initial.get("enabled", True)
        self._append_step(step)
        self.step_list.setCurrentRow(self.step_list.count() - 1)

    def _edit_selected(self) -> None:
        row = self.step_list.currentRow()
        if not 0 <= row < self.step_list.count():
            return
        item = self.step_list.item(row)
        step = dict(item.data(Qt.ItemDataRole.UserRole))
        original_count = self.step_list.count()
        self._add_step(step.get("type", ""), step)
        if self.step_list.count() > original_count:
            steps = self.result_steps()
            steps.insert(row, steps.pop())
            self._replace_steps(steps, row)

    def _remove_selected(self) -> None:
        row = self.step_list.currentRow()
        if row < 0:
            return
        steps = self.result_steps()
        steps.pop(row)
        self._replace_steps(steps, min(row, len(steps) - 1))

    def _move_selected(self, direction: int) -> None:
        row = self.step_list.currentRow()
        target = row + direction
        if not 0 <= row < self.step_list.count() or not 0 <= target < self.step_list.count():
            return
        steps = self.result_steps()
        steps.insert(target, steps.pop(row))
        self._replace_steps(steps, target)

    def _replace_steps(self, steps: list[dict], selected_row: int) -> None:
        self.step_list.clear()
        for step in steps:
            self._append_step(step)
        self.step_list.setCurrentRow(selected_row)
        self._update_control_state(selected_row)

    def _update_control_state(self, row: int) -> None:
        valid = 0 <= row < self.step_list.count()
        self.edit_button.setEnabled(valid)
        self.remove_button.setEnabled(valid)
        self.up_button.setEnabled(valid and row > 0)
        self.down_button.setEnabled(valid and row < self.step_list.count() - 1)


class Plugin(PluginBase):
    plugin_id = "MultiTool"
    plugin_name = "MultiTool"

    def __init__(self, context=None) -> None:
        super().__init__(context)
        self._sequence_steps: list[dict] = []
        self._sequence_index = 0
        self._sequence_running = False
        self._sequence_timer = QTimer()
        self._sequence_timer.setSingleShot(True)
        self._sequence_timer.timeout.connect(self._continue_sequence)

    def stop(self) -> None:
        self._sequence_timer.stop()
        self._sequence_steps = []
        self._sequence_running = False

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id=f"{self.plugin_id}.run",
                title="MultiTool",
                callback=self._run_sequence,
                plugin_id=self.plugin_id,
                icon_path=str(Path(__file__).with_name("multitool.svg")),
                plugin_settings_enabled=False,
                action_settings_callback=self._edit_sequence,
            )
        ]

    def _edit_sequence(self, _slot: int, settings: dict) -> dict | None:
        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        raw_steps = settings.get("steps", [])
        steps = [dict(step) for step in raw_steps if isinstance(step, dict)] if isinstance(raw_steps, list) else []
        plugin_actions = (
            self.context.available_plugin_actions()
            if self.context is not None
            else []
        )
        plugin_slots = (
            self.context.assigned_plugin_slots()
            if self.context is not None
            else []
        )
        dialog = SequenceEditorDialog(
            steps,
            plugin_actions,
            plugin_slots,
            parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {"steps": dialog.result_steps()}

    def _run_sequence(self, settings: dict | None = None) -> None:
        if not isinstance(settings, dict):
            return
        if self._sequence_running:
            QMessageBox.information(
                QApplication.activeWindow(),
                "MultiTool",
                "A MultiTool sequence is already running.",
            )
            return
        raw_steps = settings.get("steps", [])
        self._sequence_steps = (
            [dict(step) for step in raw_steps if isinstance(step, dict)]
            if isinstance(raw_steps, list)
            else []
        )
        self._sequence_index = 0
        self._sequence_running = bool(self._sequence_steps)
        self._continue_sequence()

    def _continue_sequence(self) -> None:
        while self._sequence_index < len(self._sequence_steps):
            step_index = self._sequence_index
            step = self._sequence_steps[step_index]
            self._sequence_index += 1
            if step.get("enabled") is False:
                continue
            if step.get("type") == "delay":
                try:
                    milliseconds = int(step.get("milliseconds", 0))
                except (TypeError, ValueError, OverflowError):
                    self._fail_step(step_index, ValueError("Invalid delay value"))
                    return
                self._sequence_timer.start(max(0, min(milliseconds, 600000)))
                return
            try:
                self._execute_step(step)
            except Exception as exc:
                self._fail_step(step_index, exc)
                return
        self._sequence_steps = []
        self._sequence_running = False

    def _execute_step(self, step: dict) -> None:
        step_type = step.get("type")
        if step_type == "program":
            path = Path(str(step.get("value", ""))).expanduser()
            if path.suffix.casefold() != ".exe" or not path.is_file():
                raise FileNotFoundError(f"Program not found: {path}")
            subprocess.Popen([str(path)], cwd=str(path.parent))
        elif step_type == "url":
            url = str(step.get("value", ""))
            if urlparse(url).scheme.casefold() not in {"http", "https"}:
                raise ValueError(f"Invalid web link: {url}")
            if not webbrowser.open(url):
                raise RuntimeError(f"No browser accepted the link: {url}")
        elif step_type == "command":
            self._run_windows_command(str(step.get("value", "")))
        elif step_type == "plugin":
            if self.context is None:
                raise RuntimeError("Plugin context is not available")
            self.context.invoke_plugin_slot(
                str(step.get("page_id", "")),
                int(step.get("slot", -1)),
            )
        elif step_type == "plugin_action":
            if self.context is None:
                raise RuntimeError("Plugin context is not available")
            action_id = str(step.get("action_id", ""))
            if not action_id:
                raise ValueError("Choose a plugin action for this step")
            settings = step.get("settings", {})
            self.context.invoke_action(
                action_id,
                settings if isinstance(settings, dict) else {},
            )
        else:
            raise ValueError(f"Unknown MultiTool step type: {step_type}")

    def _fail_step(self, step_index: int, error: Exception) -> None:
        self._sequence_steps = []
        self._sequence_running = False
        QMessageBox.critical(
            QApplication.activeWindow(),
            "MultiTool",
            f"Step {step_index + 1} failed: {error}",
        )

    def _run_windows_command(self, command: str) -> None:
        if not command.strip():
            raise ValueError("The Win+R command is empty")
        environment = os.environ.copy()
        environment["KEYDECK_RUN_COMMAND"] = command
        encoded = base64.b64encode(RUN_COMMAND_SCRIPT.encode("utf-16le")).decode("ascii")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-EncodedCommand",
                encoded,
            ],
            env=environment,
            creationflags=creation_flags,
        )
