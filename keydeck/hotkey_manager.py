from __future__ import annotations

import logging
import threading
from typing import Callable

import keyboard
from PySide6.QtCore import QObject, Signal, QTimer

logger = logging.getLogger(__name__)

class HotkeySignal(QObject):
    triggered = Signal(int)


class HotkeyManager:
    """Manages global hotkeys using the keyboard module."""

    def __init__(self, callback: Callable[[int], None]) -> None:
        self._callback = callback
        self._signal = HotkeySignal()
        self._signal.triggered.connect(self._on_triggered)
        self._active_hotkeys: dict[str, str] = {}

    def _on_triggered(self, slot: int) -> None:
        self._callback(slot)

    def _trigger_slot(self, slot: int) -> None:
        self._signal.triggered.emit(slot)

    def apply_hotkeys(self, slot_hotkeys: dict[str, str]) -> None:
        """Applies a new set of hotkeys, unregistering old ones."""
        keyboard.unhook_all()
        self._active_hotkeys = dict(slot_hotkeys)

        for slot_str, key_combo in self._active_hotkeys.items():
            if not key_combo:
                continue
            try:
                slot_idx = int(slot_str)
                # We use lambda to capture the current slot_idx
                # Adding suppress=True might prevent other apps from seeing it, but keyboard hook sometimes breaks.
                keyboard.add_hotkey(
                    key_combo,
                    lambda s=slot_idx: self._trigger_slot(s),
                    suppress=True
                )
            except Exception as e:
                logger.error(f"Failed to bind hotkey '{key_combo}' for slot {slot_str}: {e}")

    def stop(self) -> None:
        keyboard.unhook_all()
