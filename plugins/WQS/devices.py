from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Device:
    name: str
    status: str
    battery: int | None
    icon: str = "device"


class DeviceManager:
    def __init__(self, configured: list[dict[str, Any]]) -> None:
        self.configured = configured

    def read(self) -> list[Device]:
        result = self._read_configured()
        configured_names = {device.name.lower() for device in result}
        for device in LogitechGHubAdapter().read():
            if device.name.lower() not in configured_names:
                result.append(device)
        return result

    def _read_configured(self) -> list[Device]:
        result: list[Device] = []
        for item in self.configured:
            if not isinstance(item, dict):
                continue
            command = str(item.get("battery_command", "")).strip()
            if not command:
                result.append(Device(str(item.get("name", "Устройство")), "unsupported", None, str(item.get("icon", "device"))))
                continue
            try:
                output = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=4, check=False)
                value = output.stdout.strip().splitlines()[0] if output.stdout.strip() else ""
                battery = int(value.rstrip("%")) if value else None
                status = "connected" if output.returncode == 0 and battery is not None else "battery unavailable"
                result.append(Device(str(item.get("name", "Устройство")), status, battery, str(item.get("icon", "device"))))
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                result.append(Device(str(item.get("name", "Устройство")), "battery unavailable", None, str(item.get("icon", "device"))))
        return result


class LogitechGHubAdapter:
    """Reads only battery values exposed by local G HUB data.

    G HUB has no stable public battery API. The adapter therefore scans
    configured/local JSON or text exports and never invents a percentage.
    """

    DEVICES = (
        ("PRO X 2 LIGHTSPEED", "headphones", "headphone-off.svg"),
        ("G502 X LIGHTSPEED", "mouse", "mouse-off.svg"),
    )

    def __init__(self) -> None:
        roots = [
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("PROGRAMDATA", ""),
        ]
        self.roots = [Path(root) / "LGHUB" for root in roots if root]

    def read(self) -> list[Device]:
        files = self._candidate_files()
        text = "\n".join(self._read_file(path) for path in files)
        result = []
        for name, icon, off_icon in self.DEVICES:
            detected = name.lower() in text.lower()
            battery = self._battery_near_device(text, name) if detected else None
            status = "connected" if battery is not None else (
                "battery unavailable" if detected else "disconnected"
            )
            result.append(Device(name, status, battery, icon if battery is not None else off_icon))
        return result

    def _candidate_files(self) -> list[Path]:
        files: list[Path] = []
        for root in self.roots:
            if not root.is_dir():
                continue
            try:
                for path in root.rglob("*"):
                    if path.is_file() and path.suffix.lower() in {".json", ".db", ".txt", ".log"}:
                        files.append(path)
                    if len(files) >= 80:
                        return files
            except OSError:
                continue
        return files

    def _read_file(self, path: Path) -> str:
        try:
            if path.suffix.lower() == ".db":
                with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                    tables = connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                    chunks: list[str] = []
                    for (table,) in tables[:10]:
                        safe_table = str(table).replace('"', '""')
                        rows = connection.execute(f'SELECT * FROM "{safe_table}" LIMIT 100').fetchall()
                        chunks.extend(" ".join(str(value) for value in row) for row in rows)
                    return "\n".join(chunks)
            return path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, sqlite3.Error):
            return ""

    def _battery_near_device(self, text: str, device_name: str) -> int | None:
        match = re.search(
            rf"{re.escape(device_name)}.{{0,1500}}?(\d{{1,3}})\s*%",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        value = int(match.group(1))
        return value if 0 <= value <= 100 else None
