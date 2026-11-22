from __future__ import annotations

import datetime
import os
from typing import Any

import psutil


def value(widget: dict[str, Any]) -> str:
    source = str(widget.get("source", ""))
    if source == "clock":
        return datetime.datetime.now().strftime("%H:%M")
    if source == "date":
        return datetime.datetime.now().strftime("%d.%m.%Y")
    if source == "memory":
        return f"RAM {psutil.virtual_memory().percent}%"
    if source == "cpu":
        return f"CPU {psutil.cpu_percent(interval=None):.0f}%"
    if source == "hostname":
        return os.environ.get("COMPUTERNAME", "PC")
    return str(widget.get("title", source))
