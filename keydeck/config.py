from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = PROJECT_ROOT / "plugins"
ICONS_DIR = PROJECT_ROOT / "icons"
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class AppSettings:
    rows: int = 2
    columns: int = 4
    button_size: int = 84
    gap: int = 12

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        defaults = cls()
        settings = cls(
            rows=int(data.get("rows", defaults.rows)),
            columns=int(data.get("columns", defaults.columns)),
            button_size=int(data.get("button_size", defaults.button_size)),
            gap=int(data.get("gap", defaults.gap)),
        )
        return settings.clamp()

    def clamp(self) -> "AppSettings":
        self.rows = max(1, min(self.rows, 8))
        self.columns = max(1, min(self.columns, 8))
        self.button_size = max(48, min(self.button_size, 140))
        self.gap = max(4, min(self.gap, 30))
        return self

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def load_settings() -> AppSettings:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_FILE.exists():
        return AppSettings()

    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return AppSettings.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return AppSettings()


def save_settings(settings: AppSettings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings.clamp().to_dict(), indent=2),
        encoding="utf-8",
    )
