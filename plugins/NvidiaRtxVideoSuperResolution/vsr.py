from __future__ import annotations

from typing import Any

from backup import read_registry


VALUE_NAME = "_User_Global_VAL_SuperResolution"
MODE_TO_VALUE = {"off": 0, "1": 1, "2": 2, "3": 3, "4": 4, "auto": 5}
VALUE_TO_MODE = {value: mode for mode, value in MODE_TO_VALUE.items()}


def read_vsr() -> dict[str, Any]:
    registry = read_registry()
    value = registry["values"].get(VALUE_NAME)
    return {
        "source": "registry snapshot (read-only)",
        "value": value,
        "mode": VALUE_TO_MODE.get(value["value"]) if value else None,
        "registry": registry,
    }


def set_vsr(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError(
        "VSR write is not implemented safely: NVIDIA exposes this as an internal "
        "MessageBus command, not a DLL export, and the named-pipe protocol is unverified."
    )
