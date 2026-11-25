#KeyDeck/keydeck/config.py
from __future__ import annotations

import json
import math
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

IS_FROZEN = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = (
    Path(getattr(sys, "_MEIPASS"))
    if IS_FROZEN
    else Path(__file__).resolve().parent.parent
)
PLUGINS_DIR = PROJECT_ROOT / "plugins"
ICONS_DIR = PROJECT_ROOT / "icons"
_LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA") or str(
    Path.home() / "AppData" / "Local"
)
APP_DATA_DIR = (
    Path(_LOCAL_APP_DATA) / "KeyDeck"
    if IS_FROZEN
    else PROJECT_ROOT
)
CONFIG_DIR = APP_DATA_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PLUGIN_DATA_DIR = APP_DATA_DIR / "plugins"
INSTALLED_PLUGINS_DIR = APP_DATA_DIR / "installed_plugins"
PLUGIN_BACKUP_DIR = APP_DATA_DIR / "plugin_backups"


BUTTON_SIZE_MAP = {
    "small": 64,
    "medium": 84,
    "large": 108,
}


@dataclass
class DeckPage:
    page_id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Page 1"
    rows: int = 2
    columns: int = 4
    slot_actions: list[str | None] = field(default_factory=list)
    slot_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    slot_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> "DeckPage":
        rows = _positive_int(data.get("rows", 2), 2)
        columns = _positive_int(data.get("columns", 4), 4)
        raw_actions = data.get("slot_actions", [])
        actions = [
            item.strip() if isinstance(item, str) and item.strip() else None
            for item in raw_actions
        ] if isinstance(raw_actions, list) else []
        raw_settings = data.get("slot_settings", {})
        slot_settings = (
            {str(key): value for key, value in raw_settings.items() if isinstance(value, dict)}
            if isinstance(raw_settings, dict)
            else {}
        )
        slot_overrides = _normalize_slot_overrides(data.get("slot_overrides", {}))
        page_id = data.get("page_id")
        return cls(
            page_id=page_id.strip() if isinstance(page_id, str) and page_id.strip() else uuid4().hex,
            name=str(data.get("name", f"Page {index + 1}")).strip() or f"Page {index + 1}",
            rows=rows,
            columns=columns,
            slot_actions=actions,
            slot_settings=slot_settings,
            slot_overrides=slot_overrides,
        ).clamp()

    def clamp(self) -> "DeckPage":
        self.rows = max(1, min(self.rows, 8))
        self.columns = max(1, min(self.columns, 8))
        total = self.rows * self.columns
        self.slot_actions = list(self.slot_actions) + [None] * max(0, total - len(self.slot_actions))
        self.slot_settings = {
            str(key): value
            for key, value in self.slot_settings.items()
            if str(key).isdigit() and isinstance(value, dict)
        }
        self.slot_overrides = _normalize_slot_overrides(self.slot_overrides)
        return self


