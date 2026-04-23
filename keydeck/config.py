from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = PROJECT_ROOT / "plugins"
ICONS_DIR = PROJECT_ROOT / "icons"
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


BUTTON_SIZE_MAP = {
    "small": 64,
    "medium": 84,
    "large": 108,
}


@dataclass
class AppSettings:
    rows: int = 2
    columns: int = 4
    button_size: str = "medium"
    slot_actions: list[str | None] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        defaults = cls()
        button_size = str(data.get("button_size", data.get("button_scale", defaults.button_size)))
        if button_size not in BUTTON_SIZE_MAP:
            legacy_px = data.get("button_size")
            if isinstance(legacy_px, int):
                if legacy_px <= 70:
                    button_size = "small"
                elif legacy_px >= 96:
                    button_size = "large"
                else:
                    button_size = "medium"
            else:
                button_size = defaults.button_size

        raw_slots = data.get("slot_actions", [])
        slot_actions: list[str | None] = []
        if isinstance(raw_slots, list):
            for item in raw_slots:
                if isinstance(item, str) and item.strip():
                    slot_actions.append(item.strip())
                else:
                    slot_actions.append(None)

        settings = cls(
            rows=int(data.get("rows", defaults.rows)),
            columns=int(data.get("columns", defaults.columns)),
            button_size=button_size,
            slot_actions=slot_actions,
        )
        return settings.clamp()

    def clamp(self) -> "AppSettings":
        self.rows = max(1, min(self.rows, 8))
        self.columns = max(1, min(self.columns, 8))
        if self.button_size not in BUTTON_SIZE_MAP:
            self.button_size = "medium"
        self._normalize_slots()
        return self

    def _normalize_slots(self) -> None:
        total = self.rows * self.columns
        current = list(self.slot_actions)
        if len(current) < total:
            current.extend([None] * (total - len(current)))
        self.slot_actions = current[:total]

    def button_pixels(self) -> int:
        return BUTTON_SIZE_MAP[self.button_size]

    def to_dict(self) -> dict[str, Any]:
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
