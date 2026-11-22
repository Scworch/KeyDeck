from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def defaults() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "general": {
            "autorun": False,
            "hide_taskbar": True,
            "emergency_hotkey": "ctrl+alt+escape",
            "close_after_launch": True,
            "missing_monitor": "primary",
            "primary_monitor": 0,
        },
        "network": {
            "default_mode": "off",
            "zapret": {"bat": "", "arguments": "", "elevated": True},
            "nekobox": {
                "executable": "",
                "server": "",
                "tun_command": "",
                "status_command": ""
            },
            "servers": []
        },
        "widgets": [
            {"id": "clock", "title": "Время", "source": "clock", "width": 150, "enabled": True},
            {"id": "memory", "title": "Память", "source": "memory", "width": 150, "enabled": True}
        ],
        "devices": [],
        "presets": _demo_presets(),
        "run_log": []
    }


def _demo_presets() -> list[dict[str, Any]]:
    def app(name: str, command: str, monitor: int, foreground: bool = False) -> dict[str, Any]:
        return {
            "id": name.lower().replace(" ", "_"),
            "name": name,
            "executable": command,
            "arguments": "",
            "working_dir": "",
            "monitor": monitor,
            "window": {"x": 0, "y": 0, "width": 1, "height": 1, "state": "normal"},
            "foreground": foreground,
            "wait_seconds": 20
        }

    def preset(pid: str, name: str, icon: str, color: str, apps: list[dict[str, Any]], mode: str = "off") -> dict[str, Any]:
        return {
            "id": pid, "name": name, "description": "", "icon": icon, "color": color,
            "accent": "#8bd5ff", "apps": apps, "actions": [], "network": {"mode": mode, "server": ""},
            "card_width": 280, "enabled": True
        }

    return [
        preset("normal", "NORMAL", "icons/Logo_Windows_11.webp", "#a9d8ed", [
            app("Vivaldi", "vivaldi.exe", 0), app("Discord", "discord.exe", 1), app("Spotify", "spotify.exe", 2)
        ]),
        preset("steam", "STEAM", "icons/Steam_icon_logo.svg", "#17375e", [
            app("Steam", "steam.exe", 0, True), app("Vivaldi", "vivaldi.exe", 0), app("Discord", "discord.exe", 1), app("Spotify", "spotify.exe", 2)
        ]),
        preset("epic", "EPIC GAMES", "icons/Epic_Games_logo.svg", "#747982", [
            app("Epic Games Launcher", "EpicGamesLauncher.exe", 0, True), app("Vivaldi", "vivaldi.exe", 0), app("Discord", "discord.exe", 1), app("Spotify", "spotify.exe", 2)
        ]),
        preset("vscode", "VS CODE", "icons/Visual_Studio_Code_1.35_icon.svg", "#91c9e8", [
            app("VS Code Agents", "code.exe", 0, True), app("Vivaldi", "vivaldi.exe", 0), app("Discord", "discord.exe", 1), app("Spotify", "spotify.exe", 2)
        ], "vpn")
    ]


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        source = defaults()
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    source = self._merge(source, loaded)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                self.data = source
                self.save()
                return self.data
        self.data = source
        self.save()
        return self.data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _merge(self, base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(base)
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge(result[key], value)
            else:
                result[key] = value
        result["schema_version"] = SCHEMA_VERSION
        return result