def _normalize_slot_overrides(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not str(key).isdigit() or not isinstance(value, dict):
            continue
        override: dict[str, Any] = {}
        for field_name in ("title", "icon_path"):
            field_value = value.get(field_name)
            if isinstance(field_value, str) and field_value.strip():
                override[field_name] = field_value.strip()
        image_mode = value.get("image_mode")
        if isinstance(image_mode, str) and image_mode in {"fill", "fit", "crop"}:
            override["image_mode"] = image_mode
        image_zoom = value.get("image_zoom")
        if isinstance(image_zoom, (int, float)) and not isinstance(image_zoom, bool):
            try:
                if math.isfinite(image_zoom):
                    override["image_zoom"] = max(0.2, min(float(image_zoom), 3.0))
            except (OverflowError, ValueError):
                pass
        for field_name in ("image_offset_x", "image_offset_y"):
            field_value = value.get(field_name)
            if isinstance(field_value, int) and not isinstance(field_value, bool):
                override[field_name] = max(-500, min(field_value, 500))
        if override:
            normalized[str(key)] = override
    return normalized


def _positive_int(value: Any, fallback: int) -> int:
    try:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


@dataclass
class AppSettings:
    rows: int = 2
    columns: int = 4
    button_size: str = "medium"
    slot_actions: list[str | None] = field(default_factory=list)
    slot_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    slot_hotkeys: dict[str, str] = field(default_factory=dict)
    right_alt_toggle: bool = False
    pages: list[DeckPage] = field(default_factory=list)
    active_page: int = 0
    infinite_scroll: bool = False
    auto_start: bool = True
    high_priority: bool = True
    run_as_admin: bool = False
    last_update_check: float = 0.0
    disabled_plugins: list[str] = field(default_factory=list)

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

        slot_settings = data.get("slot_settings", {})
        if not isinstance(slot_settings, dict):
            slot_settings = {}

        slot_hotkeys = data.get("slot_hotkeys", {})
        if not isinstance(slot_hotkeys, dict):
            slot_hotkeys = {}

        try:
            last_update_check = float(data.get("last_update_check", 0.0))
            if not math.isfinite(last_update_check):
                last_update_check = 0.0
        except (TypeError, ValueError, OverflowError):
            last_update_check = 0.0
        raw_disabled_plugins = data.get("disabled_plugins", [])
        disabled_plugins = list(
            dict.fromkeys(
                item.strip()
                for item in raw_disabled_plugins
                if isinstance(item, str) and item.strip()
            )
        ) if isinstance(raw_disabled_plugins, list) else []

        rows = _positive_int(data.get("rows", defaults.rows), defaults.rows)
        columns = _positive_int(data.get("columns", defaults.columns), defaults.columns)
        raw_pages = data.get("pages")
        if isinstance(raw_pages, list) and raw_pages:
            pages = [
                DeckPage.from_dict(item, index)
                for index, item in enumerate(raw_pages)
                if isinstance(item, dict)
            ]
        else:
            pages = [
                DeckPage(
                    page_id="page-1",
                    name="Page 1",
                    rows=rows,
                    columns=columns,
                    slot_actions=slot_actions,
                    slot_settings=slot_settings,
                ).clamp()
            ]
        if not pages:
            pages = [
                DeckPage(
                    page_id="page-1",
                    rows=rows,
                    columns=columns,
                    slot_actions=slot_actions,
                    slot_settings=slot_settings,
                ).clamp()
            ]

        settings = cls(
            rows=rows,
            columns=columns,
            button_size=button_size,
            slot_actions=slot_actions,
            slot_settings=slot_settings,
            slot_hotkeys=slot_hotkeys,
            right_alt_toggle=bool(data.get("right_alt_toggle", defaults.right_alt_toggle)),
            pages=pages,
            active_page=_positive_int(data.get("active_page", 0), 0),
            infinite_scroll=bool(data.get("infinite_scroll", False)),
            auto_start=bool(data.get("auto_start", defaults.auto_start)),
            high_priority=bool(data.get("high_priority", defaults.high_priority)),
            run_as_admin=bool(data.get("run_as_admin", defaults.run_as_admin)),
            last_update_check=last_update_check,
            disabled_plugins=disabled_plugins,
        )
        return settings.clamp()

    def clamp(self) -> "AppSettings":
        if self.button_size not in BUTTON_SIZE_MAP:
            self.button_size = "medium"
        self.disabled_plugins = list(
            dict.fromkeys(
                plugin_id.strip()
                for plugin_id in self.disabled_plugins
                if isinstance(plugin_id, str) and plugin_id.strip()
            )
        )
        if not self.pages:
            self.pages = [
                DeckPage(
                    page_id="page-1",
                    rows=self.rows,
                    columns=self.columns,
                    slot_actions=list(self.slot_actions),
                    slot_settings=dict(self.slot_settings),
                )
            ]
        self.pages = [page.clamp() for page in self.pages]
        page_ids: set[str] = set()
        for page in self.pages:
            if page.page_id in page_ids:
                page.page_id = uuid4().hex
            page_ids.add(page.page_id)
        self.active_page = max(0, min(self.active_page, len(self.pages) - 1))
        first_page = self.pages[0]
        self.rows = first_page.rows
        self.columns = first_page.columns
        self.slot_actions = list(first_page.slot_actions)
        self.slot_settings = dict(first_page.slot_settings)
        return self

    def button_pixels(self) -> int:
        return BUTTON_SIZE_MAP[self.button_size]

    def normalize_action_ids(
        self,
        valid_action_ids: set[str],
        aliases: dict[str, str] | None = None,
        preserved_plugin_ids: set[str] | None = None,
        alias_settings_defaults: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        alias_map = aliases or {}
        settings_defaults = alias_settings_defaults or {}
        preserved_prefixes = tuple(
            f"{plugin_id}."
            for plugin_id in (preserved_plugin_ids or set())
        )
        changed = False
        for page in self.pages:
            normalized: list[str | None] = []
            for slot, action_id in enumerate(page.slot_actions):
                if (
                    not action_id
                    or action_id in valid_action_ids
                ):
                    normalized.append(action_id)
                    continue
                replacement = alias_map.get(action_id)
                if replacement:
                    normalized.append(replacement)
                    defaults = settings_defaults.get(action_id)
                    if defaults:
                        merged_settings = dict(defaults)
                        merged_settings.update(page.slot_settings.get(str(slot), {}))
                        page.slot_settings[str(slot)] = merged_settings
                    changed = True
                elif action_id.startswith(preserved_prefixes):
                    normalized.append(action_id)
                else:
                    normalized.append(None)
                    changed = True
            if normalized != page.slot_actions:
                page.slot_actions = normalized
        self.clamp()
        return changed

    def resolve_hotkey_key(self, key: str) -> tuple[int, int] | None:
        if ":" not in key:
            try:
                slot = int(key)
            except ValueError:
                return None
            return (
                (0, slot)
                if self.pages and 0 <= slot < self.pages[0].rows * self.pages[0].columns
                else None
            )
        page_id, slot_text = key.rsplit(":", 1)
        try:
            slot = int(slot_text)
        except ValueError:
            return None
        for page_index, page in enumerate(self.pages):
            if page.page_id == page_id and 0 <= slot < page.rows * page.columns:
                return page_index, slot
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_settings() -> AppSettings:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_FILE.exists():
        if IS_FROZEN:
            legacy_file = Path(sys.executable).resolve().parent / "config" / "settings.json"
            if legacy_file.is_file():
                shutil.copy2(legacy_file, SETTINGS_FILE)
        if SETTINGS_FILE.exists():
            return _read_settings()
        return AppSettings()

    return _read_settings()


def _read_settings() -> AppSettings:
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
