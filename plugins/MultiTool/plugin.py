from __future__ import annotations

import base64
import os
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext
from keydeck.ui.controls import add_dialog_header, style_dialog_buttons
from keydeck.ui.theme import size_dialog

RUN_COMMAND_SCRIPT = (
    "$shell = New-Object -ComObject WScript.Shell; "
    "$shell.Run($env:KEYDECK_RUN_COMMAND, 1, $false)"
)
STEP_TYPES = {
    "program": "Open program",
    "url": "Open web link",
    "command": "Run a Win+R command",
    "plugin": "Press another plugin button",
}


class SequenceEditorDialog(QDialog):
    def __init__(
        self,
        steps: list[dict],
        plugin_slots: list[dict],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MultiTool sequence")
        self.setModal(True)
        size_dialog(self, 820, 740, 650, 540)
        self.plugin_slots = plugin_slots
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
        self.step_list.setSpacing(4)
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
        self._update_control_state(self.step_list.currentRow())

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

    def _step_label(self, step: dict) -> str:
        label = STEP_TYPES.get(step.get("type"), "Unknown step")
        if step.get("type") == "plugin":
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
            ("plugin", "Another plugin button"),
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
            replacement = self.step_list.takeItem(self.step_list.count() - 1)
            self.step_list.takeItem(row)
            self.step_list.insertItem(row, replacement)
            self.step_list.setCurrentRow(row)

    def _remove_selected(self) -> None:
        row = self.step_list.currentRow()
        if row >= 0:
            self.step_list.takeItem(row)
            self._update_control_state(self.step_list.currentRow())

    def _move_selected(self, direction: int) -> None:
        row = self.step_list.currentRow()
        target = row + direction
        if not 0 <= row < self.step_list.count() or not 0 <= target < self.step_list.count():
            return
        item = self.step_list.takeItem(row)
        self.step_list.insertItem(target, item)
        self.step_list.setCurrentRow(target)

    def _update_control_state(self, row: int) -> None:
        valid = 0 <= row < self.step_list.count()
        self.edit_button.setEnabled(valid)
        self.remove_button.setEnabled(valid)
        self.up_button.setEnabled(valid and row > 0)
        self.down_button.setEnabled(valid and row < self.step_list.count() - 1)


class Plugin(PluginBase):
    plugin_id = "MultiTool"
    plugin_name = "MultiTool"

    def actions(self) -> list[Action]:
        return [
            Action(
                action_id=f"{self.plugin_id}.run",
                title="MultiTool",
                callback=self._run_sequence,
                plugin_id=self.plugin_id,
                icon_path=str(Path(__file__).with_name("multitool.svg")),
                action_settings_callback=self._edit_sequence,
            )
        ]

    def _edit_sequence(self, _slot: int, settings: dict) -> dict | None:
        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        raw_steps = settings.get("steps", [])
        steps = [dict(step) for step in raw_steps if isinstance(step, dict)] if isinstance(raw_steps, list) else []
        plugin_slots = (
            self.context.assigned_plugin_slots()
            if self.context is not None
            else []
        )
        dialog = SequenceEditorDialog(steps, plugin_slots, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {"steps": dialog.result_steps()}

    def _run_sequence(self, settings: dict | None = None) -> None:
        if not isinstance(settings, dict):
            return
        for index, step in enumerate(settings.get("steps", [])):
            if not isinstance(step, dict) or step.get("enabled") is False:
                continue
            step_type = step.get("type")
            try:
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
                else:
                    raise ValueError(f"Unknown MultiTool step type: {step_type}")
            except Exception as exc:
                raise RuntimeError(f"MultiTool step {index + 1} failed: {exc}") from exc

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
