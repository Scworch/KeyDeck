#KeyDeck/keydeck/config.py
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
    slot_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    slot_hotkeys: dict[str, str] = field(default_factory=dict)
    auto_start: bool = True
    high_priority: bool = True

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

<<<<<<< HEAD
        def _positive_int(value: Any, fallback: int) -> int:
            try:
                # Avoid accepting fractional values silently (e.g. 2.5 -> 2).
                if isinstance(value, float) and not value.is_integer():
                    raise ValueError
                return int(value)
            except (TypeError, ValueError, OverflowError):
                return fallback

        slot_settings = data.get("slot_settings", {})
        if not isinstance(slot_settings, dict):
            slot_settings = {}

        slot_hotkeys = data.get("slot_hotkeys", {})
        if not isinstance(slot_hotkeys, dict):
            slot_hotkeys = {}

        settings = cls(
            rows=_positive_int(data.get("rows", defaults.rows), defaults.rows),
            columns=_positive_int(data.get("columns", defaults.columns), defaults.columns),
            button_size=button_size,
            slot_actions=slot_actions,
            slot_settings=slot_settings,
            slot_hotkeys=slot_hotkeys,
            auto_start=bool(data.get("auto_start", defaults.auto_start)),
            high_priority=bool(data.get("high_priority", defaults.high_priority)),
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

    def normalize_action_ids(
        self,
        valid_action_ids: set[str],
        aliases: dict[str, str] | None = None,
    ) -> bool:
        alias_map = aliases or {}
        changed = False
        normalized: list[str | None] = []

        for action_id in self.slot_actions:
            if not action_id:
                normalized.append(None)
                continue
            if action_id in valid_action_ids:
                normalized.append(action_id)
                continue

            alias_target = alias_map.get(action_id)
            if alias_target and alias_target in valid_action_ids:
                normalized.append(alias_target)
            else:
                normalized.append(None)
            changed = True

        if changed:
            self.slot_actions = normalized
            self._normalize_slots()
        return changed

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
