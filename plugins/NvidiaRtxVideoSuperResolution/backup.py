from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
import winreg


REGISTRY_PATH = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def read_registry() -> dict[str, Any]:
    values: dict[str, Any] = {}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH, 0, winreg.KEY_READ) as key:
        count = winreg.QueryInfoKey(key)[1]
        for index in range(count):
            name, value, value_type = winreg.EnumValue(key, index)
            values[name] = {"value": _json_value(value), "type": value_type}
    return {"path": f"HKLM\\{REGISTRY_PATH}", "values": values}


def create_backup(path: Path) -> None:
    backup = {
        "created_at": datetime.now().astimezone().isoformat(),
        "registry": read_registry(),
    }
    path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
