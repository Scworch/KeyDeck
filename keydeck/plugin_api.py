from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Action:
    action_id: str
    title: str
    callback: Callable[[], None]
    plugin_id: str = "core"
    settings_callback: Callable[[], None] | None = None
    icon_path: str | None = None
    icon_mode: str = "default"
    icon_zoom: float = 1.0
    icon_offset_x: int = 0
    icon_offset_y: int = 0


@dataclass
class PluginContext:
    plugin_id: str
    plugin_name: str
    plugin_dir: Path
    entry_file: Path
    settings_file: Path
    manifest: dict

    def load_settings(self, default: dict | None = None) -> dict:
        if not self.settings_file.exists():
            data = default or {}
            self.save_settings(data)
            return dict(data)
        try:
            raw = json.loads(self.settings_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return dict(default or {})

    def save_settings(self, data: dict) -> None:
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(
            json.dumps(data, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )


class PluginBase:
    plugin_id = "base"
    plugin_name = "Base Plugin"
    context: PluginContext | None = None

    def __init__(self, context: PluginContext | None = None) -> None:
        self.context = context

    def actions(self) -> list[Action]:
        return []

    def open_settings(self) -> None:
        if self.context is None:
            return
        os.startfile(str(self.context.settings_file))
