from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtGui import QGuiApplication


@dataclass
class WindowRecord:
    title: str
    process_name: str
    monitor: int
    x: int
    y: int
    width: int
    height: int
    state: str


class WindowManager:
    def launch(self, app: dict[str, Any]) -> tuple[bool, str]:
        executable = str(app.get("executable", "")).strip()
        if not executable:
            return False, f"{app.get('name', 'Приложение')}: не указан executable"
        args = str(app.get("arguments", "")).strip()
        try:
            subprocess.Popen([executable, *args.split()], cwd=str(app.get("working_dir", "")).strip() or None)
            return True, f"Запуск: {app.get('name', executable)}"
        except (OSError, ValueError) as exc:
            return False, f"{app.get('name', executable)}: {exc}"

    def monitor_rects(self) -> list[tuple[int, int, int, int]]:
        return [(s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height())
                for s in QGuiApplication.screens()]

    def place_record(self, record: dict[str, Any]) -> bool:
        if os.name != "nt":
            return False
        title = str(record.get("window_title", "")).strip()
        if not title:
            return False
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if not hwnd:
            return False
        monitors = self.monitor_rects()
        index = int(record.get("monitor", 0))
        if index >= len(monitors):
            index = 0
        mx, my, mw, mh = monitors[index]
        geometry = record.get("window", {})
        x = mx + round(float(geometry.get("x", 0)) * mw)
        y = my + round(float(geometry.get("y", 0)) * mh)
        width = max(100, round(float(geometry.get("width", 1)) * mw))
        height = max(100, round(float(geometry.get("height", 1)) * mh))
        return bool(ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, width, height, 0x0040))

    def save_current_layout(self, app_names: list[str]) -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        records: list[dict[str, Any]] = []
        for name in app_names:
            hwnd = ctypes.windll.user32.FindWindowW(None, name)
            if not hwnd:
                continue
            rect = ctypes.wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                continue
            records.append({"window_title": name, "monitor": 0, "window": {
                "x": rect.left, "y": rect.top, "width": rect.right - rect.left, "height": rect.bottom - rect.top, "state": "normal"
            }})
        return records

    def wait_and_place(self, apps: list[dict[str, Any]]) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and apps:
            remaining = [app for app in apps if not self.place_record(app)]
            apps[:] = remaining
            if remaining:
                time.sleep(0.5)
