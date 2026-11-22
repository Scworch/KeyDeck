from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from keydeck.plugin_api import Action, PluginBase, PluginContext
from keydeck.ui.controls import add_dialog_header, style_dialog_buttons
from keydeck.ui.theme import size_dialog

POWERSHELL_SCRIPT = (
    "$shell = New-Object -ComObject WScript.Shell; "
    "$link = $shell.CreateShortcut($env:KEYDECK_SHORTCUT_PATH); "
    "[pscustomobject]@{ target=$link.TargetPath; arguments=$link.Arguments; "
    "working_directory=$link.WorkingDirectory } | ConvertTo-Json -Compress"
)
RUN_COMMAND_SCRIPT = (
    "$shell = New-Object -ComObject WScript.Shell; "
    "$shell.Run($env:KEYDECK_RUN_COMMAND, 1, $false)"
)


@dataclass(frozen=True)
class ShortcutTarget:
    target: Path
    arguments: str
    working_directory: Path | None


def resolve_shortcut(shortcut_path: Path) -> ShortcutTarget:
    if os.name != "nt":
        raise OSError("Windows shortcut files can only be resolved on Windows")
    environment = os.environ.copy()
    environment["KEYDECK_SHORTCUT_PATH"] = str(shortcut_path.resolve())
    encoded_command = POWERSHELL_SCRIPT.encode("utf-16le")
    import base64

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(encoded_command).decode("ascii"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "Windows could not resolve the selected shortcut"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("The selected shortcut returned invalid target information") from exc
    if not isinstance(data, dict):
        raise ValueError("The selected shortcut did not point to an executable")
    target_text = data.get("target")
    arguments = data.get("arguments", "")
    working_directory_text = data.get("working_directory", "")
    if not isinstance(target_text, str) or not target_text.strip():
        raise ValueError("The selected shortcut has no target")
    target = Path(target_text).expanduser().resolve()
    if target.suffix.casefold() != ".exe" or not target.is_file():
        raise ValueError("The selected shortcut must point to an existing .exe file")
    working_directory = (
        Path(working_directory_text).expanduser()
        if isinstance(working_directory_text, str) and working_directory_text.strip()
        else target.parent
    )
    return ShortcutTarget(
        target=target,
        arguments=arguments if isinstance(arguments, str) else "",
        working_directory=working_directory,
    )


class TargetPickerDialog(QDialog):
    def __init__(self, path: str = "", mode: str = "file", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose application")
        self.setModal(True)
        size_dialog(self, 700, 300, 560, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        add_dialog_header(
            layout,
            "Choose an application",
            "Choose an .exe, a Windows shortcut, or a Windows Run command such as a deep link.",
            self,
        )
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Program or shortcut", "file")
        self.mode_combo.addItem("Command or deep link", "command")
        self.mode_combo.setCurrentIndex(
            max(0, self.mode_combo.findData(mode))
        )
        self.mode_combo.currentIndexChanged.connect(self._update_mode)
        layout.addWidget(self.mode_combo)
        row = QHBoxLayout()
        self.path_edit = QLineEdit(path, self)
        self.path_edit.setPlaceholderText("Path to .exe or .lnk")
        row.addWidget(self.path_edit, 1)
        self.browse_button = QPushButton("Browse…", self)
        self.browse_button.setObjectName("QuietButton")
        self.browse_button.clicked.connect(self._browse)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        style_dialog_buttons(buttons, QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_mode()

    def _update_mode(self) -> None:
        command_mode = self.mode_combo.currentData() == "command"
        self.path_edit.setPlaceholderText(
            "Command or deep link, e.g. steam://run/123"
            if command_mode
            else "Path to .exe or .lnk"
        )
        self.browse_button.setVisible(not command_mode)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose application or shortcut",
            self.path_edit.text(),
            "Applications and shortcuts (*.exe *.lnk);;All files (*)",
        )
        if path:
            self.path_edit.setText(path)


class Plugin(PluginBase):
    plugin_id = "ShortcutLauncher"
    plugin_name = "Shortcut Launcher"

    def actions(self) -> list[Action]:
        icon_path = Path(__file__).with_name("shortcut.svg")
        return [
            Action(
                action_id=f"{self.plugin_id}.launch",
                title="Launch App",
                callback=self._launch,
                plugin_id=self.plugin_id,
                icon_path=str(icon_path),
                plugin_settings_enabled=False,
                action_settings_callback=self._edit_action_settings,
                action_icon_callback=self._get_icon,
            )
        ]

    def _get_icon(self, _slot: int, settings: dict) -> str | None:
        if settings.get("launch_mode") == "command":
            return str(Path(__file__).with_name("shortcut.svg"))
        path = settings.get("target_path")
        if isinstance(path, str) and Path(path).is_file():
            return path
        return str(Path(__file__).with_name("shortcut.svg"))

    def _edit_action_settings(self, _slot: int, settings: dict) -> dict | None:
        parent = QApplication.activeModalWidget() or QApplication.activeWindow()
        mode = str(settings.get("launch_mode", "file"))
        current_value = (
            settings.get("command", "")
            if mode == "command"
            else settings.get("source_path", "")
        )
        dialog = TargetPickerDialog(str(current_value), mode, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if dialog.mode_combo.currentData() == "command":
            command = dialog.path_edit.text().strip()
            if not command:
                QMessageBox.warning(dialog, "Shortcut Launcher", "Enter a command or deep link.")
                return None
            return {"launch_mode": "command", "command": command}
        selected_path = Path(dialog.path_edit.text().strip()).expanduser()
        if not selected_path.is_file():
            QMessageBox.warning(dialog, "Shortcut Launcher", "Select an existing .exe or .lnk file.")
            return None
        if selected_path.suffix.casefold() == ".lnk":
            try:
                target = resolve_shortcut(selected_path)
                if self.context is None:
                    raise RuntimeError("Plugin data storage is not available")
                copied_path = self._copy_shortcut_target(target.target)
                return {
                    "source_path": str(selected_path.resolve()),
                    "target_path": str(copied_path),
                    "arguments": target.arguments,
                    "working_directory": str(target.working_directory or target.target.parent),
                    "copied_from_shortcut": True,
                }
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                QMessageBox.critical(dialog, "Shortcut Launcher", str(exc))
                return None
        if selected_path.suffix.casefold() != ".exe":
            QMessageBox.warning(dialog, "Shortcut Launcher", "Select an .exe or .lnk file.")
            return None
        return {
            "source_path": str(selected_path.resolve()),
            "target_path": str(selected_path.resolve()),
            "arguments": "",
            "working_directory": str(selected_path.resolve().parent),
            "copied_from_shortcut": False,
        }

    def _copy_shortcut_target(self, target: Path) -> Path:
        if self.context is None:
            raise RuntimeError("Plugin data storage is not available")
        directory = self.context.writable_dir / "launch_targets"
        directory.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(str(target.resolve()).casefold().encode("utf-8")).hexdigest()[:12]
        copied_path = directory / f"{identity}-{target.name}"
        temporary_path = copied_path.with_name(f".{copied_path.name}.new")
        try:
            shutil.copy2(target, temporary_path)
            os.replace(temporary_path, copied_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return copied_path

    def _launch(self, settings: dict | None = None) -> None:
        settings = settings or {}
        launch_mode = settings.get("launch_mode", "file")
        if launch_mode == "command":
            command = str(settings.get("command", "")).strip()
            if not command:
                raise ValueError("Configure this button with a command or deep link.")
            self._run_windows_command(command)
            return
        if launch_mode != "file":
            raise ValueError(f"Unknown launch mode: {launch_mode}")
        target_path = Path(str(settings.get("target_path", ""))).expanduser()
        if target_path.suffix.casefold() != ".exe" or not target_path.is_file():
            raise FileNotFoundError("Configure this button with an existing .exe or Windows shortcut.")
        raw_arguments = settings.get("arguments", "")
        arguments = shlex.split(raw_arguments, posix=False) if isinstance(raw_arguments, str) else []
        working_directory_text = settings.get("working_directory")
        working_directory = (
            Path(working_directory_text)
            if isinstance(working_directory_text, str) and Path(working_directory_text).is_dir()
            else target_path.parent
        )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [str(target_path), *arguments],
            cwd=str(working_directory),
            creationflags=creation_flags,
        )

    def _run_windows_command(self, command: str) -> None:
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
